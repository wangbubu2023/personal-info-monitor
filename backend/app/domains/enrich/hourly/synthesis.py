"""LLM-backed synthesis step + rule-based fallbacks.

Three rendering paths are defined here, in decreasing order of
fidelity:

1. :func:`llm_synthesize_hourly_digest` – single shot that writes the
   full digest body (preferred).
2. :func:`generate_digest_items_with_ai` – per-cluster micro-generation
   used when the one-shot output fails format validation.
3. :func:`build_fallback_digest` – pure rule-based rendering used when
   no AI runtime is available or both AI paths fail.
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Optional

from app.ai.provider import ModelProviderClient
from app.platform.llm.translator import Translator
from app.domains.enrich.hourly.text_utils import (
    ORDERED_DIGEST_CATEGORIES,
    classify_digest_category,
    clean_digest_text,
    normalize_digest_category,
    preferred_item_summary,
    preferred_item_title,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

BRIEFING_SECTIONS: tuple[tuple[str, str], ...] = (
    ("need_to_know", "需要你现在知道"),
    ("brewing", "正在发酵"),
    ("later", "可稍后看"),
)


def build_synthesis_materials(selected: List[dict]) -> str:
    parts: List[str] = []
    for idx, e in enumerate(selected, start=1):
        cid = (e.get("content_id") or "").strip()
        title = preferred_item_title(e)
        sn = (e.get("source_name") or "Unknown").strip()
        summ = clean_digest_text((e.get("translated_summary") or e.get("summary") or "").strip())
        if len(summ) > 500:
            summ = f"{summ[:497]}..."
        link = f"[{title}](/reader/{cid})" if cid else title
        parts.append(
            f"### 素材 {idx}\n"
            f"- 本地引用（正文必须原样使用此 Markdown 链接）：{link}\n"
            f"- 来源：{sn}\n"
            f"- 标题：{title}\n"
            f"- 摘要/正文片段：{summ or '（无摘要）'}\n"
        )
    return "\n".join(parts).strip()


def _event_local_link(item: dict) -> str:
    title = clean_digest_text(str(item.get("title") or "未命名事件").strip())
    local_path = str(item.get("local_reader_path") or "").strip()
    if local_path:
        return f"[{title}]({local_path})"
    return title


def _event_sources_text(item: dict) -> str:
    source_names = item.get("source_names")
    if isinstance(source_names, list) and source_names:
        return "、".join(str(x).strip() for x in source_names if str(x).strip())
    return str(item.get("source_name") or "Unknown").strip()


def build_event_briefing_materials(event_items: List[dict]) -> str:
    parts: List[str] = []
    for idx, item in enumerate(event_items, start=1):
        parts.append(
            f"### 事件 {idx}\n"
            f"- 分区：{item.get('section')}\n"
            f"- 标题链接：{_event_local_link(item)}\n"
            f"- 来源：{_event_sources_text(item)}\n"
            f"- 重要性：{item.get('importance_score')} / 100\n"
            f"- 增量性：{item.get('incremental_score')} / 100\n"
            f"- 置信度：{item.get('confidence_score')} / 100\n"
            f"- 发生了什么：{clean_digest_text(str(item.get('what_happened') or item.get('summary') or ''))}\n"
            f"- 为什么重要：{clean_digest_text(str(item.get('why_matters') or ''))}\n"
            f"- 新信号：{clean_digest_text(str(item.get('new_signal') or item.get('summary') or ''))}\n"
            f"- 还缺什么确认：{clean_digest_text(str(item.get('missing_confirmation') or ''))}\n"
        )
    return "\n".join(parts).strip()


async def llm_synthesize_hourly_digest(
    model_client: ModelProviderClient,
    runtime,
    *,
    title: str,
    materials: str,
    task_prompt: str,
) -> str:
    # This is a publishing path, not an analysis path.  Keep reasoning disabled
    # and bound the response to the size of a short briefing.
    cap = max(900, min(2400, int(getattr(runtime, "max_tokens", 1000) or 1000)))
    prompt = (
        f"你正在生成「每小时快报」，当前是根据结构化事件卡写最终正文。必须遵守下列任务说明。\n\n"
        f"{task_prompt}\n\n"
        f"---\n"
        f"结构与格式硬约束：\n"
        f"- 第一行必须是：`## {title}` ，然后空一行再写正文。\n"
        f"- 第二段必须以 `一句话：` 开头，概括过去一小时真正值得注意的变化。\n"
        f"- 之后只使用这三个三级标题：`### 需要你现在知道`、`### 正在发酵`、`### 可稍后看`。\n"
        f"- `需要你现在知道` 中每个事件写 3 个短句：发生了什么；为什么重要；来源和本地阅读链接。\n"
        f"- `正在发酵` 中每个事件写 2 个短句：新信号是什么；还缺什么确认。\n"
        f"- `可稍后看` 只保留 3-5 条，每条一行。\n"
        f"- 禁止输出代码围栏。\n"
        f"- 不要输出 <think> 等思考标签；直接写最终简报即可。\n\n"
        f"结构化事件卡：\n{materials}"
    )
    return await model_client.generate_text(
        runtime,
        prompt=prompt,
        system_prompt="你是克制的中文私人秘书，只根据给定事件卡写短快报。",
        temperature=0.2,
        max_tokens=cap,
        timeout_seconds=150.0,
        no_think=True,
    )


def _split_event_items(event_items: List[dict]) -> dict[str, list[dict]]:
    sections = {key: [] for key, _ in BRIEFING_SECTIONS}
    for item in event_items:
        section = str(item.get("section") or "later")
        if section not in sections:
            section = "later"
        sections[section].append(item)
    return sections


def _render_need_to_know(item: dict) -> list[str]:
    link = _event_local_link(item)
    sources = _event_sources_text(item)
    what = clean_digest_text(str(item.get("what_happened") or item.get("summary") or "本小时出现新的相关进展。"))
    why = clean_digest_text(str(item.get("why_matters") or "该事件综合评分较高，值得现在知道。"))
    return [
        f"**{link}**",
        f"发生了什么：{what}",
        f"为什么重要：{why}",
        f"来源：{sources}；本地阅读：{link}",
        "",
    ]


def _render_brewing(item: dict) -> list[str]:
    link = _event_local_link(item)
    signal = clean_digest_text(str(item.get("new_signal") or item.get("summary") or "出现新的报道或材料。"))
    missing = clean_digest_text(str(item.get("missing_confirmation") or "还需要更多独立来源确认。"))
    return [
        f"**{link}**",
        f"新信号：{signal}",
        f"还缺什么确认：{missing}",
        "",
    ]


def build_hourly_briefing_digest(
    title: str,
    event_items: List[dict],
    *,
    reason: str | None = None,
) -> str:
    sections = _split_event_items(event_items)
    top = (sections["need_to_know"] or sections["brewing"])[:1]
    if top:
        one_liner = f"一句话：过去一小时真正值得注意的是，{clean_digest_text(str(top[0].get('title') or '一个新信号'))}。"
    else:
        one_liner = "一句话：过去一小时没有足够重要、增量明确且可信的新增事件。"

    lines: list[str] = [f"## {title}", "", one_liner, ""]
    if reason:
        lines.append(f"> 降级渲染：{reason.strip()}")
        lines.append("")

    lines.append("### 需要你现在知道")
    lines.append("")
    if sections["need_to_know"]:
        for item in sections["need_to_know"][:4]:
            lines.extend(_render_need_to_know(item))
    else:
        lines.append("本小时没有达到“需要现在知道”阈值的事件。")
        lines.append("")

    lines.append("### 正在发酵")
    lines.append("")
    if sections["brewing"]:
        for item in sections["brewing"][:4]:
            lines.extend(_render_brewing(item))
    else:
        lines.append("暂无需要持续跟踪但尚未确认的明显信号。")
        lines.append("")

    lines.append("### 可稍后看")
    lines.append("")
    later = sections["later"][:5]
    if later:
        for item in later:
            score = item.get("importance_score", item.get("score"))
            score_text = f"，重要性 {score:g}" if isinstance(score, (int, float)) else ""
            lines.append(f"- {_event_local_link(item)}（{_event_sources_text(item)}{score_text}）")
    else:
        lines.append("暂无高分但不紧急的补充素材。")

    return "\n".join(lines).strip()


def build_cluster_prompt_v1(title: str, clusters: List[dict], *, candidate_limit: int) -> str:
    """Legacy prompt template kept for backwards compatibility of unit tests."""
    lines = []
    selected = clusters[:candidate_limit]
    for i, cluster in enumerate(selected, start=1):
        topic = (cluster.get("topic") or "").strip()
        score = round(float(cluster.get("score") or 0.0), 3)
        items = cluster.get("items") or []
        refs = []
        for item in items[:4]:
            refs.append(
                f"[{item.get('source_name','Unknown')}]({item.get('source_url','')})"
                f" / [原文]({item.get('article_url','')})"
            )
        summaries = []
        original_titles = []
        for item in items[:3]:
            summary = (item.get("summary") or "").strip()
            if summary:
                summaries.append(summary[:180])
            ot = (item.get("original_title") or "").strip()
            if ot:
                original_titles.append(ot[:120])
        lines.append(
            f"{i}. 事件主题={topic}；事件得分={score}；同簇文章数={len(items)}；参考来源={'; '.join(refs)}；"
            f"原标题候选={' | '.join(original_titles)}；候选摘要片段={' | '.join(summaries)}"
        )

    joined = "\n".join(lines)

    return (
        f"请根据以下过去60分钟的网站/博客内容，撰写中文私人简报。\n"
        f"标题固定为：{title}\n\n"
        "输出格式必须严格遵守下面模板，不要输出任何解释或额外前言：\n"
        f"## {title}\n\n"
        "### 分类名称\n"
        "**条目标题**\n"
        "条目摘要，1-2 句话，先说结论再补充关键信息。（来源：[来源名](原文链接) [点击查看原文](原文链接)）\n\n"
        "### 分类名称\n"
        "**条目标题**\n"
        "条目摘要……（来源：[来源名](原文链接) [点击查看原文](原文链接)）\n\n"
        "硬性要求：\n"
        "1) 一级标题固定为上述 title，分类标题必须使用三级标题，即 `### 财经`、`### 科技`、`### AI`、`### 汽车`、`### 政策`、`### 国际`、`### 重点` 等。\n"
        "2) 每个条目必须严格占两行：第一行只有标题并用 `**标题**` 包裹；第二行只有摘要，并以 `（来源：... [点击查看原文](...)）` 结尾。\n"
        "3) 不要出现编号、项目符号、目录、原标题字段、事件主题字段、分数、过程解释。\n"
        "4) 摘要必须是中文，长度控制在 50-120 字，避免空话和重复原文句式。\n"
        "5) 同类事件尽量归并，但最终呈现给用户时仍然要是一条一条可读的简报项。\n"
        "6) 若某类没有内容，就不要输出该分类。\n"
        "7) 不要编造信息，只能基于提供材料。\n\n"
        f"输入已按「事件簇」预聚合并排序，越靠前优先级越高。优先处理前 {min(6, len(selected))} 个事件簇。\n\n"
        f"事件簇列表：\n{joined}\n"
    )


def build_cluster_item_prompt(cluster: dict) -> str:
    topic = clean_digest_text((cluster.get("topic") or "未命名事件").strip())
    materials = []
    for idx, item in enumerate((cluster.get("items") or [])[:3], start=1):
        source_name = (item.get("source_name") or "Unknown").strip()
        source_url = (item.get("article_url") or item.get("source_url") or "").strip()
        title = clean_digest_text(
            (item.get("translated_title") or "").strip()
            or (item.get("original_title") or "").strip()
            or (item.get("title") or "").strip()
        )
        body = clean_digest_text(
            (item.get("translated_summary") or "").strip()
            or (item.get("summary") or "").strip()
        )
        materials.append(
            f"材料{idx}\n"
            f"来源：{source_name}\n"
            f"链接：{source_url}\n"
            f"标题：{title}\n"
            f"正文片段：{body[:900]}\n"
        )

    joined = "\n".join(materials).strip()
    return (
        "请把下面这些关于同一事件的材料，整合写成一条中文私人简报。\n"
        "这不是翻译任务，也不是摘抄任务，而是编辑整合写作。\n\n"
        "严格按下面三行输出，不要添加任何解释：\n"
        "分类：科技\n"
        "标题：一句简洁标题\n"
        "摘要：用 2 句中文写成，先说结论，再补充关键信息；要像编辑写的简报，而不是原文摘抄或零碎翻译。\n\n"
        "要求：\n"
        "1) 分类只能从 `重点`、`财经`、`金融`、`科技`、`AI`、`汽车`、`政策`、`国际` 中选一个。\n"
        "2) 标题必须是中文，不能照抄英文原标题。\n"
        "3) 摘要要整合材料里的共同信息，避免原文口吻、记者署名、无关修饰和长引号。\n"
        "4) 不要出现“据材料”“报道称”“原标题”等过程表述。\n"
        "5) 只能依据给定材料，不要编造。\n\n"
        f"事件主题：{topic}\n\n"
        f"{joined}\n"
    )


def _cluster_source_text(cluster: dict) -> tuple[str, str]:
    """Return (zh_source, full_source) drawn from a cluster's materials.

    ``zh_source`` keeps only Chinese-bearing fields, so char-n-gram grounding
    is never run across scripts (a Chinese digest item vs an English-only
    source would otherwise score ~0 and be wrongly rejected). ``full_source``
    keeps everything for date grounding, which is script-aware on its own.
    """
    zh_parts: List[str] = []
    full_parts: List[str] = []
    for item in (cluster.get("items") or [])[:4]:
        for key in ("translated_title", "original_title", "title", "translated_summary", "summary"):
            val = (item.get(key) or "").strip()
            if not val:
                continue
            full_parts.append(val)
            if re.search(r"[\u4e00-\u9fff]", val):
                zh_parts.append(val)
    return " ".join(zh_parts), " ".join(full_parts)


def parse_generated_digest_item(text: str, cluster: dict) -> Optional[dict]:
    from app.domains.enrich.hourly.text_utils import strip_llm_reasoning
    from app.utils.llm_guardrail import (
        check_dates_grounded,
        check_grounding,
        detect_llm_refusal,
        first_issue,
    )

    raw = strip_llm_reasoning((text or "").strip())
    if not raw:
        return None

    category_match = re.search(r"^分类[:：]\s*(.+)$", raw, re.M)
    title_match = re.search(r"^标题[:：]\s*(.+)$", raw, re.M)
    summary_match = re.search(r"^摘要[:：]\s*(.+)$", raw, re.M | re.S)

    title = clean_digest_text(title_match.group(1) if title_match else "")
    summary = clean_digest_text(summary_match.group(1) if summary_match else "")
    if not title or not summary:
        return None

    primary = (cluster.get("items") or [{}])[0]

    # Guardrail: drop refusals, hallucinated stories, and invented dates before
    # they get bound to a real content_id and rendered as a digest item.
    output_text = f"{title} {summary}"
    zh_source, full_source = _cluster_source_text(cluster)
    guard = first_issue(
        detect_llm_refusal(output_text),
        check_grounding(output_text, zh_source, threshold=0.18),
        check_dates_grounded(output_text, full_source),
    )
    if guard:
        logger.warning(
            "Digest item rejected by guardrail (%s): cid=%s title=%r",
            guard, (primary.get("content_id") or "")[:12], title[:60],
        )
        return None

    category = normalize_digest_category(category_match.group(1) if category_match else "")
    if category == "重点":
        category = classify_digest_category(f"{cluster.get('topic','')} {title} {summary}")

    cid = (primary.get("content_id") or "").strip()
    local_reader_path = f"/reader/{cid}" if cid else ""

    return {
        "category": category,
        "title": title,
        "summary": summary,
        "source_name": (primary.get("source_name") or "Unknown").strip(),
        "article_url": (primary.get("article_url") or primary.get("source_url") or "").strip(),
        "local_reader_path": local_reader_path,
    }


def _render_source_line(source_name: str, local_path: str, article_url: str) -> str:
    if local_path:
        return f"（来源：[{source_name}]({local_path}) [本地阅读]({local_path})）"
    if article_url:
        return f"（来源：[{source_name}]({article_url}) [点击查看原文]({article_url})）"
    return f"（来源：{source_name}）"


def build_digest_from_items(title: str, items: List[dict]) -> str:
    sections: dict[str, list[dict]] = {}
    for item in items:
        category = normalize_digest_category(item.get("category") or "重点")
        sections.setdefault(category, []).append(item)

    lines = [f"## {title}", ""]
    for category in ORDERED_DIGEST_CATEGORIES:
        entries = sections.get(category)
        if not entries:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item in entries:
            source_name = item.get("source_name") or "Unknown"
            local_path = (item.get("local_reader_path") or "").strip()
            article_url = (item.get("article_url") or "").strip()
            source_line = _render_source_line(source_name, local_path, article_url)
            lines.append(f"**{item.get('title') or '未命名事件'}**")
            lines.append(f"{item.get('summary') or '该事件在过去一小时内出现新的进展。'}{source_line}")
            lines.append("")
    return "\n".join(lines).strip()


async def localize_fallback_clusters(clusters: List[dict], *, candidate_limit: int) -> None:
    """Translate English primary items in-place before rendering the fallback digest.

    Translation failures are swallowed: the fallback renderer tolerates
    missing translations by falling back to the original title/summary.
    """
    translator = Translator()

    async def _translate_primary_item(item: dict) -> None:
        original_title = (item.get("original_title") or item.get("title") or "").strip()
        original_summary = (item.get("summary") or "").strip()
        translated_title = (item.get("translated_title") or "").strip()
        translated_summary = (item.get("translated_summary") or "").strip()

        if original_title and not translated_title and not translator.is_chinese(original_title):
            candidate = None
            try:
                candidate = await asyncio.wait_for(
                    translator.translate(original_title, "zh-CN"), timeout=30.0
                )
            except (TimeoutError, asyncio.TimeoutError):
                logger.debug("Translator timed out for title fallback")
            except Exception as exc:  # noqa: BLE001 - translator may raise anything, log and continue
                logger.debug("Translator raised on title fallback: %s", exc)
            if candidate:
                item["translated_title"] = clean_digest_text(candidate)

        if original_summary and not translated_summary and not translator.is_chinese(original_summary):
            candidate = None
            try:
                candidate = await asyncio.wait_for(
                    translator.translate(original_summary, "zh-CN"), timeout=40.0
                )
            except (TimeoutError, asyncio.TimeoutError):
                logger.debug("Translator timed out for summary fallback")
            except Exception as exc:  # noqa: BLE001 - translator may raise anything, log and continue
                logger.debug("Translator raised on summary fallback: %s", exc)
            if candidate:
                item["translated_summary"] = clean_digest_text(candidate)

    tasks = []
    for cluster in clusters[:candidate_limit]:
        items = cluster.get("items") or []
        if not items:
            continue
        tasks.append(_translate_primary_item(items[0]))

    if tasks:
        await asyncio.gather(*tasks)


async def generate_digest_items_with_ai(
    model_client: ModelProviderClient,
    runtime,
    clusters: List[dict],
    *,
    candidate_limit: int,
) -> List[dict]:
    semaphore = asyncio.Semaphore(2)
    selected = clusters[:candidate_limit]

    async def _generate(cluster: dict) -> Optional[dict]:
        prompt = build_cluster_item_prompt(cluster)
        try:
            async with semaphore:
                response = await asyncio.wait_for(
                    model_client.generate_text(
                        runtime,
                        prompt=prompt,
                        system_prompt="你是一位经验丰富的中文新闻编辑，擅长把多篇材料整合写成简报。",
                        temperature=0.15,
                        max_tokens=600,
                        timeout_seconds=45.0,
                    ),
                    timeout=50.0,
                )
        except Exception as exc:  # noqa: BLE001 - model client may raise anything
            logger.warning("Digest item generation failed (%s): %s", runtime.provider, exc)
            return None
        return parse_generated_digest_item(response, cluster)

    generated = await asyncio.gather(*[_generate(cluster) for cluster in selected])
    return [item for item in generated if item]


def build_fallback_digest(
    title: str,
    clusters: List[dict],
    *,
    candidate_limit: int,
    reason: str | None = None,
) -> str:
    selected = clusters[:candidate_limit]
    lines: list[str] = [f"## {title}", ""]
    # Surface the degrade reason so users can tell when their custom prompt
    # was bypassed (e.g. AI provider returned 4xx/5xx). Markdown blockquote
    # keeps it visually distinct from the actual digest content.
    if reason:
        lines.append(f"> ⚠️ 降级渲染：{reason.strip()}")
        lines.append("")
    sections: dict[str, list[tuple[str, str, str, str]]] = {}

    for idx, cluster in enumerate(selected, start=1):
        topic = (cluster.get("topic") or f"事件 {idx}").strip()
        items = cluster.get("items") or []
        primary = items[0] if items else {}
        summary = preferred_item_summary(primary)
        source_name = (primary.get("source_name") or "Unknown").strip()
        article_url = (primary.get("article_url") or primary.get("source_url") or "").strip()
        item_title = preferred_item_title(primary) or topic
        category = normalize_digest_category(
            classify_digest_category(f"{topic} {item_title} {summary}")
        )
        cid = (primary.get("content_id") or "").strip()
        local_path = f"/reader/{cid}" if cid else ""
        source_line = _render_source_line(source_name, local_path, article_url)
        sections.setdefault(category, []).append((item_title, summary, source_name, source_line))

    for category in ORDERED_DIGEST_CATEGORIES:
        entries = sections.get(category)
        if not entries:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item_title, summary, _, source_line in entries:
            lines.append(f"**{item_title}**")
            lines.append(f"{summary}{source_line}")
            lines.append("")

    return "\n".join(lines).strip()
