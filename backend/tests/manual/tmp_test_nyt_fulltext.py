import asyncio
import json

from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.processors.content_processor import ContentProcessor
from app.utils.encryption import decrypt_data

AUTH_ID = "9c0400f6-9540-4d4f-a75b-30188f63655b"
URL = "https://www.nytimes.com/2026/02/26/world/asia/australia-bondi-one-nation-immigration.html"


def load_cookies() -> dict:
    db = SessionLocal()
    try:
        cfg = db.query(AuthConfig).filter(AuthConfig.id == AUTH_ID).first()
        raw = decrypt_data(cfg.credentials) if cfg and cfg.credentials else {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        cookies = raw.get("cookies") if isinstance(raw, dict) else {}
        return cookies if isinstance(cookies, dict) else {}
    finally:
        db.close()


async def main() -> None:
    cookies = load_cookies()
    p = ContentProcessor()
    text = await p._fetch_full_text_with_cookies(URL, cookies)
    print("cookie_count=", len(cookies))
    print("text_len=", len(text or ""))
    print("preview=", (text or "")[:240].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())
