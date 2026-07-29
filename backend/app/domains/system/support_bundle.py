"""Support bundle generation for seed-user diagnostics."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import desc, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domains.system.doctor import DoctorService
from app.models import BrowserSession, Content, Source, SourceFetchLog
from app.utils.datetime import utcnow_naive

_LOG_TAIL_BYTES = 128 * 1024
_MAX_LOG_LINES = 400
_RECENT_FETCH_LIMIT = 50
_SOURCE_LIMIT = 50
_WEB_CLEAN_DIAGNOSTIC_LIMIT = 50
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|secret|password|cookie|ct0|auth_token)"
    r"([\"'\s:=]+)"
    r"([^\"'\s,}]{8,})"
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")


def _safe_text(value: Any, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    text_value = _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text_value)
    return text_value[:limit]


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _safe_text(value, limit=300)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port is not None else host
        return urlunsplit((parsed.scheme, netloc, parsed.path[:300], "", ""))
    return _safe_text(value, limit=300)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _pseudonymous_id(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return value


def _safe_web_clean_profile(metadata: Any) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    profile = metadata.get("web_clean_profile")
    if not isinstance(profile, dict):
        return None
    allowed = {
        "version",
        "extraction_method",
        "template_id",
        "quality_status",
        "quality_score",
        "text_chars",
        "paragraph_count",
        "boilerplate_ratio",
        "link_density",
        "shadow",
        "blocked",
        "recent_failure_reason",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        value = profile.get(key)
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 160:
            result[key] = value
    return result or None


def _safe_web_clean_diagnostic(content: Content) -> dict[str, Any] | None:
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    web_clean = metadata.get("web_clean")
    if not isinstance(web_clean, dict):
        return None
    trace = web_clean.get("trace") if isinstance(web_clean.get("trace"), dict) else {}
    standardizer = trace.get("standardizer") if isinstance(trace.get("standardizer"), dict) else {}
    safe_standardizer: dict[str, Any] = {}
    for key in (
        "input_chars",
        "output_chars",
        "truncated",
        "removed_elements",
        "removed_attributes",
        "absolutized_urls",
        "promoted_lazy_media",
        "shadow_materialized_count",
        "shadow_timeout",
        "input_sha256",
        "output_sha256",
    ):
        value = standardizer.get(key)
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 128:
            safe_standardizer[key] = value

    safe_candidates: list[dict[str, Any]] = []
    raw_candidates = trace.get("candidates")
    if isinstance(raw_candidates, (list, tuple)):
        for raw in raw_candidates[:12]:
            if not isinstance(raw, dict):
                continue
            candidate: dict[str, Any] = {}
            for key in ("method", "quality_status", "rejected_reason"):
                value = raw.get(key)
                if value is not None:
                    candidate[key] = _safe_text(value, limit=160)
            for key in ("score", "text_chars"):
                value = _safe_number(raw.get(key))
                if value is not None:
                    candidate[key] = value
            signals = raw.get("signals")
            if isinstance(signals, dict):
                safe_signals = {
                    key: value
                    for key in (
                        "paragraph_count",
                        "link_density",
                        "boilerplate_ratio",
                        "title_match_score",
                        "blocked_score",
                        "listing_score",
                    )
                    if (value := _safe_number(signals.get(key))) is not None
                }
                if safe_signals:
                    candidate["signals"] = safe_signals
            safe_candidates.append(candidate)

    template_errors = trace.get("template_validation_errors")
    safe_errors = (
        [_safe_text(item, limit=240) for item in template_errors[:8]]
        if isinstance(template_errors, (list, tuple))
        else []
    )
    diagnostic = {
        "content_ref": _pseudonymous_id(content.id),
        "source_ref": _pseudonymous_id(content.source_id),
        "fetched_at": content.fetched_at,
        "version": _safe_text(web_clean.get("version"), limit=40),
        "extraction_method": _safe_text(web_clean.get("extraction_method"), limit=80),
        "template_id": _safe_text(web_clean.get("template_id"), limit=120),
        "quality_status": _safe_text(web_clean.get("quality_status"), limit=80),
        "quality_score": _safe_number(web_clean.get("quality_score")),
        "text_chars": _safe_number(web_clean.get("text_chars")),
        "paragraph_count": _safe_number(web_clean.get("paragraph_count")),
        "boilerplate_ratio": _safe_number(web_clean.get("boilerplate_ratio")),
        "link_density": _safe_number(web_clean.get("link_density")),
        "shadow": bool(web_clean.get("shadow")),
        "selected_method": _safe_text(trace.get("selected_method"), limit=80),
        "shadow_materialized_count": _safe_number(trace.get("shadow_materialized_count")),
        "shadow_timeout": bool(trace.get("shadow_timeout")),
        "standardizer": safe_standardizer,
        "candidates": safe_candidates,
        "template_validation_errors": [item for item in safe_errors if item],
    }
    return {key: value for key, value in diagnostic.items() if value not in (None, {}, [])}


def _run_git(args: list[str], repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _version_snapshot() -> dict[str, Any]:
    repo = _repo_root()
    return {
        "commit": _run_git(["rev-parse", "--short", "HEAD"], repo),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo),
        "dirty": bool(_run_git(["status", "--porcelain"], repo)),
        "repo": str(repo),
    }


def _runtime_snapshot() -> dict[str, Any]:
    settings = get_settings()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "data_dir": str(Path(settings.data_dir).expanduser()),
        "pid": os.getpid(),
    }


def _health_snapshot(db: Session) -> dict[str, Any]:
    checks: dict[str, str] = {}
    details: dict[str, Any] = {}
    settings = get_settings()
    try:
        db.execute(text("SELECT 1")).scalar()
        checks["database"] = "ok"
    except SQLAlchemyError as exc:
        checks["database"] = "error"
        details["database_error"] = _safe_text(exc, limit=300)

    try:
        from app.scheduler import scheduler

        checks["scheduler"] = "ok" if getattr(scheduler, "running", False) else "error"
        details["scheduled_jobs"] = len(scheduler.get_jobs())
    except (RuntimeError, SQLAlchemyError) as exc:
        checks["scheduler"] = "error"
        details["scheduler_error"] = _safe_text(exc, limit=300)

    try:
        usage = os.statvfs(settings.data_dir)
        free = usage.f_bavail * usage.f_frsize
        checks["disk"] = "ok" if free >= 100 * 1024 * 1024 else "error"
        details["disk_free_bytes"] = free
    except OSError as exc:
        checks["disk"] = "error"
        details["disk_error"] = _safe_text(exc, limit=300)

    return {
        "status": "healthy" if checks and all(v == "ok" for v in checks.values()) else "degraded",
        "checks": checks,
        "details": details,
    }


def _metrics_snapshot() -> dict[str, Any]:
    from app.utils.metrics import request_metrics, source_metrics, task_queue_metrics

    payload = request_metrics.snapshot()
    payload["sources"] = source_metrics.snapshot()
    payload["task_queue"] = task_queue_metrics.snapshot()
    try:
        from app.scheduler import scheduler

        payload["scheduler"] = {
            "running": bool(getattr(scheduler, "running", False)),
            "job_count": len(scheduler.get_jobs()),
        }
    except (RuntimeError, SQLAlchemyError) as exc:
        payload["scheduler"] = {"error": _safe_text(exc, limit=300)}
    return payload


def _queue_snapshot() -> dict[str, Any]:
    from app.background import task_tracker
    from app.platform.config.settings import effective_fetch_concurrency

    status = task_tracker.status()
    settings = get_settings()
    return {
        "running_fetches": status.get("running_fetches"),
        "running_processes": status.get("running_processes"),
        "fetch_concurrency": settings.fetch_concurrency,
        "active_fetch_concurrency": effective_fetch_concurrency(settings),
        "fetch_active_limit": getattr(settings, "fetch_active_limit", 20),
    }


def _source_summary(db: Session) -> dict[str, Any]:
    try:
        total = db.query(func.count(Source.id)).scalar() or 0
        enabled = db.query(func.count(Source.id)).filter(Source.enabled.is_(True)).scalar() or 0
        erroring = (
            db.query(Source)
            .filter(Source.last_error.isnot(None))
            .order_by(desc(Source.error_count), desc(Source.last_fetched_at))
            .limit(_SOURCE_LIMIT)
            .all()
        )
        disabled_or_cooling = (
            db.query(Source)
            .filter((Source.enabled.is_(False)) | (Source.fetch_cooldown_until.isnot(None)))
            .order_by(desc(Source.updated_at))
            .limit(_SOURCE_LIMIT)
            .all()
        )
        session_unhealthy = (
            db.query(Source)
            .filter(Source.session_health_status.isnot(None), Source.session_health_status != "ok")
            .order_by(desc(Source.session_health_validated_at))
            .limit(_SOURCE_LIMIT)
            .all()
        )
        return {
            "counts": {
                "total": total,
                "enabled": enabled,
                "disabled": max(total - enabled, 0),
                "with_last_error": len(erroring),
            },
            "failed_sources": [_serialize_source(source) for source in erroring],
            "disabled_or_cooling_sources": [_serialize_source(source) for source in disabled_or_cooling],
            "session_unhealthy_sources": [_serialize_source(source) for source in session_unhealthy],
        }
    except SQLAlchemyError as exc:
        db.rollback()
        return {
            "counts": {"total": 0, "enabled": 0, "disabled": 0, "with_last_error": 0},
            "failed_sources": [],
            "disabled_or_cooling_sources": [],
            "session_unhealthy_sources": [],
            "error": _safe_text(exc, limit=500),
        }


def _serialize_source(source: Source) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "name": source.name,
        "type": _enum_value(source.type),
        "url": _safe_url(source.url),
        "enabled": bool(source.enabled),
        "last_fetched_at": source.last_fetched_at,
        "error_count": source.error_count or 0,
        "last_error": _safe_text(source.last_error, limit=800),
        "fetch_cooldown_until": source.fetch_cooldown_until,
        "last_fetch_outcome": {
            "code": source.last_fetch_outcome_code,
            "severity": source.last_fetch_outcome_severity,
            "message": _safe_text(source.last_fetch_outcome_message, limit=500),
            "updated_at": source.last_fetch_outcome_updated_at,
        },
        "session_health": {
            "status": source.session_health_status,
            "reason": source.session_health_reason,
            "suggested_action": source.session_health_suggested_action,
            "validated_at": source.session_health_validated_at,
        },
        "web_clean_profile": _safe_web_clean_profile(source.metadata_),
    }


def _web_clean_diagnostics(db: Session) -> list[dict[str, Any]]:
    try:
        rows = (
            db.query(Content)
            .order_by(desc(Content.fetched_at))
            .limit(_WEB_CLEAN_DIAGNOSTIC_LIMIT * 4)
            .all()
        )
        diagnostics: list[dict[str, Any]] = []
        for content in rows:
            diagnostic = _safe_web_clean_diagnostic(content)
            if diagnostic:
                diagnostics.append(diagnostic)
            if len(diagnostics) >= _WEB_CLEAN_DIAGNOSTIC_LIMIT:
                break
        return diagnostics
    except SQLAlchemyError as exc:
        db.rollback()
        return [{"error": _safe_text(exc, limit=500)}]


def _recent_fetches(db: Session) -> list[dict[str, Any]]:
    try:
        rows = (
            db.query(SourceFetchLog, Source.name, Source.type)
            .join(Source, Source.id == SourceFetchLog.source_id)
            .order_by(desc(SourceFetchLog.attempted_at))
            .limit(_RECENT_FETCH_LIMIT)
            .all()
        )
        return [
            {
                "source_id": str(log.source_id),
                "source_name": name,
                "source_type": _enum_value(source_type),
                "attempted_at": log.attempted_at,
                "outcome": log.outcome,
                "severity": log.severity,
                "failure_code": log.failure_code,
                "saved_count": log.saved_count,
                "latency_ms": log.latency_ms,
                "fulltext_ok": log.fulltext_ok,
                "fulltext_total": log.fulltext_total,
                "preferred_strategy": log.preferred_strategy,
            }
            for log, name, source_type in rows
        ]
    except SQLAlchemyError as exc:
        db.rollback()
        return [{"error": _safe_text(exc, limit=500)}]


def _browser_sessions(db: Session) -> list[dict[str, Any]]:
    try:
        rows = db.query(BrowserSession).order_by(desc(BrowserSession.updated_at)).limit(_SOURCE_LIMIT).all()
        return [
            {
                "id": str(session.id),
                "site_url": _safe_url(session.site_url),
                "site_host": session.site_host,
                "profile_name": session.profile_name,
                "status": _enum_value(session.status),
                "last_validated_at": session.last_validated_at,
                "last_error": _safe_text(session.last_error, limit=800),
            }
            for session in rows
        ]
    except SQLAlchemyError as exc:
        db.rollback()
        return [{"error": _safe_text(exc, limit=500)}]


def _log_paths() -> list[Path]:
    candidates = [
        Path(os.environ.get("PIM_LOG_DIR", ".pim-local-logs")) / "backend.log",
        Path.home() / ".pim" / "data" / "pim.log",
    ]
    return [path.expanduser() for path in candidates if path.expanduser().exists()]


def _read_log_tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _LOG_TAIL_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"Unable to read {path}: {_safe_text(exc, limit=300)}\n"
    lines = text.splitlines()[-_MAX_LOG_LINES:]
    return "\n".join(_safe_text(line, limit=2000) or "" for line in lines) + "\n"


def _issue_template(summary: dict[str, Any]) -> str:
    version = summary.get("version") or {}
    runtime = summary.get("runtime") or {}
    return "\n".join(
        [
            "## 问题描述",
            "",
            "## 复现步骤",
            "",
            "## 期望行为",
            "",
            "## 实际行为",
            "",
            "## PIM 诊断摘要",
            "",
            f"- Commit: `{version.get('commit') or 'unknown'}`",
            f"- Branch: `{version.get('branch') or 'unknown'}`",
            f"- Generated at: `{runtime.get('generated_at') or 'unknown'}`",
            f"- Platform: `{runtime.get('platform') or 'unknown'}`",
            "",
            "请附上导出的 support bundle zip。",
            "",
        ]
    )


def _summary_markdown(summary: dict[str, Any]) -> str:
    sources = summary.get("sources") or {}
    counts = sources.get("counts") or {}
    doctor = summary.get("doctor") or {}
    health = summary.get("health") or {}
    version = summary.get("version") or {}
    runtime = summary.get("runtime") or {}
    failed = sources.get("failed_sources") or []
    sessions = summary.get("browser_sessions") or []

    lines = [
        "# PIM Support Bundle",
        "",
        f"- Generated at: `{runtime.get('generated_at') or 'unknown'}`",
        f"- Commit: `{version.get('commit') or 'unknown'}`",
        f"- Branch: `{version.get('branch') or 'unknown'}`",
        f"- Dirty worktree: `{version.get('dirty')}`",
        f"- Platform: `{runtime.get('platform') or 'unknown'}`",
        f"- Data dir: `{runtime.get('data_dir') or 'unknown'}`",
        "",
        "## Health",
        "",
        f"- Doctor: `{doctor.get('overall_status') or 'unknown'}`",
        f"- Health check: `{health.get('status') or 'unknown'}`",
        f"- Sources: `{counts.get('enabled', 0)}` enabled / `{counts.get('total', 0)}` total",
        f"- Sources with last error: `{counts.get('with_last_error', 0)}`",
        f"- Browser sessions: `{len(sessions)}`",
        "",
        "## Recent Failed Sources",
        "",
    ]
    if failed:
        for source in failed[:10]:
            lines.append(
                f"- {source.get('name')} ({source.get('type')}): "
                f"{source.get('last_error') or source.get('last_fetch_outcome', {}).get('message') or 'unknown'}"
            )
    else:
        lines.append("- None recorded.")
    lines.append("")
    lines.append("## Privacy")
    lines.append("")
    lines.append("This bundle excludes pim.db, cookies, runtime-secrets.json, API keys, and raw content bodies.")
    lines.append("")
    return "\n".join(lines)


class SupportBundleService:
    """Create a redacted diagnostic bundle as a zip file."""

    def __init__(self, db: Session):
        self.db = db

    def build_bundle(self, output_path: Path | None = None) -> Path:
        if output_path is None:
            output_path = self.default_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doctor = DoctorService(self.db).audit_all()
        summary: dict[str, Any] = {
            "runtime": _runtime_snapshot(),
            "version": _version_snapshot(),
            "doctor": doctor,
            "health": _health_snapshot(self.db),
            "metrics": _metrics_snapshot(),
            "queue": _queue_snapshot(),
            "sources": _source_summary(self.db),
            "recent_fetches": _recent_fetches(self.db),
            "browser_sessions": _browser_sessions(self.db),
            "web_clean_diagnostics": _web_clean_diagnostics(self.db),
        }
        manifest = {
            "generated_at": summary["runtime"]["generated_at"],
            "schema": "pim.support_bundle.v1",
            "privacy": {
                "excluded": [
                    "pim.db",
                    "cookies",
                    "runtime-secrets.json",
                    "api keys",
                    "raw content bodies",
                ],
                "logs": "tail only, redacted by token-like key names",
            },
            "files": [
                "SUMMARY.md",
                "manifest.json",
                "doctor.json",
                "health.json",
                "metrics.json",
                "queue.json",
                "failed_sources.json",
                "recent_fetches.json",
                "browser_sessions.json",
                "web_clean_diagnostics.json",
                "issue_template.md",
            ],
        }
        log_entries = [(f"logs/{path.name}", _read_log_tail(path)) for path in _log_paths()]
        manifest["files"].extend(name for name, _tail in log_entries)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            self._write_text(zf, "SUMMARY.md", _summary_markdown(summary))
            self._write_json(zf, "manifest.json", manifest)
            self._write_json(zf, "doctor.json", doctor)
            self._write_json(zf, "health.json", summary["health"])
            self._write_json(zf, "metrics.json", summary["metrics"])
            self._write_json(zf, "queue.json", summary["queue"])
            self._write_json(zf, "failed_sources.json", summary["sources"])
            self._write_json(zf, "recent_fetches.json", summary["recent_fetches"])
            self._write_json(zf, "browser_sessions.json", summary["browser_sessions"])
            self._write_json(zf, "web_clean_diagnostics.json", summary["web_clean_diagnostics"])
            self._write_text(zf, "issue_template.md", _issue_template(summary))
            for arcname, tail in log_entries:
                self._write_text(zf, arcname, tail)

        return output_path

    @staticmethod
    def default_output_path() -> Path:
        settings = get_settings()
        stamp = utcnow_naive().strftime("%Y%m%d-%H%M%S")
        return Path(settings.data_dir).expanduser().parent / "support-bundles" / f"pim-support-bundle-{stamp}.zip"

    @staticmethod
    def _write_json(zf: zipfile.ZipFile, name: str, payload: Any) -> None:
        zf.writestr(name, _to_json_bytes(payload))

    @staticmethod
    def _write_text(zf: zipfile.ZipFile, name: str, text: str) -> None:
        zf.writestr(name, text.encode("utf-8"))

    def build_bundle_bytes(self) -> tuple[str, bytes]:
        buffer = io.BytesIO()
        path = self.default_output_path()
        temp_path = path.with_suffix(".tmp.zip")
        built = self.build_bundle(temp_path)
        try:
            data = built.read_bytes()
        finally:
            built.unlink(missing_ok=True)
        buffer.write(data)
        return path.name, buffer.getvalue()


__all__ = ["SupportBundleService"]
