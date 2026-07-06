#!/usr/bin/env python3
"""Create and apply a human review sheet for offline-eval candidates."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from scripts.run_offline_eval import VALID_LABELS

REVIEW_COLUMNS = [
    "id",
    "label",
    "suggested_label",
    "suggested_confidence",
    "review_priority",
    "suggested_reason",
    "source_name",
    "source_id",
    "title",
    "url",
    "summary",
    "full_content_excerpt",
]
REVIEW_LABEL_SOURCE = "human-review-sheet-v1"
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: record must be a JSON object")
            records.append(record)
    return records


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _clean_cell(value: Any, *, max_chars: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if max_chars is not None and len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def _review_sort_key(record: dict[str, Any]) -> tuple[int, float, str, str]:
    priority = str(record.get("review_priority") or "").strip().lower()
    confidence = record.get("suggested_confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0
    return (
        _PRIORITY_RANK.get(priority, 3),
        -confidence_value,
        str(record.get("source_name") or ""),
        str(record.get("id") or ""),
    )


def build_review_rows(
    records: list[dict[str, Any]],
    *,
    include_labeled: bool = False,
    max_summary_chars: int = 400,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rows: list[dict[str, str]] = []
    skipped_labeled = 0
    missing_suggestions = 0

    for record in sorted(records, key=_review_sort_key):
        label = str(record.get("label") or "").strip()
        if label and not include_labeled:
            skipped_labeled += 1
            continue
        if not str(record.get("suggested_label") or "").strip():
            missing_suggestions += 1
        rows.append(
            {
                "id": _clean_cell(record.get("id")),
                "label": label,
                "suggested_label": _clean_cell(record.get("suggested_label")),
                "suggested_confidence": _clean_cell(record.get("suggested_confidence")),
                "review_priority": _clean_cell(record.get("review_priority")),
                "suggested_reason": _clean_cell(record.get("suggested_reason")),
                "source_name": _clean_cell(record.get("source_name")),
                "source_id": _clean_cell(record.get("source_id")),
                "title": _clean_cell(record.get("title")),
                "url": _clean_cell(record.get("url") or record.get("original_url")),
                "summary": _clean_cell(record.get("summary"), max_chars=max_summary_chars),
                "full_content_excerpt": _clean_cell(record.get("full_content"), max_chars=max_summary_chars),
            }
        )

    stats = {
        "records": len(records),
        "exported": len(rows),
        "skipped_labeled": skipped_labeled,
        "missing_suggestions": missing_suggestions,
        "by_priority": dict(sorted(Counter(row["review_priority"] or "unknown" for row in rows).items())),
    }
    return rows, stats


def write_review_sheet(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def write_review_html(path: Path, rows: list[dict[str, str]], stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_for_script({"columns": REVIEW_COLUMNS, "rows": rows, "stats": stats})
    title = "PIM Eval Review"
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: Canvas;
      color: CanvasText;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, Canvas);
      background: Canvas;
    }}
    .bar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 10px 14px;
    }}
    h1 {{
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      font-size: 12px;
      color: color-mix(in srgb, CanvasText 70%, Canvas);
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(260px, 360px) 1fr;
      min-height: calc(100vh - 54px);
    }}
    aside {{
      border-right: 1px solid color-mix(in srgb, CanvasText 16%, Canvas);
      overflow: auto;
      max-height: calc(100vh - 54px);
    }}
    .filters {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 10px;
      border-bottom: 1px solid color-mix(in srgb, CanvasText 12%, Canvas);
    }}
    select, button {{
      min-height: 34px;
      border: 1px solid color-mix(in srgb, CanvasText 24%, Canvas);
      border-radius: 6px;
      background: Canvas;
      color: CanvasText;
      font: inherit;
      font-size: 13px;
      padding: 6px 8px;
    }}
    button {{
      cursor: pointer;
      font-weight: 650;
    }}
    button.primary {{
      background: color-mix(in srgb, Highlight 88%, Canvas);
      color: HighlightText;
      border-color: color-mix(in srgb, Highlight 70%, CanvasText);
    }}
    .list {{
      display: grid;
    }}
    .item {{
      display: grid;
      gap: 4px;
      padding: 9px 10px;
      border: 0;
      border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, Canvas);
      text-align: left;
      background: Canvas;
      color: CanvasText;
      min-height: 72px;
      border-radius: 0;
      font-weight: 400;
    }}
    .item[aria-current="true"] {{
      background: color-mix(in srgb, Highlight 14%, Canvas);
      box-shadow: inset 3px 0 0 Highlight;
    }}
    .item-title {{
      font-size: 13px;
      font-weight: 700;
      line-height: 1.3;
    }}
    .pillrow {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      font-size: 11px;
      color: color-mix(in srgb, CanvasText 72%, Canvas);
    }}
    .pill {{
      border: 1px solid color-mix(in srgb, CanvasText 18%, Canvas);
      border-radius: 999px;
      padding: 1px 7px;
    }}
    section {{
      min-width: 0;
      padding: 18px;
      display: grid;
      align-content: start;
      gap: 14px;
    }}
    .review-title {{
      font-size: 22px;
      font-weight: 800;
      line-height: 1.2;
      margin: 0;
      letter-spacing: 0;
    }}
    .source {{
      font-size: 13px;
      color: color-mix(in srgb, CanvasText 68%, Canvas);
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .content {{
      display: grid;
      gap: 12px;
      max-width: 920px;
      line-height: 1.55;
      font-size: 14px;
    }}
    .field {{
      display: grid;
      gap: 5px;
    }}
    .field h2 {{
      margin: 0;
      font-size: 12px;
      color: color-mix(in srgb, CanvasText 62%, Canvas);
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .field div {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    a {{
      color: LinkText;
    }}
    @media (max-width: 760px) {{
      main {{
        grid-template-columns: 1fr;
      }}
      aside {{
        max-height: 36vh;
        border-right: 0;
        border-bottom: 1px solid color-mix(in srgb, CanvasText 16%, Canvas);
      }}
      .bar {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <h1>{html.escape(title)}</h1>
      <div class="meta">
        <span id="progress"></span>
        <button id="download" class="primary" type="button">Download TSV</button>
      </div>
    </div>
  </header>
  <main>
    <aside>
      <div class="filters">
        <select id="priority">
          <option value="all">All priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select id="state">
          <option value="all">All rows</option>
          <option value="unlabeled">Unlabeled</option>
          <option value="labeled">Labeled</option>
        </select>
      </div>
      <div id="list" class="list"></div>
    </aside>
    <section>
      <h2 id="title" class="review-title"></h2>
      <div id="source" class="source"></div>
      <div class="actions">
        <button type="button" data-label="must_see">must_see</button>
        <button type="button" data-label="ok">ok</button>
        <button type="button" data-label="noise">noise</button>
        <button type="button" id="clear">Clear</button>
        <button type="button" id="prev">Prev</button>
        <button type="button" id="next">Next</button>
      </div>
      <div class="content">
        <div class="field"><h2>Suggested</h2><div id="suggested"></div></div>
        <div class="field"><h2>Summary</h2><div id="summary"></div></div>
        <div class="field"><h2>Excerpt</h2><div id="excerpt"></div></div>
        <div class="field"><h2>URL</h2><div><a id="url" href="#" target="_blank" rel="noreferrer"></a></div></div>
      </div>
    </section>
  </main>
  <script>
    const payload = {payload};
    const columns = payload.columns;
    const rows = payload.rows;
    let selected = 0;

    const list = document.getElementById("list");
    const progress = document.getElementById("progress");
    const priority = document.getElementById("priority");
    const state = document.getElementById("state");

    function escapeCell(value) {{
      return String(value || "").replace(/[\\t\\n\\r]+/g, " ").trim();
    }}

    function visibleRows() {{
      return rows.filter((row) => {{
        if (priority.value !== "all" && row.review_priority !== priority.value) return false;
        if (state.value === "labeled" && !row.label) return false;
        if (state.value === "unlabeled" && row.label) return false;
        return true;
      }});
    }}

    function updateProgress() {{
      const labeled = rows.filter((row) => row.label).length;
      progress.textContent = `${{labeled}}/${{rows.length}} labeled`;
    }}

    function renderList() {{
      const visible = visibleRows();
      if (!visible.includes(rows[selected])) selected = rows.indexOf(visible[0] || rows[0]);
      list.innerHTML = "";
      visible.forEach((row) => {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "item";
        button.setAttribute("aria-current", rows[selected] === row ? "true" : "false");
        button.innerHTML = `
          <div class="item-title">${{escapeHtml(row.title || "(untitled)")}}</div>
          <div class="pillrow">
            <span class="pill">${{escapeHtml(row.review_priority || "unknown")}}</span>
            <span class="pill">${{escapeHtml(row.label || "unlabeled")}}</span>
            <span class="pill">${{escapeHtml(row.suggested_label || "no suggestion")}}</span>
          </div>`;
        button.addEventListener("click", () => {{
          selected = rows.indexOf(row);
          render();
        }});
        list.appendChild(button);
      }});
    }}

    function escapeHtml(value) {{
      return String(value || "").replace(/[&<>"']/g, (char) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[char]));
    }}

    function setText(id, value) {{
      document.getElementById(id).textContent = value || "";
    }}

    function renderDetail() {{
      const row = rows[selected] || rows[0];
      if (!row) return;
      setText("title", row.title);
      setText("source", `${{row.source_name || "Unknown source"}} | ${{row.source_id || "no source id"}}`);
      setText("suggested", `${{row.suggested_label || ""}} (${{row.suggested_confidence || "n/a"}}) - ${{row.suggested_reason || ""}}`);
      setText("summary", row.summary);
      setText("excerpt", row.full_content_excerpt);
      const link = document.getElementById("url");
      link.href = row.url || "#";
      link.textContent = row.url || "";
      document.querySelectorAll("[data-label]").forEach((button) => {{
        button.classList.toggle("primary", row.label === button.dataset.label);
      }});
    }}

    function render() {{
      updateProgress();
      renderList();
      renderDetail();
    }}

    function move(delta) {{
      const visible = visibleRows();
      if (!visible.length) return;
      const current = visible.indexOf(rows[selected]);
      const next = Math.max(0, Math.min(visible.length - 1, current + delta));
      selected = rows.indexOf(visible[next]);
      render();
    }}

    document.querySelectorAll("[data-label]").forEach((button) => {{
      button.addEventListener("click", () => {{
        rows[selected].label = button.dataset.label;
        move(1);
      }});
    }});
    document.getElementById("clear").addEventListener("click", () => {{
      rows[selected].label = "";
      render();
    }});
    document.getElementById("prev").addEventListener("click", () => move(-1));
    document.getElementById("next").addEventListener("click", () => move(1));
    priority.addEventListener("change", render);
    state.addEventListener("change", render);
    document.getElementById("download").addEventListener("click", () => {{
      const lines = [columns.join("\\t")].concat(rows.map((row) => columns.map((key) => escapeCell(row[key])).join("\\t")));
      const blob = new Blob([lines.join("\\n") + "\\n"], {{type: "text/tab-separated-values"}});
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "pim_eval_review.tsv";
      link.click();
      URL.revokeObjectURL(link.href);
    }});
    document.addEventListener("keydown", (event) => {{
      if (event.target.tagName === "SELECT") return;
      if (event.key === "1") rows[selected].label = "must_see";
      if (event.key === "2") rows[selected].label = "ok";
      if (event.key === "3") rows[selected].label = "noise";
      if (event.key === "Backspace") rows[selected].label = "";
      if (["1", "2", "3"].includes(event.key)) move(1);
      if (event.key === "ArrowLeft") move(-1);
      if (event.key === "ArrowRight") move(1);
      render();
    }});
    render();
  </script>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def load_review_sheet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = set(reader.fieldnames or [])
        missing = {"id", "label"} - fieldnames
        if missing:
            raise ValueError(f"{path}: missing required columns: {sorted(missing)}")
        return [dict(row) for row in reader]


def apply_review_rows(
    records: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    require_reviewed: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id = {str(record.get("id") or "").strip(): dict(record) for record in records}
    if "" in by_id:
        raise ValueError("input records contain a blank id")

    seen_sheet_ids: set[str] = set()
    errors: list[str] = []
    labels_by_id: dict[str, str] = {}

    for row_no, row in enumerate(rows, start=2):
        record_id = str(row.get("id") or "").strip()
        label = str(row.get("label") or "").strip()
        if not record_id:
            errors.append(f"sheet row {row_no}: id is required")
            continue
        if record_id in seen_sheet_ids:
            errors.append(f"sheet row {row_no}: duplicate id {record_id!r}")
            continue
        seen_sheet_ids.add(record_id)
        if record_id not in by_id:
            errors.append(f"sheet row {row_no}: unknown id {record_id!r}")
            continue
        if not label:
            if require_reviewed:
                errors.append(f"sheet row {row_no}: label is required")
            continue
        if label not in VALID_LABELS:
            errors.append(f"sheet row {row_no}: label must be one of {sorted(VALID_LABELS)}")
            continue
        labels_by_id[record_id] = label

    if errors:
        raise ValueError("\n".join(errors))

    out: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    updated = 0
    remaining_unlabeled = 0

    for record in records:
        item = dict(record)
        record_id = str(item.get("id") or "").strip()
        if record_id in labels_by_id:
            if item.get("label") != labels_by_id[record_id]:
                updated += 1
            item["label"] = labels_by_id[record_id]
            item["label_source"] = REVIEW_LABEL_SOURCE
        if str(item.get("label") or "").strip():
            label_counts[str(item["label"])] += 1
        else:
            remaining_unlabeled += 1
        out.append(item)

    stats = {
        "records": len(out),
        "review_rows": len(rows),
        "updated_labels": updated,
        "remaining_unlabeled": remaining_unlabeled,
        "labels": dict(sorted(label_counts.items())),
    }
    return out, stats


def review_status(
    records: list[dict[str, Any]],
    rows: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    by_id = {str(record.get("id") or "").strip(): record for record in records}
    errors: list[str] = []
    if "" in by_id:
        errors.append("input records contain a blank id")

    labels_by_id: dict[str, str] = {}
    if rows is None:
        for record in records:
            record_id = str(record.get("id") or "").strip()
            label = str(record.get("label") or "").strip()
            if label:
                labels_by_id[record_id] = label
    else:
        seen_sheet_ids: set[str] = set()
        for row_no, row in enumerate(rows, start=2):
            record_id = str(row.get("id") or "").strip()
            label = str(row.get("label") or "").strip()
            if not record_id:
                errors.append(f"sheet row {row_no}: id is required")
                continue
            if record_id in seen_sheet_ids:
                errors.append(f"sheet row {row_no}: duplicate id {record_id!r}")
                continue
            seen_sheet_ids.add(record_id)
            if record_id not in by_id:
                errors.append(f"sheet row {row_no}: unknown id {record_id!r}")
                continue
            if not label:
                continue
            if label not in VALID_LABELS:
                errors.append(f"sheet row {row_no}: label must be one of {sorted(VALID_LABELS)}")
                continue
            labels_by_id[record_id] = label

        missing_sheet_ids = sorted(record_id for record_id in by_id if record_id not in seen_sheet_ids)
        if missing_sheet_ids:
            preview = ", ".join(missing_sheet_ids[:5])
            suffix = "" if len(missing_sheet_ids) <= 5 else f", ... {len(missing_sheet_ids) - 5} more"
            errors.append(f"sheet is missing {len(missing_sheet_ids)} candidate ids: {preview}{suffix}")

    label_counts: Counter[str] = Counter()
    missing_by_priority: Counter[str] = Counter()
    missing_by_suggestion: Counter[str] = Counter()
    remaining_unlabeled = 0
    for record in records:
        record_id = str(record.get("id") or "").strip()
        label = labels_by_id.get(record_id, "")
        if label:
            label_counts[label] += 1
            continue
        remaining_unlabeled += 1
        missing_by_priority[str(record.get("review_priority") or "unknown")] += 1
        missing_by_suggestion[str(record.get("suggested_label") or "unknown")] += 1

    return {
        "ok": not errors and remaining_unlabeled == 0,
        "records": len(records),
        "review_rows": len(rows) if rows is not None else None,
        "labeled": sum(label_counts.values()),
        "remaining_unlabeled": remaining_unlabeled,
        "labels": dict(sorted(label_counts.items())),
        "missing_by_priority": dict(sorted(missing_by_priority.items())),
        "missing_by_suggestion": dict(sorted(missing_by_suggestion.items())),
        "error_count": len(errors),
        "errors": errors,
    }


def _print_stats(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export/apply a human review sheet for eval candidates")
    parser.add_argument("--json", action="store_true", help="Print machine-readable stats")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-sheet", help="Export TSV for manual label review")
    export_parser.add_argument("input", type=Path, help="Candidate JSONL, usually with suggested_* fields")
    export_parser.add_argument("--output", type=Path, required=True, help="Output TSV review sheet")
    export_parser.add_argument("--include-labeled", action="store_true", help="Include rows that already have label")
    export_parser.add_argument("--max-summary-chars", type=int, default=400)

    html_parser = subparsers.add_parser("export-html", help="Export a static browser review page")
    html_parser.add_argument("input", type=Path, help="Candidate JSONL, usually with suggested_* fields")
    html_parser.add_argument("--output", type=Path, required=True, help="Output HTML review page")
    html_parser.add_argument("--include-labeled", action="store_true", help="Include rows that already have label")
    html_parser.add_argument("--max-summary-chars", type=int, default=900)

    apply_parser = subparsers.add_parser("apply-sheet", help="Apply reviewed TSV labels back to JSONL")
    apply_parser.add_argument("input", type=Path, help="Original candidate JSONL")
    apply_parser.add_argument("--sheet", type=Path, required=True, help="Reviewed TSV from export-sheet")
    apply_parser.add_argument("--output", type=Path, required=True, help="Output annotated JSONL")
    apply_parser.add_argument("--require-reviewed", action="store_true", help="Require every sheet row to have label")

    status_parser = subparsers.add_parser("status", help="Report review progress and sheet errors")
    status_parser.add_argument("input", type=Path, help="Candidate JSONL")
    status_parser.add_argument("--sheet", type=Path, help="Reviewed TSV from export-sheet")
    status_parser.add_argument("--require-complete", action="store_true", help="Exit non-zero unless every record is labeled")

    args = parser.parse_args()

    try:
        if args.command == "export-sheet":
            records = _load_jsonl(args.input)
            rows, stats = build_review_rows(
                records,
                include_labeled=args.include_labeled,
                max_summary_chars=args.max_summary_chars,
            )
            write_review_sheet(args.output, rows)
            _print_stats({"input": str(args.input), "output": str(args.output), **stats}, as_json=args.json)
            return 0

        if args.command == "export-html":
            records = _load_jsonl(args.input)
            rows, stats = build_review_rows(
                records,
                include_labeled=args.include_labeled,
                max_summary_chars=args.max_summary_chars,
            )
            write_review_html(args.output, rows, stats)
            _print_stats({"input": str(args.input), "output": str(args.output), **stats}, as_json=args.json)
            return 0

        if args.command == "status":
            records = _load_jsonl(args.input)
            rows = load_review_sheet(args.sheet) if args.sheet else None
            stats = review_status(records, rows)
            payload = {"input": str(args.input), "sheet": str(args.sheet) if args.sheet else None, **stats}
            _print_stats(payload, as_json=args.json)
            if stats["error_count"] > 0:
                return 2
            if args.require_complete and stats["remaining_unlabeled"] > 0:
                return 1
            return 0

        records = _load_jsonl(args.input)
        rows = load_review_sheet(args.sheet)
        annotated, stats = apply_review_rows(records, rows, require_reviewed=args.require_reviewed)
        _write_jsonl(args.output, annotated)
        _print_stats(
            {"input": str(args.input), "sheet": str(args.sheet), "output": str(args.output), **stats},
            as_json=args.json,
        )
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
