"""Tasks for generating hourly digests."""

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
from app.processors.translator import Translator
from app.services.ranking_service import RankingService
from app.services.system_settings import get_system_settings_sync
from app.utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_TZ = ZoneInfo("Asia/Shanghai")


def _local_to_utc_naive(dt_local: datetime) -> datetime:
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def _format_digest_title(target_label_local: datetime) -> str:
    return f"{target_label_local.month} 月 {target_label_local.day} 日 {target_label_local.hour} 时简报"


def _coerce_limit_int(value, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _get_digest_limits() -> dict:
    settings = get_system_settings_sync() or {}
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return {
        "max_input_items": _coerce_limit_int(limits.get("max_hourly_digest_input_items"), 200, min_value=20, max_value=2000),
        "max_candidates": _coerce_limit_int(limits.get("max_digest_candidates"), 12, min_value=3, max_value=30),
    }


def _build_prompt(title: str, clusters: List[dict], *, candidate_limit: int) -> str:
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


def _build_cluster_item_prompt(cluster: dict) -> str:
    topic = _clean_digest_text((cluster.get("topic") or "未命名事件").strip())
    materials = []
    for idx, item in enumerate((cluster.get("items") or [])[:3], start=1):
        source_name = (item.get("source_name") or "Unknown").strip()
        source_url = (item.get("article_url") or item.get("source_url") or "").strip()
        title = _clean_digest_text(
            (item.get("translated_title") or "").strip()
            or (item.get("original_title") or "").strip()
            or (item.get("title") or "").strip()
        )
        body = _clean_digest_text(
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


def _parse_generated_digest_item(text: str, cluster: dict) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None

    category_match = re.search(r"^分类[:：]\s*(.+)$", raw, re.M)
    title_match = re.search(r"^标题[:：]\s*(.+)$", raw, re.M)
    summary_match = re.search(r"^摘要[:：]\s*(.+)$", raw, re.M | re.S)

    title = _clean_digest_text(title_match.group(1) if title_match else "")
    summary = _clean_digest_text(summary_match.group(1) if summary_match else "")
    if not title or not summary:
        return None

    primary = (cluster.get("items") or [{}])[0]
    category = _normalize_digest_category(category_match.group(1) if category_match else "")
    if category == "重点":
        category = _classify_digest_category(f"{cluster.get('topic','')} {title} {summary}")

    return {
        "category": category,
        "title": title,
        "summary": summary,
        "source_name": (primary.get("source_name") or "Unknown").strip(),
        "article_url": (primary.get("article_url") or primary.get("source_url") or "").strip(),
    }


def _build_digest_from_items(title: str, items: List[dict]) -> str:
    ordered_categories = ["重点", "财经", "金融", "科技", "AI", "汽车", "政策", "国际"]
    sections: dict[str, list[dict]] = {}
    for item in items:
        category = _normalize_digest_category(item.get("category") or "重点")
        sections.setdefault(category, []).append(item)

    lines = [f"## {title}", ""]
    for category in ordered_categories:
        entries = sections.get(category)
        if not entries:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item in entries:
            source_name = item.get("source_name") or "Unknown"
            article_url = item.get("article_url") or ""
            source_line = f"（来源：[{source_name}]({article_url}) [点击查看原文]({article_url})）" if article_url else f"（来源：{source_name}）"
            lines.append(f"**{item.get('title') or '未命名事件'}**")
            lines.append(f"{item.get('summary') or '该事件在过去一小时内出现新的进展。'}{source_line}")
            lines.append("")
    return "\n".join(lines).strip()


def _is_valid_digest_format(body: str) -> bool:
    text = (body or "").strip()
    return bool(text and "### " in text and "来源：" in text)


def _normalize_digest_category(label: str) -> str:
    normalized = (label or "").strip()
    return normalized or "重点"


def _classify_digest_category(text: str) -> str:
    normalized = (text or "").lower()
    ascii_tokens = set(re.findall(r"[a-z0-9.+-]+", normalized))

    def _matches(keyword: str) -> bool:
        token = (keyword or "").strip().lower()
        if not token:
            return False
        if re.fullmatch(r"[a-z0-9.+-]+", token):
            return token in ascii_tokens
        return token in normalized

    rules = [
        ("AI", [" ai", "openai", "anthropic", "gemini", "llm", "model", "人工智能", "大模型", "智能体"]),
        ("汽车", ["car", "auto", "ev", "tesla", "byd", "蔚来", "小鹏", "理想", "汽车"]),
        ("金融", ["bank", "bond", "fund", "insurance", "credit", "融资租赁", "证券", "基金", "保险", "信贷"]),
        ("财经", ["ipo", "earnings", "economy", "market", "acquisition", "merger", "export", "revenue", "profit", "股价", "财报", "经济", "出口"]),
        ("科技", ["tech", "startup", "chip", "semiconductor", "software", "app", "cloud", "developer", "科技", "芯片", "半导体"]),
        ("政策", ["ministry", "government", "policy", "regulator", "外交部", "国务院", "部委", "政策", "监管"]),
        ("国际", ["war", "iran", "ukraine", "pakistan", "india", "china", "eu", "外交", "国际", "冲突"]),
    ]
    for label, keywords in rules:
        if any(_matches(keyword) for keyword in keywords):
            return label
    return "重点"


def _preferred_item_title(item: dict) -> str:
    return _clean_digest_text(
        (item.get("translated_title") or "").strip()
        or (item.get("original_title") or "").strip()
        or (item.get("title") or "").strip()
        or "未命名事件"
    )


def _clean_digest_text(text: str) -> str:
    cleaned = html.unescape((text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}:\s*", "", cleaned)
    cleaned = re.sub(r"^[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}\s*/\s*[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}:\s*", "", cleaned)
    return cleaned.strip()


def _preferred_item_summary(item: dict) -> str:
    text = _clean_digest_text(
        (item.get("translated_summary") or "").strip()
        or (item.get("summary") or "").strip()
    )
    if len(text) > 120:
        return f"{text[:117]}..."
    return text or "该事件在过去一小时内出现新的进展。"


async def _localize_fallback_clusters(clusters: List[dict], *, candidate_limit: int) -> None:
    translator = Translator()

    async def _translate_primary_item(item: dict) -> None:
        original_title = (item.get("original_title") or item.get("title") or "").strip()
        original_summary = (item.get("summary") or "").strip()
        translated_title = (item.get("translated_title") or "").strip()
        translated_summary = (item.get("translated_summary") or "").strip()

        if original_title and not translated_title and not translator.is_chinese(original_title):
            try:
                candidate = await asyncio.wait_for(translator.translate(original_title, "zh-CN"), timeout=30.0)
            except Exception:
                candidate = None
            if candidate:
                item["translated_title"] = _clean_digest_text(candidate)

        if original_summary and not translated_summary and not translator.is_chinese(original_summary):
            try:
                candidate = await asyncio.wait_for(translator.translate(original_summary, "zh-CN"), timeout=40.0)
            except Exception:
                candidate = None
            if candidate:
                item["translated_summary"] = _clean_digest_text(candidate)

    tasks = []
    for cluster in clusters[:candidate_limit]:
        items = cluster.get("items") or []
        if not items:
            continue
        tasks.append(_translate_primary_item(items[0]))

    if tasks:
        await asyncio.gather(*tasks)


async def _generate_digest_items_with_ai(
    model_client: ModelProviderClient,
    runtime,
    clusters: List[dict],
    *,
    candidate_limit: int,
) -> List[dict]:
    semaphore = asyncio.Semaphore(2)
    selected = clusters[:candidate_limit]

    async def _generate(cluster: dict) -> Optional[dict]:
        prompt = _build_cluster_item_prompt(cluster)
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
        except Exception as exc:
            logger.warning("Digest item generation failed (%s): %s", runtime.provider, exc)
            return None
        return _parse_generated_digest_item(response, cluster)

    generated = await asyncio.gather(*[_generate(cluster) for cluster in selected])
    return [item for item in generated if item]


def _build_fallback_digest(title: str, clusters: List[dict], *, candidate_limit: int, reason: str | None = None) -> str:
    selected = clusters[:candidate_limit]
    lines = [f"## {title}", ""]
    sections: dict[str, list[tuple[str, str, str, str]]] = {}

    for idx, cluster in enumerate(selected, start=1):
        topic = (cluster.get("topic") or f"事件 {idx}").strip()
        items = cluster.get("items") or []
        primary = items[0] if items else {}
        summary = _preferred_item_summary(primary)
        source_name = (primary.get("source_name") or "Unknown").strip()
        article_url = (primary.get("article_url") or primary.get("source_url") or "").strip()
        item_title = _preferred_item_title(primary) or topic
        category = _normalize_digest_category(_classify_digest_category(f"{topic} {item_title} {summary}"))
        source_line = f"（来源：[{source_name}]({article_url}) [点击查看原文]({article_url})）" if article_url else f"（来源：{source_name}）"
        sections.setdefault(category, []).append((item_title, summary, source_name, source_line))

    ordered_categories = ["重点", "财经", "金融", "科技", "AI", "汽车", "政策", "国际"]
    for category in ordered_categories:
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


def _build_digest_text_seed(content) -> str:
    source = content.source
    has_paywall_auth = bool(source and (source.auth_required or source.auth_config_id))
    full_content = (content.full_content or "").strip()
    if has_paywall_auth and full_content:
        return full_content[:2000]
    if full_content:
        return full_content[:1500]
    return (content.translated_summary or content.summary or "").strip()


def _build_entries(rows: list) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    source_names: list[str] = []
    for c in rows:
        source_name = c.source.name if c.source else "Unknown"
        if source_name not in source_names:
            source_names.append(source_name)
        seed_text = _build_digest_text_seed(c)
        entries.append({
            "content_id": str(c.id),
            "source_name": source_name,
            "source_url": (c.source.url if c.source else "") or c.original_url or "",
            "article_url": c.original_url or "",
            "title": c.title or "",
            "original_title": c.title or "",
            "summary": seed_text,
            "translated_title": getattr(c, "translated_title", None) or "",
            "translated_summary": getattr(c, "translated_summary", None) or "",
            "source_priority": c.source.priority if c.source else 0,
            "publish_time": c.publish_time,
            "fetched_at": c.fetched_at,
        })
    return entries, source_names


def _compute_digest_window(now_local: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    end_local = now_local.replace(minute=0, second=0, microsecond=0)
    start_local = end_local - timedelta(hours=1)
    start_utc = _local_to_utc_naive(start_local)
    end_utc = _local_to_utc_naive(end_local)
    return start_local, end_local, start_utc, end_utc


def _load_digest_rows(db, start_utc: datetime, end_utc: datetime, *, max_input_items: int):
    from app.models import Content

    return (
        db.query(Content)
        .filter(Content.content_type == "website")
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .order_by(Content.fetched_at.desc())
        .limit(max_input_items)
        .all()
    )


def _get_or_create_hourly_digest(db, digest_date, digest_hour: int, title: str):
    from app.models import HourlyDigest

    digest = (
        db.query(HourlyDigest)
        .filter(HourlyDigest.digest_date == digest_date, HourlyDigest.hour == digest_hour)
        .first()
    )
    if not digest:
        digest = HourlyDigest(digest_date=digest_date, hour=digest_hour, title=title)
        db.add(digest)
    return digest


def _store_empty_digest(db, digest, title: str, message: str, *, content_count: int, sources: list[str]) -> None:
    _store_digest(
        db,
        digest,
        title,
        f"## {title}\n\n### 重点\n{message}",
        content_count=content_count,
        sources=sources,
    )


def _store_digest(db, digest, title: str, body: str, *, content_count: int, sources: list[str]) -> None:
    digest.title = title
    digest.summary = body
    digest.content_count = content_count
    digest.sources = sources
    try:
        db.commit()
        return
    except IntegrityError:
        db.rollback()

    from app.models import HourlyDigest

    existing = (
        db.query(HourlyDigest)
        .filter(HourlyDigest.digest_date == digest.digest_date, HourlyDigest.hour == digest.hour)
        .first()
    )
    if not existing:
        raise

    existing.title = title
    existing.summary = body
    existing.content_count = content_count
    existing.sources = sources
    db.commit()


def _build_digest_generation_context(db) -> Optional[dict]:
    now_local = datetime.now(SYSTEM_TZ)
    start_local, end_local, start_utc, end_utc = _compute_digest_window(now_local)
    digest_limits = _get_digest_limits()
    max_input_items = digest_limits["max_input_items"]
    max_candidates = digest_limits["max_candidates"]

    rows = _load_digest_rows(db, start_utc, end_utc, max_input_items=max_input_items)
    digest_date = end_local.date()
    digest_hour = end_local.hour
    title = _format_digest_title(end_local)
    digest = _get_or_create_hourly_digest(db, digest_date, digest_hour, title)

    if not rows:
        _store_empty_digest(
            db,
            digest,
            title,
            "过去 60 分钟内暂无网站/博客新增内容。",
            content_count=0,
            sources=[],
        )
        return None

    prev_rows = _load_digest_rows(
        db,
        start_utc - timedelta(hours=1),
        start_utc,
        max_input_items=max_input_items,
    )
    entries, source_names = _build_entries(rows)
    prev_entries, _ = _build_entries(prev_rows)
    ranking_service = RankingService()
    previous_clusters = ranking_service.cluster_and_rank(prev_entries)
    previous_event_keys = {
        str(cluster.get("event_key"))
        for cluster in previous_clusters
        if cluster.get("event_key")
    }
    clusters = ranking_service.cluster_and_rank(entries, excluded_event_keys=previous_event_keys)[:max_candidates]
    if not clusters:
        _store_empty_digest(
            db,
            digest,
            title,
            "过去 60 分钟内暂无新增高优先事件。",
            content_count=len(rows),
            sources=source_names,
        )
        return None

    return {
        "db": db,
        "digest": digest,
        "title": title,
        "clusters": clusters,
        "prompt": _build_prompt(title, clusters, candidate_limit=max_candidates),
        "rows": rows,
        "source_names": source_names,
    }


async def clear_hourly_digests():
    """Delete all stored hourly digests."""
    def _clear():
        from app.database import SessionLocal
        from app.models import HourlyDigest

        db = SessionLocal()
        try:
            deleted = db.query(HourlyDigest).delete()
            db.commit()
            logger.info(f"Cleared {deleted} hourly digests")
        finally:
            db.close()

    await asyncio.to_thread(_clear)


async def generate_previous_hour_digest():
    """Generate digest for the previous hour (websites/blogs only)."""
    def _generate():
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            return _build_digest_generation_context(db)
        except Exception:
            db.close()
            raise

    ctx = await asyncio.to_thread(_generate)
    if ctx is None:
        return

    runtime = await get_runtime_from_system_settings(
        setting_key="ai_model",
        default_provider="ollama",
        default_model="deepseek-r1:14b",
        default_api_base="http://localhost:11434",
        default_temperature=0.2,
        default_max_tokens=2400,
    )

    model_client = ModelProviderClient()
    db = ctx["db"]
    try:
        if not runtime:
            await _localize_fallback_clusters(
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
            )
            fallback_body = _build_fallback_digest(
                ctx["title"],
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
                reason="当前未配置可用 AI 模型，已生成简版私人简报。",
            )

            def _save_fallback_without_runtime():
                _store_digest(
                    db,
                    ctx["digest"],
                    ctx["title"],
                    fallback_body,
                    content_count=len(ctx["rows"]),
                    sources=ctx["source_names"],
                )

            await asyncio.to_thread(_save_fallback_without_runtime)
            logger.info("Stored fallback hourly digest because no AI runtime is available")
            return

        try:
            generated_items = await _generate_digest_items_with_ai(
                model_client,
                runtime,
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
            )
            body = _build_digest_from_items(ctx["title"], generated_items) if generated_items else ""
        except Exception as e:
            logger.warning(f"Digest generation failed ({runtime.provider}): {e}")
            await _localize_fallback_clusters(
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
            )
            body = _build_fallback_digest(
                ctx["title"],
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
                reason="AI 生成超时或失败，已自动回退为简版私人简报。",
            )
        if not _is_valid_digest_format(body):
            logger.warning("Digest output invalid, fallback digest will be stored instead")
            await _localize_fallback_clusters(
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
            )
            body = _build_fallback_digest(
                ctx["title"],
                ctx["clusters"],
                candidate_limit=min(6, len(ctx["clusters"])),
                reason="AI 输出未通过格式校验，已自动回退为简版私人简报。",
            )

        def _save():
            _store_digest(
                db,
                ctx["digest"],
                ctx["title"],
                body,
                content_count=len(ctx["rows"]),
                sources=ctx["source_names"],
            )

        await asyncio.to_thread(_save)
        logger.info(f"Generated hourly digest for {ctx['title']}")
    finally:
        db.close()
