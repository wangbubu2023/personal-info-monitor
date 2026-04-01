
import os
import psycopg2
from datetime import datetime, timedelta

def analyze_weekly_crawls():
    db_url = "postgresql://shuhuaiwang@localhost:5432/info_monitor"
    last_week = datetime(2026, 3, 22)
    now = datetime(2026, 3, 29)
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # Query all sources and their stats
    query = """
    WITH weekly_stats AS (
        SELECT 
            s.id,
            s.name,
            s.url,
            s.last_fetched_at,
            s.enabled,
            COUNT(c.id) FILTER (WHERE c.fetched_at >= %s) as content_count,
            MAX(c.publish_time) as last_publish_time
        FROM 
            sources s
        LEFT JOIN 
            contents c ON s.id = c.source_id
        GROUP BY 
            s.id, s.name, s.url, s.last_fetched_at, s.enabled
    )
    SELECT 
        name, 
        url, 
        content_count, 
        last_fetched_at, 
        last_publish_time,
        enabled
    FROM 
        weekly_stats
    ORDER BY 
        content_count DESC, name ASC;
    """
    
    cur.execute(query, (last_week,))
    rows = cur.fetchall()
    
    results = []
    for name, url, count, last_fetched, last_publish, enabled in rows:
        reason = "-"
        if count == 0:
            if not enabled:
                reason = "源已禁用"
            elif not last_fetched or last_fetched < last_week:
                reason = "没来得及抓取 (上次抓取在: %s)" % (last_fetched.strftime('%Y-%m-%d') if last_fetched else '从未抓取')
            else:
                # Recently fetched but no new content
                if not last_publish or last_publish < (now - timedelta(days=30)):
                    reason = "这个源的内容过旧 (核心内容更新慢)"
                else:
                    reason = "没有抓取到内容 (可能有反爬或暂无更新)"
        
        results.append({
            "name": name,
            "url": url,
            "count": count,
            "reason": reason
        })
        
    # Output as Markdown table
    print("| 监测源 | URL | 抓取数量 (过去一周) | 备注/原因 |")
    print("| :--- | :--- | :---: | :--- |")
    for r in results:
        print(f"| {r['name']} | [{r['url']}]({r['url']}) | {r['count']} | {r['reason']} |")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    analyze_weekly_crawls()
