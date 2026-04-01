import asyncio
import json

from app.collectors.website import WebsiteCollector
from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.processors.extractor import ContentExtractor
from app.utils.encryption import decrypt_data

URL = "https://news.google.com/rss/articles/CBMilwNBVV95cUxOMGh6Wm9iOFJtSlNadVFKSmdmc29Ga3pmWHZSZkJJR2FWRWlDckRvcGhsN3FyZ1p5enFMNFhvcXU2dUVfREFHUml3elFlQkd6TksyWDI0a3I0QTY4dVhGZXBVcnNTcEZIbnVlbmJ3ZnVVcUdvU0c1WFlIWEJDYVJvYWVRd1JSZ2lXNGF5dThmbEU1UjlZbjFQNzlZZEdSakdCWVBKZjB0ZUVIN0Q2c1ZHbFFrRjJGSndGWjd6YnVhb2ZIRmZZSUdybklDZGFoR3ZSMWEyS1l4ajRrZmFzU1J2alViUzhzNmh5cEx1LVJBREl0NmpVeWtqZEVlbjlXd0p0Wnktb2MwOW1fT0I4bk1LWk4wN0Utcmp5d0xsbjRXdWtFbkRUelFrZFl0aG00c2N4MGs0TVJfNllST0NTZldqRk1CbWhTSllWX3FNcFdIanZ0aWRjaXctT2lFQkJhU3RjSlp0ZmpGNFVnT0kwdWpGa3NBVC01WEhYSGVQc1ZINS1hSUNZdXAyQTdLNlI5cGNDVk1mQk5RWQ?oc=5"
AUTH_ID = "b80c7463-2cc1-4a4a-a736-ec0f2569af19"


def load_cookies() -> dict:
    db = SessionLocal()
    try:
        cfg = db.query(AuthConfig).filter(AuthConfig.id == AUTH_ID).first()
        if not cfg or not cfg.credentials:
            return {}
        raw = decrypt_data(cfg.credentials)
        if isinstance(raw, str):
            raw = json.loads(raw)
        cookies = raw.get("cookies") if isinstance(raw, dict) else {}
        return cookies if isinstance(cookies, dict) else {}
    finally:
        db.close()


async def main() -> None:
    cookies = load_cookies()
    collector = WebsiteCollector()
    extractor = ContentExtractor()
    html, resolved = await collector._fetch_article_html(URL, cookies, "https://www.wsj.com")
    text = await extractor.extract(html or "", resolved or URL)
    print("resolved_url=", resolved)
    print("html_len=", len(html or ""))
    print("text_len=", len(text or ""))
    print("text_preview=", (text or "")[:260].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())
