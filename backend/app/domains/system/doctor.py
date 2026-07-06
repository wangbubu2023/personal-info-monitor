"""System diagnostic service for PIM."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class DoctorService:
    """Audit system health and configuration."""

    def __init__(self, db=None):
        self.db = db or SessionLocal()

    def audit_all(self) -> Dict[str, Any]:
        """Perform full system audit."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "database": self._audit_database(),
            "environment": self._audit_environment(),
            "workers": self._audit_workers(),
            "collectors": self._audit_collectors(),
            "integrations": self._audit_integrations(),
        }

        failed = 0
        for category in results.values():
            if isinstance(category, dict) and category.get("status") == "error":
                failed += 1

        results["overall_status"] = "ok" if failed == 0 else "degraded" if failed < 3 else "error"
        return results

    def _audit_database(self) -> Dict[str, Any]:
        """Check SQLite and FTS5 status."""
        try:
            sqlite_res = self.db.execute(text("SELECT sqlite_version(), compile_options")).first()
            version = sqlite_res[0]
            options = sqlite_res[1]
            has_fts5 = "ENABLE_FTS5" in options or "FTS5" in options

            contents_count = self.db.execute(text("SELECT count(*) FROM contents")).scalar()
            sources_count = self.db.execute(text("SELECT count(*) FROM sources")).scalar()
            has_alembic = self.db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
            ).scalar()

            return {
                "status": "ok" if has_fts5 else "warning",
                "version": version,
                "fts5_enabled": has_fts5,
                "contents_count": contents_count,
                "sources_count": sources_count,
                "is_migrated": bool(has_alembic),
                "message": "FTS5 search is ready" if has_fts5 else "FTS5 search may be unavailable",
            }
        except Exception as e:  # noqa: BLE001 - doctor audits should return structured failures
            return {"status": "error", "message": f"DB Audit failed: {e}"}

    def _audit_environment(self) -> Dict[str, Any]:
        """Check directories and disk space."""
        data_dir = Path(settings.data_dir).expanduser()
        try:
            _total, _used, free = shutil.disk_usage(data_dir.parent)
            return {
                "status": "ok",
                "data_dir": str(data_dir),
                "data_dir_exists": data_dir.exists(),
                "free_space_gb": round(free / (2**30), 2),
                "is_low_space": free < (1024 * 1024 * 1024),
            }
        except Exception as e:  # noqa: BLE001 - doctor audits should return structured warnings
            return {"status": "warning", "message": f"Env Audit warning: {e}"}

    def _audit_workers(self) -> Dict[str, Any]:
        """Check background worker health."""
        from app.background import task_tracker
        from app.scheduler import scheduler

        status = task_tracker.status()
        return {
            "status": "ok",
            "running_fetches": status["running_fetches"],
            "running_processes": status["running_processes"],
            "scheduler_running": bool(getattr(scheduler, "running", False)),
            "job_count": len(scheduler.get_jobs()),
        }

    def _audit_collectors(self) -> Dict[str, Any]:
        """Check Playwright availability and feature-flag posture."""
        from app.features import playwright_enabled, x_playwright_enabled

        try:
            import playwright  # noqa: F401 - import side-effect (probe)
        except ImportError:
            return {"status": "error", "message": "Playwright not installed in virtualenv"}
        except Exception as e:  # noqa: BLE001 - playwright import can fail for many reasons
            return {"status": "warning", "message": f"Collector Audit warning: {e}"}

        patchright_installed = True
        try:
            import patchright  # noqa: F401 - import side-effect (probe)
        except ImportError:
            patchright_installed = False

        warnings: List[str] = []
        master_on = playwright_enabled()
        x_on = x_playwright_enabled()

        if master_on:
            warnings.append(
                "Playwright 默认启用：如需在强化/无头环境下关闭浏览器自动化，"
                "请设置 PIM_FEATURE_PLAYWRIGHT=false。"
            )
        if x_on:
            warnings.append(
                "X/Twitter Playwright 登录态抓取已开启，该功能触及 X 服务条款灰区"
                "，默认应保持关闭（PIM_FEATURE_X_PLAYWRIGHT=false）。"
            )

        if master_on and not patchright_installed:
            warnings.append(
                "patchright 未安装：Datadome/Cloudflare 级保护站点（NYT/WSJ/"
                "Bloomberg 等）将无法穿透。建议 `uv add patchright && patchright install chromium`。"
            )

        from app.utils.playwright_runtime import backend_name

        status = "ok" if master_on else "warning"
        payload: Dict[str, Any] = {
            "status": status,
            "playwright_installed": True,
            "patchright_installed": patchright_installed,
            "browser_backend": backend_name() if master_on else None,
            "chrome_found": True,
            "playwright_feature_enabled": master_on,
            "x_playwright_feature_enabled": x_on,
        }
        if warnings:
            payload["warnings"] = warnings
        if not master_on:
            payload["message"] = (
                "Playwright 特性已通过 PIM_FEATURE_PLAYWRIGHT=false 关闭；"
                "网站抓取将退化为纯 HTTP + RSS。"
            )
        return payload

    def _audit_integrations(self) -> Dict[str, Any]:
        """Check AI and Translation connectivity."""
        has_openai = bool(settings.openai_api_key)
        return {
            "status": "ok",
            "openai_configured": has_openai,
            "cloud_fallback": settings.cloud_fallback_enabled,
            "message": "AI summarization ready" if has_openai else "Running in local-only mode (No OpenAI Key)",
        }


__all__ = ["DoctorService"]
