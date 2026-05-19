"""Keyword matching for content."""

import re
from typing import Any, Dict, List

from app.models import Keyword
from app.services.keyword_rules import dedupe_keywords_case_insensitive, normalize_keyword_value
from app.utils.logger import get_logger

logger = get_logger(__name__)
MAX_REGEX_LENGTH = 256
_UNSAFE_REGEX_PATTERNS = (
    (re.compile(r"\\[1-9]"), "backreferences are disallowed"),
    (re.compile(r"\(\?<([=!])"), "lookbehind assertions are disallowed"),
    (
        re.compile(r"\((?:[^()\\]|\\.)+\)(?:\+|\*|\{\d+(?:,\d*)?\})(?:\+|\*|\{\d+(?:,\d*)?\})"),
        "nested quantified groups are disallowed",
    ),
    # 独立嵌套量词：a+*、a{1,}+ 等变体
    (
        re.compile(r"(?:\+|\*|\{\d+(?:,\d*)?\})(?:\+|\*|\{\d+(?:,\d*)?\})"),
        "consecutive quantifiers are disallowed",
    ),
)
_REGEX_MATCH_TIMEOUT_SECONDS = 2
# Non-main-thread / no-SIGALRM: bound input size to reduce ReDoS blast radius (with pattern validation).
_REGEX_TEXT_CLIP_NONMAIN = 16_000


class KeywordMatcher:
    """Match keywords in content."""
    
    def match(
        self,
        title: str,
        body: str,
        keywords: List[Keyword]
    ) -> List[Dict[str, Any]]:
        """
        Match keywords in text.
        
        Args:
            title: Title text to search in
            body: Body text to search in
            keywords: List of Keyword model instances
        
        Returns:
            List of matched keywords with metadata
        """
        if not keywords:
            return []
        
        matches = []
        
        for keyword in keywords:
            if not keyword.enabled:
                continue
            
            match_result = self._check_match(title or "", body or "", keyword)

            if match_result:
                matches.append({
                    "id": str(keyword.id),
                    "keyword": keyword.keyword,
                    "color": keyword.color,
                    "match_type": keyword.match_type,
                    "match_scope": getattr(keyword, "match_scope", "title_content"),
                    "matched_scope": match_result["matched_scope"],
                    "matched_term": match_result["matched_term"],
                })
                logger.debug(f"Matched keyword: {keyword.keyword}")
        
        return matches
    
    def _check_match(self, title: str, body: str, keyword: Keyword) -> dict[str, str] | None:
        """Check if keyword matches in its configured scope."""
        for scope_name, scope_text in self._iter_scope_texts(title, body, keyword):
            if not scope_text:
                continue

            if self._matches_text(scope_text, keyword.keyword, keyword):
                return {"matched_scope": scope_name, "matched_term": keyword.keyword}

            for equivalent in self._keyword_terms(keyword):
                if self._matches_text(scope_text, equivalent, keyword):
                    return {"matched_scope": scope_name, "matched_term": equivalent}

        return None

    @staticmethod
    def _iter_scope_texts(title: str, body: str, keyword: Keyword) -> list[tuple[str, str]]:
        match_scope = getattr(keyword, "match_scope", "title_content") or "title_content"
        if match_scope == "title":
            return [("title", title)]
        if match_scope == "content":
            return [("content", body)]
        return [("title", title), ("content", body)]

    @staticmethod
    def _keyword_terms(keyword: Keyword) -> list[str]:
        equivalents = getattr(keyword, "equivalent_terms", None) or []
        terms, _ = dedupe_keywords_case_insensitive(
            [keyword.keyword, *[str(item) for item in equivalents]]
        )
        return [term for term in terms if normalize_keyword_value(term) != normalize_keyword_value(keyword.keyword)]

    def _matches_text(self, text: str, candidate: str, keyword: Keyword) -> bool:
        search_text = text if keyword.case_sensitive else text.lower()
        search_candidate = candidate if keyword.case_sensitive else candidate.lower()

        if keyword.match_type == "exact":
            pattern = self._exact_pattern(search_candidate)
            return bool(re.search(pattern, search_text))

        if keyword.match_type == "contains":
            return search_candidate in search_text

        if keyword.match_type == "regex":
            is_safe, reason = self._validate_regex_pattern(candidate)
            if not is_safe:
                logger.warning("Rejected unsafe regex pattern '%s': %s", candidate, reason)
                return False

            flags = 0 if keyword.case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(candidate, flags)
                return self._safe_regex_search(compiled, text)
            except Exception as e:
                logger.error(f"Regex error for {candidate}: {e}")
                return False

        return False

    @staticmethod
    def _exact_pattern(candidate: str) -> str:
        escaped = re.escape(candidate)
        if re.search(r"[A-Za-z0-9_]", candidate):
            return rf"\b{escaped}\b"
        return escaped

    def _validate_regex_pattern(self, pattern: str) -> tuple[bool, str]:
        """Reject regex features that are common ReDoS footguns for user input."""
        candidate = str(pattern or "")
        if not candidate:
            return False, "pattern is empty"
        if len(candidate) > MAX_REGEX_LENGTH:
            return False, f"pattern exceeds {MAX_REGEX_LENGTH} characters"

        for compiled, reason in _UNSAFE_REGEX_PATTERNS:
            if compiled.search(candidate):
                return False, reason

        try:
            re.compile(candidate)
        except re.error as exc:
            return False, f"invalid regex: {exc}"

        return True, "ok"

    @staticmethod
    def _safe_regex_search(compiled: re.Pattern, text: str) -> bool:
        """执行正则搜索，限时 _REGEX_MATCH_TIMEOUT_SECONDS 秒防止 ReDoS。"""
        import signal
        import sys
        import threading

        clip = _REGEX_TEXT_CLIP_NONMAIN

        def _run(subj: str) -> bool:
            return bool(compiled.search(subj))

        # Windows / no SIGALRM: bounded input only
        if sys.platform == "win32" or not hasattr(signal, "SIGALRM"):
            return _run(text[:clip])

        # Worker threads cannot use signal.alarm reliably
        if threading.current_thread() is not threading.main_thread():
            return _run(text[:clip])

        def _timeout_handler(signum, frame):
            raise TimeoutError("regex match timed out")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(_REGEX_MATCH_TIMEOUT_SECONDS)
        try:
            return _run(text)
        except TimeoutError:
            logger.warning("Regex timed out after %ds: %s", _REGEX_MATCH_TIMEOUT_SECONDS, compiled.pattern[:80])
            return False
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    
    def highlight_matches(
        self,
        text: str,
        matches: List[Dict[str, Any]],
        tag: str = "mark"
    ) -> str:
        """
        Add HTML highlighting to matched keywords in text.
        
        Args:
            text: Original text
            matches: List of matched keywords from match()
            tag: HTML tag to use for highlighting
        
        Returns:
            Text with highlighted keywords
        """
        if not matches:
            return text
        
        highlighted = text
        
        # Sort by length (longest first) to handle overlapping matches
        sorted_matches = sorted(matches, key=lambda x: len(x["keyword"]), reverse=True)
        
        for match in sorted_matches:
            keyword = match["keyword"]
            color = match.get("color", "#ff4d4f")
            
            # Create case-insensitive pattern that preserves original case
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)

            # Bind the per-iteration color/tag into defaults so each replacement
            # uses this keyword's styling instead of the final loop values.
            def replace_func(m, _color=color, _tag=tag):
                return f'<{_tag} style="background-color: {_color}; padding: 0 2px;">{m.group()}</{_tag}>'

            highlighted = pattern.sub(replace_func, highlighted)
        
        return highlighted
    
    def get_match_context(
        self,
        text: str,
        keyword: str,
        context_chars: int = 100
    ) -> List[str]:
        """
        Get text snippets around keyword matches.
        
        Args:
            text: Text to search in
            keyword: Keyword to find
            context_chars: Number of characters of context on each side
        
        Returns:
            List of context snippets
        """
        contexts = []
        
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        
        for match in pattern.finditer(text):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            
            snippet = text[start:end]
            
            # Add ellipsis if truncated
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            
            contexts.append(snippet)
        
        return contexts
