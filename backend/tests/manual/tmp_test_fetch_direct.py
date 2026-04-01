import asyncio
import json

from app.collectors.website import WebsiteCollector
from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.processors.extractor import ContentExtractor
from app.utils.encryption import decrypt_data

URL = "https://www.wsj.com/opinion/indias-military-makes-strides-but-lags-behind-china-8511d226"
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
