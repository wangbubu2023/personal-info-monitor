# Score Module Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复评分模块中 subjective 权重无效、reach 区分度低、英文实体误匹配、中文聚类质量差等问题，并实现最小可行 LLM 主观分接入口。

**Architecture:** 分为三个层次：(1) 确定性规则层调优（权重/词边界/reach 细化），(2) 轻量 LLM 主观分实装（复用现有 `ModelProviderClient`，只对 candidate 区间文章异步补分），(3) 可观测性工具（feedback 汇总脚本）。所有变更向后兼容，不改 metadata 存储 schema。

**Tech Stack:** Python 3.14, SQLAlchemy async, `app.ai.provider.ModelProviderClient`, pytest

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/domains/score/scoring.py` | 修改 | ScoringConfig 权重重分配；recommendation_reason 过滤 subjective；confidence 透明化 |
| `app/domains/score/score_rules.py` | 修改 | score_reach 增加 S-tier sub-bucket；_corpus 用户词 limit 上调 |
| `app/domains/score/score_vocab_runtime.py` | 修改 | entity_tier_score 英文词边界保护 |
| `app/domains/score/score_subjective.py` | 修改 | 实现 LlmSubjectiveScorer；resolve_subjective_score async 路径接通 |
| `app/services/ranking_service.py` | 修改 | _tokenize 中文 trigram 改善 Jaccard 计算 |
| `app/platform/config/system_settings.py` | 修改 | DEFAULT_SYSTEM_SETTINGS 增加 score_model |
| `app/ai/provider.py` | 修改 | get_runtime_from_system_settings 支持 score_model |
| `scripts/feedback_summary.py` | 新建 | 查询 ScoreFeedback 生成调参建议报告 |
| `tests/test_score_v2_rules.py` | 修改 | 补充 reach sub-bucket、词边界、中文聚类测试 |

---

## Task 1: 重分配 subjective 权重，调整阈值

**背景**：subjective 维度固定 5.0，20% 权重对所有文章贡献相同，实际上是在给每篇文章加固定 10 分，导致阈值 75/60 的语义不透明。把 20% 按比例分配给其余四维，阈值相应下调到 70/55，评分行为等效但公式透明。

**Files:**
- Modify: `backend/app/domains/score/scoring.py`

- [ ] **Step 1: 修改 ScoringConfig 默认权重和阈值**

在 `scoring.py:46-55`，将 `ScoringConfig` 改为：

```python
@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: {
        "salience": 0.30,
        "reach": 0.25,
        "authority": 0.25,
        "depth": 0.20,
        "subjective": 0.0,   # disabled until LLM subjective scoring is live
    })
    selected_threshold: float = 70.0
    candidate_threshold: float = 55.0
    minimum_selected_confidence: float = 0.65
```

- [ ] **Step 2: 修复 build_recommendation_reason 中 subjective 误报**

在 `scoring.py:104-110`，`high_dimensions` 列表生成处，跳过 `subjective` 维度（因为它只是固定占位，并非真实信号）：

```python
high_dimensions = [
    DIMENSION_LABELS[key]
    for key in ("salience", "reach", "authority", "depth")  # subjective excluded: fixed baseline
    if scores.get(key, 0.0) >= 7.0 and key in DIMENSION_LABELS
]
```

- [ ] **Step 3: 运行测试确认通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

预期：全部通过（阈值变更后部分断言可能需要同步更新，见下步）。

- [ ] **Step 4: 更新受阈值影响的测试断言**

`tests/test_score_v2_rules.py:104-118`（`test_calculate_article_score_selected_threshold`），断言分数范围不变，但 `selection_status` 可能因阈值变化而不同。检查并更新：

```python
def test_calculate_article_score_selected_threshold():
    result = calculate_article_score(
        {
            "salience": 9.0,
            "reach": 9.0,
            "authority": 8.5,
            "depth": 7.0,
            "subjective": 5.0,
        },
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
        lane="tech_product",
    )
    assert result["selection_status"] == "selected"   # 新权重下 score=(0.30*9+0.25*9+0.25*8.5+0.20*7)*10=84.75 ≥ 70
    assert result["article_score"] >= 60
```

- [ ] **Step 5: 补充一条 high_dimensions 不含 subjective 的断言**

在 `tests/test_score_v2_rules.py` 末尾追加：

```python
def test_recommendation_reason_excludes_subjective_from_high_dimensions():
    from app.domains.score.scoring import build_recommendation_reason
    reason = build_recommendation_reason(
        {"salience": 9.0, "reach": 7.0, "authority": 8.5, "depth": 6.0, "subjective": 5.0},
        final_score=80.0,
        selection_status="selected",
        source_stars=3,
        score_confidence=0.85,
    )
    dims = reason["why_matters"]
    assert "主观判断" not in dims  # subjective never appears in high_dimensions
```

- [ ] **Step 6: 全部通过后提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/scoring.py backend/tests/test_score_v2_rules.py
git commit -m "fix(score): redistribute subjective weight 20%→0% across rule dims; adjust thresholds to 70/55"
```

---

## Task 2: score_confidence 透明化 —— 增加 confidence_limited_by_fulltext 标志

**背景**：`title_only` 状态的文章由于 `evidence_confidence=0.22`，即使 salience 打了高分，confidence 也永远低于 0.65，导致 score ≥ 70 的文章被静默降为 candidate。加一个显式字段让用户知道是置信度限制而非分数不够。

**Files:**
- Modify: `backend/app/domains/score/scoring.py`

- [ ] **Step 1: 在 calculate_article_score 中增加 confidence_limited_by_fulltext 字段**

在 `scoring.py:177-205` 的 `calculate_article_score` 函数，在 `selection_status` 判断后，在 `return` dict 中追加字段：

```python
# After existing selection_status logic:
confidence_limited = (
    article_score >= config.selected_threshold
    and score_confidence < config.minimum_selected_confidence
)

# In the return dict, add:
return {
    ...  # existing fields unchanged
    "confidence_limited_by_fulltext": confidence_limited,
}
```

具体：将 `calculate_article_score` 函数的 return 语句改为在现有字段末尾追加：

```python
    return {
        "score_version": SCORE_VERSION,
        "lane": lane,
        "dimension_scores": normalized_scores,
        "subjective_meta": subj_meta,
        "source_stars": source_stars,
        "score_confidence": score_confidence,
        "article_score": article_score,
        "final_score": article_score,
        "selection_status": selection_status,
        "confidence_limited_by_fulltext": (
            article_score >= config.selected_threshold
            and score_confidence < config.minimum_selected_confidence
        ),
        "recommendation_reason": build_recommendation_reason(
            normalized_scores,
            content_metadata=content_metadata,
            source_metadata=source_metadata,
            final_score=article_score,
            selection_status=selection_status,
            source_stars=source_stars,
            score_confidence=score_confidence,
            lane=lane,
        ),
    }
```

- [ ] **Step 2: 添加测试**

```python
def test_confidence_limited_flag_for_title_only():
    result = calculate_article_score(
        {"salience": 9.0, "reach": 9.0, "authority": 8.5, "depth": 4.0, "subjective": 5.0},
        content_metadata={"fulltext_status": "title_only", "content_quality": 0.5},
        source_metadata={"source_stars": 3},
    )
    # title_only evidence_confidence=0.22, score will be high but confidence low
    assert result["confidence_limited_by_fulltext"] is True
    assert result["selection_status"] == "candidate"


def test_confidence_limited_flag_false_for_full_content():
    result = calculate_article_score(
        {"salience": 9.0, "reach": 9.0, "authority": 8.5, "depth": 7.0, "subjective": 5.0},
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
    )
    assert result["confidence_limited_by_fulltext"] is False
    assert result["selection_status"] == "selected"
```

- [ ] **Step 3: 运行测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

- [ ] **Step 4: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/scoring.py backend/tests/test_score_v2_rules.py
git commit -m "feat(score): add confidence_limited_by_fulltext flag when title_only blocks selection"
```

---

## Task 3: score_reach 增加 S-tier entity 的 major_entity 子桶（6.5 分）

**背景**：reach 目前只有 4 个硬编码返回值（9.0/7.0/5.5/3.5），大量文章落在 entity=5.5 无区分度。S-tier 实体（Fed、白宫、OpenAI 等）天然具有 sector 级影响面，在无显式 reach 关键词时给予 6.5 的 major_entity 分，介于 entity 和 sector 之间。

**Files:**
- Modify: `backend/app/domains/score/score_rules.py`
- Modify: `backend/app/domains/score/score_vocab.py`

- [ ] **Step 1: 在 score_vocab.py 中将 major_entity reach 分值加入 REACH_SCORES**

在 `score_vocab.py:369`：

```python
REACH_SCORES = {"systemic": 9.0, "sector": 7.0, "major_entity": 6.5, "entity": 5.5, "local": 3.5}
```

- [ ] **Step 2: 修改 score_reach 签名，增加可选 runtime_vocab 参数**

将 `score_rules.py:132-144` 的 `score_reach` 函数改为：

```python
def score_reach(
    title: str,
    summary: str | None,
    full_content: str | None,
    *,
    runtime_vocab: "RuntimeScoringVocab | None" = None,
) -> float:
    del full_content  # reach is headline-scoped; body mentions are often incidental
    corpus = _headline_corpus(title, summary)
    title_l = (title or "").lower()
    has_disaster = any(term.lower() in corpus for term in DISASTER_TERMS)
    if has_disaster and any(k in title_l for k in ("多地", "多个省份", "数个省份", "跨省")):
        if any(term.lower() in title_l for term in CASUALTY_TERMS):
            return REACH_SCORES["systemic"]
        return REACH_SCORES["sector"]
    for level in ("systemic", "sector", "local"):
        if any(kw.lower() in corpus for kw in REACH_KEYWORDS[level]):
            return REACH_SCORES[level]
    # S-tier entity in headline → major_entity (6.5), between entity and sector
    if runtime_vocab is not None:
        from app.domains.score.score_vocab import ENTITY_TIER_S
        if any(term.lower() in corpus.lower() for term in ENTITY_TIER_S):
            return REACH_SCORES["major_entity"]
    return REACH_SCORES["entity"]
```

注意：需要在文件顶部的 `from __future__ import annotations` 已存在，所以类型注解字符串形式 `"RuntimeScoringVocab | None"` 可避免循环导入。

- [ ] **Step 3: 在 compute_rule_dimension_scores 中传递 runtime_vocab 给 score_reach**

在 `score_rules.py:197-229`，`compute_rule_dimension_scores` 函数内，将 `score_reach` 调用改为：

```python
dimensions = {
    "salience": score_salience(resolved_title, summary, full_content, runtime_vocab=runtime_vocab),
    "reach": score_reach(resolved_title, summary, full_content, runtime_vocab=runtime_vocab),
    "authority": score_authority(source_metadata),
    "depth": score_depth(
        title=resolved_title,
        summary=summary,
        full_content=full_content,
        content_metadata=content_metadata,
        content_type=content_type,
        content=content,
    ),
    "subjective": round(max(0.0, min(10.0, float(subj.score))), 1),
}
```

- [ ] **Step 4: 添加测试**

在 `tests/test_score_v2_rules.py` 末尾追加：

```python
def test_reach_major_entity_for_s_tier_without_sector_keyword():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    # Title mentioning OpenAI with no sector-wide reach keyword
    reach = score_reach("OpenAI announces quarterly update", None, None, runtime_vocab=vocab)
    assert reach == 6.5  # major_entity

def test_reach_sector_keyword_takes_precedence_over_major_entity():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    reach = score_reach("OpenAI reshapes the entire AI industry landscape", None, None, runtime_vocab=vocab)
    assert reach == 7.0  # sector keyword "landscape" or "across the industry"

def test_reach_entity_for_non_s_tier():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    reach = score_reach("Acme startup announces product update", None, None, runtime_vocab=vocab)
    assert reach == 5.5  # plain entity
```

- [ ] **Step 5: 运行测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

- [ ] **Step 6: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/score_rules.py backend/app/domains/score/score_vocab.py backend/tests/test_score_v2_rules.py
git commit -m "feat(score): add major_entity reach sub-bucket (6.5) for S-tier entities"
```

---

## Task 4: 英文词条词边界保护

**背景**：`entity_tier_score` 用 `term.lower() in corpus_l` 做子字符串匹配。英文词条如 `"meta "` 需要尾随空格，`"meta-analysis"` 仍可能误匹配。用户自定义关键词（tier B）风险更高。对 ASCII 词条改用 `\b` 正则词边界；中文保持子字符串匹配（中文无空格词边界）。

**Files:**
- Modify: `backend/app/domains/score/score_vocab_runtime.py`

- [ ] **Step 1: 添加 _is_ascii_term 辅助函数和 _term_in_corpus**

在 `score_vocab_runtime.py` 的 `_dedupe_terms` 函数前，添加：

```python
import re as _re

def _is_ascii_term(term: str) -> bool:
    """True when term contains only ASCII characters (English, numbers, punctuation)."""
    return all(ord(c) < 128 for c in term)


def _term_in_corpus(term: str, corpus_l: str) -> bool:
    """Match term in corpus with word-boundary protection for ASCII terms."""
    t = term.lower()
    if not t:
        return False
    if _is_ascii_term(term):
        return bool(_re.search(r"\b" + _re.escape(t) + r"\b", corpus_l))
    return t in corpus_l
```

- [ ] **Step 2: 在 entity_tier_score 中使用 _term_in_corpus**

将 `entity_tier_score` 方法（`score_vocab_runtime.py:54-65`）改为：

```python
def entity_tier_score(self, corpus: str) -> float:
    corpus_l = (corpus or "").lower()
    for term in self.entity_tier_s:
        if _term_in_corpus(term, corpus_l):
            return ENTITY_TIER_SCORES["S"]
    for term in self.entity_tier_a:
        if _term_in_corpus(term, corpus_l):
            return ENTITY_TIER_SCORES["A"]
    for term in self.entity_tier_b:
        if _term_in_corpus(term, corpus_l):
            return ENTITY_TIER_SCORES["B"]
    return ENTITY_TIER_SCORES["C"]
```

- [ ] **Step 3: 在 salience_with_user_match_floor 中也使用 _term_in_corpus**

将 `salience_with_user_match_floor` 方法（`score_vocab_runtime.py:67-74`）改为：

```python
def salience_with_user_match_floor(self, base_salience: float, corpus: str) -> float:
    """Raise salience when the user explicitly monitors a term that appears."""
    if not self.matched_user_terms:
        return base_salience
    corpus_l = (corpus or "").lower()
    if any(_term_in_corpus(term, corpus_l) for term in self.matched_user_terms):
        return max(base_salience, USER_KEYWORD_MATCHED_SALIENCE)
    return base_salience
```

- [ ] **Step 4: 添加测试**

在 `tests/test_score_v2_rules.py` 末尾追加：

```python
def test_entity_tier_ascii_word_boundary():
    """ASCII terms must not match as substrings inside longer words."""
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    # "meta-analysis" should NOT match tier-S "meta" (which is a company, not a prefix)
    # The term in vocab is "meta " or a variant; test that bare "meta-analysis" doesn't trigger S
    score_no_meta = vocab.entity_tier_score("researchers published a meta-analysis on AI safety")
    score_with_meta = vocab.entity_tier_score("Meta announces new AI research initiative")
    assert score_with_meta == 9.0   # "meta" as company word → S-tier
    assert score_no_meta < 9.0      # "meta-analysis" should not trigger S-tier
```

- [ ] **Step 5: 运行测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

- [ ] **Step 6: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/score_vocab_runtime.py backend/tests/test_score_v2_rules.py
git commit -m "fix(score): add word-boundary protection for ASCII entity terms in tier matching"
```

---

## Task 5: 用户词 salience 检测范围从 800 字扩大到 2000 字

**背景**：`_corpus(limit=800)` 在 `score_salience` 中用于 `salience_with_user_match_floor` 的正文检测。长文章中用户关键词若出现在第 800 字之后会被漏掉。扩大到 2000 字即可覆盖绝大多数摘要+正文前段。

**Files:**
- Modify: `backend/app/domains/score/score_rules.py`

- [ ] **Step 1: 修改 score_salience 中的 _corpus 调用**

在 `score_rules.py:112-129` 的 `score_salience` 函数内，将：

```python
raw = runtime_vocab.salience_with_user_match_floor(raw, _corpus(title, summary, full_content))
```

改为：

```python
raw = runtime_vocab.salience_with_user_match_floor(raw, _corpus(title, summary, full_content, limit=2000))
```

- [ ] **Step 2: 运行测试确认无回归**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

- [ ] **Step 3: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/score_rules.py
git commit -m "fix(score): expand user-keyword salience scan limit from 800 to 2000 chars"
```

---

## Task 6: 改善中文 tokenization（bigram + trigram）

**背景**：`RankingService._tokenize` 对中文仅做 bigram（相邻两字），三字词（如"人民银行"、"工信部"）会被拆成 2 个 bigram，与完整词义不匹配，导致 Jaccard 相似度计算不准。加入 trigram 后，三字词在两篇文章中各有一个 trigram 命中，相似度更可靠。

**Files:**
- Modify: `backend/app/services/ranking_service.py`

- [ ] **Step 1: 修改 _tokenize 函数**

将 `ranking_service.py:20-27` 的 `_tokenize` 函数改为：

```python
def _tokenize(text: str) -> Set[str]:
    """Tokenize mixed Chinese/English text into a compact token set.

    Chinese: both bigrams and trigrams to better capture 3-char terms.
    English: 2+ character words (lowercased).
    """
    normalized = _normalize_text(text)
    if not normalized:
        return set()

    words = re.findall(r"[a-z0-9]{2,}", normalized)
    zh_chars = re.findall(r"[一-鿿]", normalized)
    zh_bigrams = ["".join(zh_chars[i : i + 2]) for i in range(len(zh_chars) - 1)]
    zh_trigrams = ["".join(zh_chars[i : i + 3]) for i in range(len(zh_chars) - 2)]

    return set(words + zh_bigrams + zh_trigrams)
```

- [ ] **Step 2: 验证现有测试通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_hourly_digest_ranking.py -q
```

- [ ] **Step 3: 补充测试**

在 `tests/test_hourly_digest_ranking.py` 末尾（或单独文件）追加：

```python
def test_tokenize_includes_chinese_trigrams():
    from app.services.ranking_service import _tokenize
    tokens = _tokenize("中国人民银行宣布降息")
    # bigrams
    assert "人民" in tokens
    assert "银行" in tokens
    # trigrams
    assert "人民银" in tokens
    assert "民银行" in tokens


def test_tokenize_three_char_term_similarity():
    """Two headlines sharing a 3-char Chinese term should have higher Jaccard than bigrams-only."""
    from app.services.ranking_service import _tokenize, _jaccard
    a = _tokenize("中国人民银行宣布利率决定")
    b = _tokenize("人民银行维持基准利率不变")
    score = _jaccard(a, b)
    assert score > 0.15  # trigrams give overlap on "人民银" and "民银行"
```

- [ ] **Step 4: 运行测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_hourly_digest_ranking.py -q
```

- [ ] **Step 5: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/services/ranking_service.py backend/tests/test_hourly_digest_ranking.py
git commit -m "fix(ranking): add Chinese trigrams to tokenizer for better 3-char term Jaccard similarity"
```

---

## Task 7: feedback_summary.py 脚本

**背景**：`ScoreFeedback` 表记录了用户标注的 too_high/too_low/ok，但没有消费工具。此脚本查询所有 feedback，按 lane × direction 汇总，生成可读的调参建议报告。

**Files:**
- Create: `backend/scripts/feedback_summary.py`

- [ ] **Step 1: 创建脚本**

```python
#!/usr/bin/env python3
"""Summarize ScoreFeedback to guide score calibration.

Usage:
    cd backend
    .venv/bin/python scripts/feedback_summary.py
    .venv/bin/python scripts/feedback_summary.py --min-count 3
"""
from __future__ import annotations

import argparse
import sys
import os
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///pim.db")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.score_feedback import ScoreFeedback
from app.models.content import Content
from app.database import Base


def _get_engine():
    settings = get_settings()
    db_url = str(settings.database_url or "sqlite:///pim.db")
    return create_engine(db_url.replace("+aiosqlite", ""))


def summarize(*, min_count: int = 1) -> None:
    engine = _get_engine()
    with Session(engine) as session:
        rows = session.execute(
            select(ScoreFeedback, Content.title)
            .join(Content, Content.id == ScoreFeedback.content_id)
            .order_by(ScoreFeedback.created_at.desc())
        ).all()

    if not rows:
        print("No feedback recorded yet.")
        return

    total = len(rows)
    direction_counter: Counter = Counter()
    lane_direction: dict[str, Counter] = defaultdict(Counter)
    expected_status_counter: Counter = Counter()
    score_deltas: list[float] = []
    notes: list[str] = []

    for feedback, title in rows:
        direction_counter[feedback.direction] += 1
        snap = feedback.snapshot or {}
        lane = snap.get("lane") or "unknown"
        lane_direction[lane][feedback.direction] += 1
        if feedback.expected_status:
            expected_status_counter[feedback.expected_status] += 1
        delta = snap.get("score_delta")
        if delta is not None:
            try:
                score_deltas.append(float(delta))
            except (TypeError, ValueError):
                pass
        if feedback.note:
            notes.append(f"  [{feedback.direction}] {title[:60]}: {feedback.note}")

    print(f"\n{'='*60}")
    print(f"Score Feedback Summary  (total: {total})")
    print(f"{'='*60}")

    print("\n--- Overall Direction ---")
    for direction in ("too_high", "too_low", "ok"):
        count = direction_counter.get(direction, 0)
        pct = count / total * 100
        print(f"  {direction:12s}: {count:4d}  ({pct:.1f}%)")

    print("\n--- By Lane × Direction ---")
    for lane, counts in sorted(lane_direction.items()):
        lane_total = sum(counts.values())
        if lane_total < min_count:
            continue
        line = f"  {lane:20s}: "
        parts = [f"{d}={counts[d]}" for d in ("too_high", "too_low", "ok") if counts[d]]
        print(line + "  ".join(parts))

    if expected_status_counter:
        print("\n--- Expected Status (when feedback disagrees) ---")
        for status, count in expected_status_counter.most_common():
            print(f"  {status}: {count}")

    if score_deltas:
        avg_delta = sum(score_deltas) / len(score_deltas)
        print(f"\n--- Score Delta (recomputed − stored) ---")
        print(f"  mean delta: {avg_delta:+.2f}  (positive = vocab change inflated score)")

    if notes:
        print(f"\n--- Notes ({len(notes)}) ---")
        for note in notes[:20]:
            print(note)
        if len(notes) > 20:
            print(f"  ... and {len(notes) - 20} more")

    print("\n--- Calibration Hints ---")
    high_pct = direction_counter.get("too_high", 0) / total
    low_pct = direction_counter.get("too_low", 0) / total
    if high_pct > 0.4:
        print("  ⚠  >40% too_high — consider raising selected_threshold or tightening vocab caps")
    if low_pct > 0.4:
        print("  ⚠  >40% too_low  — consider lowering thresholds or expanding entity tiers")
    if high_pct < 0.15 and low_pct < 0.15:
        print("  ✓  Distribution looks balanced")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize ScoreFeedback")
    parser.add_argument("--min-count", type=int, default=1, help="Min feedback count per lane to show")
    args = parser.parse_args()
    summarize(min_count=args.min_count)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 设置可执行权限**

```bash
chmod +x /Users/shuhuaiwang/personal-info-monitor/backend/scripts/feedback_summary.py
```

- [ ] **Step 3: 验证脚本可以运行（无数据时应打印 "No feedback recorded yet."）**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python scripts/feedback_summary.py 2>/dev/null || .venv/bin/python scripts/feedback_summary.py
```

预期输出（无数据）：`No feedback recorded yet.`

- [ ] **Step 4: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/scripts/feedback_summary.py
git commit -m "feat(scripts): add feedback_summary.py for score calibration guidance"
```

---

## Task 8: LLM 主观分基础设施 —— score_model 系统设置

**背景**：LlmSubjectiveScorer 需要访问 LLM，遵循现有 ai_model/atom_model 模式，在 system_settings 加入 score_model 配置项，provider.py 增加对应的 num_ctx 处理。

**Files:**
- Modify: `backend/app/platform/config/system_settings.py`
- Modify: `backend/app/ai/provider.py`

- [ ] **Step 1: 在 DEFAULT_SYSTEM_SETTINGS 中增加 score_model**

在 `system_settings.py` 的 `DEFAULT_SYSTEM_SETTINGS` dict 内，`atom_model` 定义之后追加：

```python
    "score_model": {
        "provider": "ollama",
        "model": "",
        "api_base": "http://localhost:11434",
        "temperature": 0.1,
        "max_tokens": 150,   # short score + rationale, no need for long output
        "ollama_num_ctx": 2048,
        "ollama_no_think": True,
    },
```

- [ ] **Step 2: 在 provider.py 的 get_runtime_from_system_settings 增加 score_model 分支**

在 `provider.py:476-487`，`get_runtime_from_system_settings` 函数内的 `elif setting_key == "atom_model":` 分支后添加：

```python
    elif setting_key == "score_model":
        ollama_num_ctx_default = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
        ollama_no_think_default = True
```

- [ ] **Step 3: 运行现有测试确认无回归**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_score_v2_rules.py -x 2>/dev/null | tail -5
```

- [ ] **Step 4: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/platform/config/system_settings.py backend/app/ai/provider.py
git commit -m "feat(config): add score_model to system settings for LLM subjective scoring"
```

---

## Task 9: 实现 LlmSubjectiveScorer

**背景**：`score_subjective.py` 已定义 `SubjectiveScorer` 协议和 `PIM_SCORE_LLM_SUBJECTIVE` feature flag，但实现体为空。实现一个轻量 scorer：输入标题+摘要，输出 1-10 相关性分和一句 rationale；仅传标题+摘要（不传全文），成本可控。

**Files:**
- Modify: `backend/app/domains/score/score_subjective.py`

- [ ] **Step 1: 实现 LlmSubjectiveScorer**

将 `score_subjective.py` 全部替换为：

```python
"""Subjective score slot for pim-score-v2 (LLM hook + fixed baseline)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.features import feature_enabled

FIXED_BASELINE_SUBJECTIVE_SCORE = 5.0

_SCORE_RE = re.compile(r"\b([1-9]|10)\b")


@dataclass(frozen=True)
class SubjectiveScoreResult:
    score: float
    source: str
    rationale: str | None = None
    model: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "score": round(max(0.0, min(10.0, float(self.score))), 1),
            "source": self.source,
            "rationale": self.rationale,
            "model": self.model,
        }


class SubjectiveScorer(Protocol):
    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult: ...


class FixedBaselineSubjectiveScorer:
    """Neutral placeholder until LLM subjective scoring is enabled."""

    def __init__(self, score: float = FIXED_BASELINE_SUBJECTIVE_SCORE) -> None:
        self._score = score

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        return SubjectiveScoreResult(
            score=self._score,
            source="fixed_baseline",
            rationale=None,
            model=None,
        )


class LlmSubjectiveScorer:
    """Score relevance via LLM. Calls are async; requires PIM_SCORE_LLM_SUBJECTIVE=true."""

    _SYSTEM = (
        "你是新闻重要性评估助手。根据标题和摘要，给出对个人信息监控用途的主观重要性分数（1-10整数）和一句不超过30字的理由。"
        "输出格式（只输出这两行）：\n"
        "score: <1-10整数>\n"
        "rationale: <理由>"
    )

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        title = (getattr(content, "title", None) or getattr(content, "translated_title", None) or "").strip()
        summary = (getattr(content, "summary", None) or getattr(content, "translated_summary", None) or "").strip()
        if not title and not summary:
            return SubjectiveScoreResult(score=FIXED_BASELINE_SUBJECTIVE_SCORE, source="fixed_baseline")

        prompt = f"标题：{title[:200]}\n摘要：{summary[:400]}"
        raw = await self._call_llm(prompt)
        return self._parse(raw)

    async def _call_llm(self, prompt: str) -> str:
        try:
            from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
            runtime = await get_runtime_from_system_settings(
                setting_key="score_model",
                default_provider="ollama",
                default_model="",
                default_max_tokens=150,
            )
            if runtime is None:
                return ""
            client = ModelProviderClient()
            return await client.generate_text(
                runtime,
                prompt=prompt,
                system_prompt=self._SYSTEM,
                temperature=0.1,
                max_tokens=150,
                timeout_seconds=30.0,
            )
        except Exception:
            return ""

    def _parse(self, raw: str) -> SubjectiveScoreResult:
        score = FIXED_BASELINE_SUBJECTIVE_SCORE
        rationale: str | None = None
        model: str | None = None
        for line in (raw or "").splitlines():
            line = line.strip()
            if line.lower().startswith("score:"):
                m = _SCORE_RE.search(line)
                if m:
                    score = float(m.group(1))
            elif line.lower().startswith("rationale:"):
                rationale = line.split(":", 1)[-1].strip() or None
        return SubjectiveScoreResult(
            score=score,
            source="llm",
            rationale=rationale,
            model=model,
        )


def get_subjective_scorer() -> SubjectiveScorer:
    if feature_enabled("PIM_SCORE_LLM_SUBJECTIVE"):
        return LlmSubjectiveScorer()
    return FixedBaselineSubjectiveScorer()


def resolve_subjective_score(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Sync path for ingest finish — always returns fixed baseline (LLM is async-only)."""
    del content, lane
    return SubjectiveScoreResult(
        score=FIXED_BASELINE_SUBJECTIVE_SCORE,
        source="fixed_baseline",
        rationale=None,
        model=None,
    )


async def score_subjective_async(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Async path — calls LLM when PIM_SCORE_LLM_SUBJECTIVE=true, else fixed baseline."""
    scorer = get_subjective_scorer()
    return await scorer.score(content, lane=lane)


async def score_subjective_sync_path(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Legacy alias — use score_subjective_async for new callers."""
    return resolve_subjective_score(content, lane=lane)
```

- [ ] **Step 2: 更新 merge_rule_scoring_metadata_async 使用异步路径**

在 `scoring.py:314-319`，将 `merge_rule_scoring_metadata_async` 改为实际异步处理（对 candidate 区间文章调用 LLM）：

```python
async def merge_rule_scoring_metadata_async(
    metadata: Mapping[str, Any] | None,
    *,
    content: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Async scoring entry — calls LLM subjective scorer when feature flag is on."""
    from app.domains.score.score_subjective import score_subjective_async

    result = merge_rule_scoring_metadata(metadata, content=content, **kwargs)

    if feature_enabled("PIM_SCORE_LLM_SUBJECTIVE") and isinstance(result, dict):
        lane = result.get("lane", "other")
        subj = await score_subjective_async(content, lane=lane)
        if subj.source == "llm":
            # Re-run article_score with LLM subjective value
            dims = dict(result.get("dimension_scores") or {})
            dims["subjective"] = round(max(0.0, min(10.0, float(subj.score))), 1)
            from app.domains.score.scoring import calculate_article_score
            updated = calculate_article_score(
                dims,
                content_metadata=result,
                source_metadata=kwargs.get("source_metadata"),
                lane=lane,
                subjective_meta=subj.to_metadata(),
            )
            result.update(updated)
            result["scoring_method"] = "rule+llm"
    return result
```

- [ ] **Step 3: 在 features.py 中确认 PIM_SCORE_LLM_SUBJECTIVE 已注册**

检查 `app/features.py` 的 `_FEATURE_FLAG_DEFAULTS` 中包含 `"PIM_SCORE_LLM_SUBJECTIVE": False`（已存在，无需改动）。

- [ ] **Step 4: 运行测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

- [ ] **Step 5: 提交**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add backend/app/domains/score/score_subjective.py backend/app/domains/score/scoring.py
git commit -m "feat(score): implement LlmSubjectiveScorer with score_model runtime; wire async re-scoring path"
```

---

## Task 10: 运行完整测试套件确认全量通过

- [ ] **Step 1: 运行完整评分相关测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py tests/test_content_quality_scoring.py \
  tests/test_hourly_digest_ranking.py tests/test_score_explain.py -v 2>&1 | tail -30
```

预期：全部 PASSED，无 FAILED 或 ERROR。

- [ ] **Step 2: 更新 SCORING_MODEL.md**

在 `docs/SCORING_MODEL.md` 的 §1.2 表格中：
- 将 `subjective 主观` 权重从 `20%` 改为 `0%（LLM 预留，暂停用）`
- 更新入选阈值表：`selected ≥ 70 / candidate ≥ 55`
- 在 §8 已知限制里删除 `subjective 固定 5.0`，改为 `subjective 权重已归零，等待 LLM scorer 接入`

- [ ] **Step 3: 提交文档更新**

```bash
cd /Users/shuhuaiwang/personal-info-monitor
git add docs/SCORING_MODEL.md
git commit -m "docs(score): update SCORING_MODEL.md for v2.2 — new thresholds, reach sub-bucket, LLM scorer"
```
