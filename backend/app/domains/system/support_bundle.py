"""Support bundle generation for seed-user diagnostics."""

from __future__ import annotations

import io
import json
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
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domains.system.doctor import DoctorService
from app.models import BrowserSession, Source, SourceFetchLog
from app.utils.datetime import utcnow_naive

_LOG_TAIL_BYTES = 128 * 1024
_MAX_LOG_LINES = 400
_RECENT_FETCH_LIMIT = 50
_SOURCE_LIMIT = 50
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
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:300], "", ""))
    return _safe_text(value, limit=300)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


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
    except Exception as exc:  # noqa: BLE001 - bundle should degrade to structured output
        checks["database"] = "error"
        details["database_error"] = _safe_text(exc, limit=300)

    try:
        from app.scheduler import scheduler

        checks["scheduler"] = "ok" if getattr(scheduler, "running", False) else "error"
        details["scheduled_jobs"] = len(scheduler.get_jobs())
    except Exception as exc:  # noqa: BLE001
        checks["scheduler"] = "error"
        details["scheduler_error"] = _safe_text(exc, limit=300)

    try:
        usage = os.statvfs(settings.data_dir)
        free = usage.f_bavail * usage.f_frsize
        checks["disk"] = "ok" if free >= 100 * 1024 * 1024 else "error"
        details["disk_free_bytes"] = free
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001 - bundle should still be exportable on broken DBs
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
    }


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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
