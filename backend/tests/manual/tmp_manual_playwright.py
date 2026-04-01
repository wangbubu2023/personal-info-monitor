import asyncio
import json

from playwright.async_api import async_playwright

from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.utils.encryption import decrypt_data

URL = "https://news.google.com/rss/articles/CBMilwNBVV95cUxOMGh6Wm9iOFJtSlNadVFKSmdmc29Ga3pmWHZSZkJJR2FWRWlDckRvcGhsN3FyZ1p5enFMNFhvcXU2dUVfREFHUml3elFlQkd6TksyWDI0a3I0QTY4dVhGZXBVcnNTcEZIbnVlbmJ3ZnVVcUdvU0c1WFlIWEJDYVJvYWVRd1JSZ2lXNGF5dThmbEU1UjlZbjFQNzlZZEdSakdCWVBKZjB0ZUVIN0Q2c1ZHbFFrRjJGSndGWjd6YnVhb2ZIRmZZSUdybklDZGFoR3ZSMWEyS1l4ajRrZmFzU1J2alViUzhzNmh5cEx1LVJBREl0NmpVeWtqZEVlbjlXd0p0Wnktb2MwOW1fT0I4bk1LWk4wN0Utcmp5d0xsbjRXdWtFbkRUelFrZFl0aG00c2N4MGs0TVJfNllST0NTZldqRk1CbWhTSllWX3FNcFdIanZ0aWRjaXctT2lFQkJhU3RjSlp0ZmpGNFVnT0kwdWpGa3NBVC01WEhYSGVQc1ZINS1hSUNZdXAyQTdLNlI5cGNDVk1mQk5RWQ?oc=5"
AUTH_ID = "b80c7463-2cc1-4a4a-a736-ec0f2569af19"


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
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        items = [
            {"name": k, "value": v, "domain": "www.wsj.com", "path": "/"}
            for k, v in cookies.items()
            if k and v is not None
        ]
        await context.add_cookies(items)

        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(2500)

        p_count = await page.locator("article p").count()
        texts = await page.locator("article p").all_inner_texts()
        full = "\n\n".join([t.strip() for t in texts if t.strip()])

        print("page_url=", page.url)
        print("title=", await page.title())
        print("p_count=", p_count)
        print("text_len=", len(full))
        print("preview=", full[:200].replace("\n", " "))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
