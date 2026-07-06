import asyncio
import argparse
import sys
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID
from dotenv import load_dotenv

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)

# Load environment variables from .env
load_dotenv(os.path.join(backend_dir, ".env"))

from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal
from app.models import Source, Content
from app.services.probe_service import ProbeService
from app.utils.datetime import utcnow_naive

# Initialize probe service
probe_service = ProbeService()

# Domains and keywords for major platforms that we protect from automated deletion misidentifications
PROTECTED_KEYWORDS = [
    "wsj", "reuters", "nytimes", "bloomberg", "ft.com", "economist", "bbc", "cnn", "guardian", 
    "cnbc", "forbes", "fortune", "businessinsider", "techcrunch", "theverge", "wired",
    "apple", "google", "microsoft", "amazon", "facebook", "meta", "netflix", "youtube", "x.com", 
    "twitter", "substack", "medium", "github", "openai", "anthropic", "huggingface"
]

async def probe_source_task(session, semaphore, source_info, cutoff_date, threshold_days):
    """Worker task to probe a single source and determine activity status."""
    async with semaphore:
        import feedparser
        c = source_info
        try:
            # 1. Probe the source
            probe_result = await probe_service.probe(c["url"], c["type"])
            c["probe_status"] = probe_result.status
            c["probe_strategy"] = probe_result.strategy
            c["probe_message"] = probe_result.message
            c["probe_rss_url"] = probe_result.rss_url
            
            # 2. Extract latest publish date from probe if DB has none
            effective_last_publish = c["db_last_publish"]
            probe_last_publish = None
            
            if probe_result.strategy == "rss" and probe_result.rss_url:
                try:
                    async with session.get(probe_result.rss_url, timeout=10) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            feed = feedparser.parse(text)
                            if feed.entries:
                                entry = feed.entries[0]
                                dt_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
                                if dt_tuple:
                                    probe_last_publish = datetime(*dt_tuple[:6])
                                    if effective_last_publish is None or probe_last_publish > effective_last_publish:
                                        effective_last_publish = probe_last_publish
                except Exception:  # noqa: BLE001 - probe RSS date lookup is best-effort
                    pass

            c["effective_last_publish"] = effective_last_publish
            
            # 3. Comprehensive Decision Logic
            is_stale = False
            suggestion = "KEEP"
            reason = ""
            
            url_lower = c["url"].lower()
            # Protect social platforms and major news from automated deletion
            is_protected = any(keyword in url_lower for keyword in PROTECTED_KEYWORDS)
            if c["type"] in ["x", "youtube"]: 
                is_protected = True

            # Case A: Probe Error (Blocked/Captcha/Change of URL) -> KEEP
            if probe_result.status == "error":
                suggestion = "KEEP (Needs strategy fix)"
                reason = f"无法探测: {probe_result.message}"
            
            # Case B: Confirmed Date Evidence
            elif effective_last_publish:
                if effective_last_publish < cutoff_date:
                    if is_protected:
                        suggestion = "KEEP (Strategy Stale)"
                        reason = f"探测到过期内容({effective_last_publish.strftime('%Y-%m-%d')}), 但由于是知名源，保留并建议排查策略"
                    else:
                        is_stale = True
                        suggestion = "DELETE"
                        reason = f"确认为长期未更新 (最后发布: {effective_last_publish.strftime('%Y-%m-%d')})"
                else:
                    suggestion = "KEEP"
                    reason = f"活跃 (最新发布: {effective_last_publish.strftime('%Y-%m-%d')})"
            
            # Case C: No content anywhere
            else:
                if c["created_at"] < cutoff_date:
                    if is_protected:
                        suggestion = "KEEP"
                        reason = "收录超过半年且无数据，但属于重要源，保留"
                    else:
                        is_stale = True
                        suggestion = "DELETE"
                        reason = "收录超过半年且从未抓取到任何内容"
                else:
                    suggestion = "KEEP"
                    reason = "新源(创建于180天内)，待抓取"

            c["is_stale"] = is_stale
            c["suggestion"] = suggestion
            c["reason"] = reason
            return c

        except Exception as e:  # noqa: BLE001 - one failed probe should not abort analysis
            c["suggestion"] = "KEEP (Probe Exception)"
            c["reason"] = f"程序探测异常: {str(e)[:50]}"
            return c

async def analyze_and_cleanup(dry_run: bool = True):
    print(f"--- Starting Comprehensive Inactive Source Analysis (Dry Run: {dry_run}) ---")
    
    threshold_days = 180
    last_week = utcnow_naive() - timedelta(days=7)
    cutoff_date = utcnow_naive() - timedelta(days=threshold_days)
    
    db: Session = SessionLocal()
    
    try:
        # 1. Identify sources that had 0 content in the past week
        sources = db.query(Source).filter(Source.enabled == True).all()
        print(f"Total enabled sources: {len(sources)}")
        
        candidates_data = []
        for source in sources:
            # Check content count in last 7 days
            content_count = db.query(func.count(Content.id)).filter(
                Content.source_id == source.id,
                Content.fetched_at >= last_week
            ).scalar()
            
            if content_count == 0:
                # Get last publish from DB (if any)
                latest_publish_db = db.query(func.max(Content.publish_time)).filter(
                    Content.source_id == source.id
                ).scalar()
                
                candidates_data.append({
                    "id": source.id,
                    "name": source.name,
                    "url": source.url,
                    "type": source.type.value if hasattr(source.type, 'value') else source.type,
                    "db_last_publish": latest_publish_db,
                    "created_at": source.created_at,
                })

        print(f"Found {len(candidates_data)} candidates (0 content last 7 days). Probing all...")
        
        # 2. Parallel Probe (Concurrency restricted to avoid IP blocks)
        import aiohttp
        semaphore = asyncio.Semaphore(15) 
        
        async with aiohttp.ClientSession() as session:
            tasks = [
                probe_source_task(session, semaphore, c, cutoff_date, threshold_days)
                for c in candidates_data
            ]
            results = await asyncio.gather(*tasks)

        # 3. Output Results as Markdown Table
        stale_count = sum(1 for r in results if r.get("is_stale"))
        print(f"\nReport Summary: Total Candidates: {len(results)}, Deletion Suggested: {stale_count}")
        
        print("\n### Comprehensive Source Activity Report\n")
        print("| 建议操作 | 监测源 | URL | 探测策略 | 证据/发布时间 | 原因/备注 |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        
        # Sort results: DELETE first, then KEEP ordered by name
        results.sort(key=lambda x: (0 if x.get("suggestion") == "DELETE" else 1, x["name"]))
        
        for r in results:
            latest_pub_str = r.get('effective_last_publish').strftime('%Y-%m-%d') if r.get('effective_last_publish') else '无'
            probe_info = f"{r.get('probe_strategy', 'none')} ({r.get('probe_status', 'unknown')})"
            print(f"| **{r.get('suggestion', 'KEEP')}** | {r['name']} | {r['url']} | {probe_info} | {latest_pub_str} | {r.get('reason', '')} |")

        # 4. Final Confirmation Message
        if stale_count > 0 and not dry_run:
            print(f"\n--- Executing Physical Deletion of {stale_count} sources ---")
            for r in results:
                if r.get("is_stale"):
                    source_to_del = db.query(Source).filter(Source.id == r['id']).first()
                    if source_to_del:
                        db.delete(source_to_del)
            db.commit()
            print("Deletion completed.")
        elif stale_count > 0:
            print(f"\n[DRY RUN] Currently identification complete. {stale_count} sources marked for deletion.")
        else:
            print("\nResult: No sources confirmed for deletion based on strict criteria.")

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Comprehensive source activity analysis.")
    parser.add_argument("--delete", action="store_true", help="Actually delete sources")
    args = parser.parse_args()
    
    asyncio.run(analyze_and_cleanup(dry_run=not args.delete))
