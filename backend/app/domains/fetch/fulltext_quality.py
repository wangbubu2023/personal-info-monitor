"""Explainable full-text quality layer.

"Fetched HTML" is not the same as "fetched an article". This module inspects
the extracted title/body text (plus light fetch metadata) and produces a
structured :class:`FulltextQuality` verdict that distinguishes *why* a body is
unusable — login wall, captcha, bot wall, paywall, boilerplate-only, a
non-article listing page, or simply empty — instead of collapsing everything
into a single ``blocked`` bucket.

It is deliberately model-free and pure (text in, verdict out) so it can run on
the fetch hot-path and be exhaustively unit-tested. It *complements*
``app.domains.ingest.quality_metadata`` (which assigns the coarse
``fulltext_status`` used by scoring): the richer ``status`` here maps back onto
those coarse buckets via :meth:`FulltextQuality.coarse_status`, while the
``reason`` / ``boilerplate_ratio`` / ``title_match_score`` are stamped into
``Content.metadata_`` for diagnostics (plan §7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.domains.contracts.content_quality import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    FULLTEXT_STATUS_TITLE_ONLY,
)
from app.utils.text import strip_html_tags

FulltextStatus = Literal[
    "full",
    "partial",
    "summary_only",
    "title_only",
    "blocked",
    "login_required",
    "bot_wall",
    "captcha",
    "boilerplate_only",
    "non_article",
    "empty",
]

# Wall / interstitial phrase markers (lower-cased substring match, EN + ZH).
_LOGIN_MARKERS = (
    "sign in to continue", "please log in", "please sign in", "log in to read",
    "subscribe to continue", "subscribers only", "create a free account",
    "登录后查看", "请登录", "登录后阅读", "登录以继续", "注册后阅读", "开通会员", "登录账号",
)
_PAYWALL_MARKERS = (
    "this article is for subscribers", "to continue reading", "unlock this article",
    "become a member", "start your free trial", "this content is reserved",
    "付费阅读", "订阅后阅读", "会员专享", "开通订阅",
)
_CAPTCHA_MARKERS = (
    "captcha", "i'm not a robot", "verify you are human", "are you a robot",
    "请完成验证", "人机验证", "安全验证", "滑动验证",
)
_BOT_WALL_MARKERS = (
    "access denied", "you have been blocked", "request blocked",
    "attention required", "cloudflare", "ddos protection by",
    "enable javascript and cookies to continue", "checking your browser",
    "访问被拒绝", "您的访问被拒绝", "访问受限",
)
# Boilerplate lines that dominate non-article / shell pages.
_BOILERPLATE_LINE_MARKERS = (
    "cookie", "privacy policy", "terms of service", "all rights reserved",
    "subscribe", "newsletter", "sign up", "follow us", "advertisement",
    "©", "menu", "search", "home", "contact us",
    "隐私政策", "服务条款", "版权所有", "订阅", "广告", "关注我们", "免责声明",
    "关于我们", "网站声明", "联系方式", "用户反馈", "网站地图", "友情链接",
    "关联话题", "举报电话", "举报邮箱", "沪ICP备", "沪公网安备",
    "互联网新闻信息服务许可证",
)


@dataclass(frozen=True)
class FulltextQuality:
    status: FulltextStatus
    score: float
    reason: str
    text_chars: int
    title_match_score: float | None = None
    boilerplate_ratio: float | None = None

    _BLOCKED_LIKE = frozenset({"login_required", "bot_wall", "captcha"})

    def is_blocked(self) -> bool:
        return self.status in self._BLOCKED_LIKE or self.status == "blocked"

    def coarse_status(self) -> str:
        """Map the rich status back onto the coarse FULLTEXT_STATUS_* buckets."""
        if self.status == FULLTEXT_STATUS_FULL:
            return FULLTEXT_STATUS_FULL
        if self.status == FULLTEXT_STATUS_PARTIAL:
            return FULLTEXT_STATUS_PARTIAL
        if self.status == FULLTEXT_STATUS_SUMMARY_ONLY:
            return FULLTEXT_STATUS_SUMMARY_ONLY
        if self.status == FULLTEXT_STATUS_TITLE_ONLY:
            return FULLTEXT_STATUS_TITLE_ONLY
        # login_required / bot_wall / captcha / boilerplate_only / non_article /
        # empty / blocked all collapse to "blocked" for the scoring gate.
        return FULLTEXT_STATUS_BLOCKED

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "fulltext_status": self.coarse_status(),
            "fulltext_quality_status": self.status,
            "fulltext_quality_score": self.score,
            "fulltext_reason": self.reason,
            "text_chars": self.text_chars,
        }
        if self.title_match_score is not None:
            payload["title_match_score"] = self.title_match_score
        if self.boilerplate_ratio is not None:
            payload["boilerplate_ratio"] = self.boilerplate_ratio
        return payload


def _clean(text: Any) -> str:
    return strip_html_tags(str(text or "")).strip()


def _contains_any(haystack: str, markers: tuple[str, ...]) -> bool:
    return any(marker in haystack for marker in markers)


def _split_lines(text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _distinct_boilerplate_markers(text_lower: str) -> int:
    """Count distinct boilerplate markers present anywhere in the text.

    ``strip_html_tags`` collapses newlines, so we can't rely on per-line
    detection; counting distinct nav/footer markers is robust to that.
    """
    return sum(1 for marker in _BOILERPLATE_LINE_MARKERS if marker in text_lower)


def _boilerplate_ratio(text_lower: str) -> float:
    distinct = _distinct_boilerplate_markers(text_lower)
    return round(min(1.0, distinct / 6.0), 3)


def _title_match_score(title: str, body: str) -> float | None:
    title = title.strip().lower()
    body = body.lower()
    if not title:
        return None
    tokens = [t for t in re.split(r"\W+", title) if len(t) >= 3]
    if not tokens:
        return 1.0 if title in body else 0.0
    hit = sum(1 for t in tokens if t in body)
    return round(hit / len(tokens), 3)


def _url_looks_like_article(url: str) -> bool:
    from app.domains.fetch.collectors.website_helpers import looks_like_article_url

    try:
        return looks_like_article_url(url, url)
    except Exception:  # noqa: BLE001 — heuristic only
        return False


def assess_fulltext_quality(
    *,
    title: str = "",
    body: str | None = None,
    summary: str | None = None,
    url: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> FulltextQuality:
    """Classify *why* a fetched body is (un)usable into a rich status + reason."""
    metadata = metadata if isinstance(metadata, Mapping) else {}
    title_text = _clean(title)
    body_text = _clean(body)
    summary_text = _clean(summary)
    wall_blob = f"{title_text}\n{body_text}\n{summary_text}".lower()

    body_len = len(body_text)
    summary_len = len(summary_text)
    title_len = len(title_text)
    lines = _split_lines(body_text)
    distinct_boilerplate = _distinct_boilerplate_markers(body_text.lower())
    boilerplate_ratio = _boilerplate_ratio(body_text.lower())
    title_match = _title_match_score(title_text, body_text)

    short_body = body_len < 400

    # 1. Hard walls — only trust them when the body is short (a full article that
    #    merely *mentions* "captcha" shouldn't be flagged).
    if short_body and _contains_any(wall_blob, _CAPTCHA_MARKERS):
        return FulltextQuality("captcha", 0.0, "captcha_detected", body_len, title_match, boilerplate_ratio)
    if short_body and _contains_any(wall_blob, _BOT_WALL_MARKERS):
        return FulltextQuality("bot_wall", 0.0, "bot_wall_detected", body_len, title_match, boilerplate_ratio)
    if short_body and (_contains_any(wall_blob, _LOGIN_MARKERS) or _contains_any(wall_blob, _PAYWALL_MARKERS)):
        return FulltextQuality("login_required", 0.0, "login_or_paywall", body_len, title_match, boilerplate_ratio)

    # 2. Nothing at all.
    if body_len == 0 and summary_len == 0 and title_len == 0:
        return FulltextQuality("empty", 0.0, "no_text", 0, None, None)

    # 3. Boilerplate-dominated page (nav / footer template, not an article).
    # Keep the check bounded to sub-1200-char candidates so a legitimate long
    # article with a small publisher footer is not rejected. The old <400
    # boundary let 400-600-char navigation shells pass as ``partial``.
    if body_len < 1200 and distinct_boilerplate >= 3:
        return FulltextQuality("boilerplate_only", 0.05, "boilerplate_dominated", body_len, title_match, boilerplate_ratio)

    # 4. Looks like a listing / non-article page: real-but-short text, the URL is
    #    not an article and the title barely appears in the body. Requires actual
    #    body text so empty-body summary/title rows fall through to (5).
    if (
        short_body
        and body_len >= 50
        and url
        and not _url_looks_like_article(url)
        and (title_match is not None and title_match < 0.34)
    ):
        return FulltextQuality("non_article", 0.08, "non_article_url", body_len, title_match, boilerplate_ratio)

    # 5. Length-based grading for genuine bodies.
    paragraphs = len([ln for ln in lines if len(ln) >= 40]) or (1 if body_len >= 80 else 0)
    if body_len >= 1200 and paragraphs >= 3:
        score = max(0.78, min(1.0, body_len / 2400.0 + 0.1 * paragraphs))
        return FulltextQuality("full", round(score, 3), "full_body", body_len, title_match, boilerplate_ratio)
    if body_len >= 400 or (body_len >= 220 and paragraphs >= 2):
        return FulltextQuality("partial", 0.55, "partial_body", body_len, title_match, boilerplate_ratio)
    if summary_len >= 50:
        return FulltextQuality("summary_only", 0.3, "summary_only", body_len, title_match, boilerplate_ratio)
    if title_len > 0:
        return FulltextQuality("title_only", 0.12, "title_only", body_len, title_match, boilerplate_ratio)
    return FulltextQuality("empty", 0.0, "no_usable_text", body_len, title_match, boilerplate_ratio)


__all__ = [
    "FulltextStatus",
    "FulltextQuality",
    "assess_fulltext_quality",
]
