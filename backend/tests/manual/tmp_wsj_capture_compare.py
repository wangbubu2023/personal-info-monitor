import asyncio
import json

from playwright.async_api import async_playwright

from app.database import SessionLocal
from app.models.auth_config import AuthConfig
from app.utils.encryption import decrypt_data

WRAPPER_URL = "https://news.google.com/rss/articles/CBMilwNBVV95cUxOMGh6Wm9iOFJtSlNadVFKSmdmc29Ga3pmWHZSZkJJR2FWRWlDckRvcGhsN3FyZ1p5enFMNFhvcXU2dUVfREFHUml3elFlQkd6TksyWDI0a3I0QTY4dVhGZXBVcnNTcEZIbnVlbmJ3ZnVVcUdvU0c1WFlIWEJDYVJvYWVRd1JSZ2lXNGF5dThmbEU1UjlZbjFQNzlZZEdSakdCWVBKZjB0ZUVIN0Q2c1ZHbFFrRjJGSndGWjd6YnVhb2ZIRmZZSUdybklDZGFoR3ZSMWEyS1l4ajRrZmFzU1J2alViUzhzNmh5cEx1LVJBREl0NmpVeWtqZEVlbjlXd0p0Wnktb2MwOW1fT0I4bk1LWk4wN0Utcmp5d0xsbjRXdWtFbkRUelFrZFl0aG00c2N4MGs0TVJfNllST0NTZldqRk1CbWhTSllWX3FNcFdIanZ0aWRjaXctT2lFQkJhU3RjSlp0ZmpGNFVnT0kwdWpGa3NBVC01WEhYSGVQc1ZINS1hSUNZdXAyQTdLNlI5cGNDVk1mQk5RWQ?oc=5"
AUTH_ID = "b80c7463-2cc1-4a4a-a736-ec0f2569af19"


def load_wsj_cookies() -> dict:
    db = SessionLocal()
    try:
        cfg = db.query(AuthConfig).filter(AuthConfig.id == AUTH_ID).first()
        if not cfg or not cfg.credentials:
            return {}
        raw = decrypt_data(cfg.credentials)
        if isinstance(raw, str):
            raw = json.loads(raw)
        cookies = raw.get("cookies") if isinstance(raw, dict) else {}
        if isinstance(cookies, dict):
            return {str(k): str(v) for k, v in cookies.items() if k and v is not None}
        return {}
    finally:
        db.close()


async def capture(use_cookies: bool, cookies: dict) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ))

        if use_cookies and cookies:
            cookie_items = [
                {"name": name, "value": value, "domain": "www.wsj.com", "path": "/"}
                for name, value in cookies.items()
            ]
            await context.add_cookies(cookie_items)

        page = await context.new_page()
        await page.goto(WRAPPER_URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(2000)

        url = page.url
        title = await page.title()
        p_locator = page.locator("article p")
        p_count = await p_locator.count()
        texts = await p_locator.all_inner_texts()
        cleaned = [t.strip() for t in texts if (t or "").strip()]
        full_text = "\n\n".join(cleaned)
        text_len = len(full_text)

        body_text = await page.locator("body").inner_text()
        lower_body = (body_text or "").lower()
        markers = [k for k in ["subscribe", "sign in", "subscription", "continue reading"] if k in lower_body]

        mode = "with_cookie" if use_cookies else "no_cookie"
        print(f"mode={mode}")
        print(" final_url=", url)
        print(" title=", title)
        print(" article_p_count=", p_count)
        print(" article_text_len=", text_len)
        print(" paywall_markers=", markers[:8])
        if text_len:
            preview = full_text[:220] + ("..." if text_len > 220 else "")
            print(" text_preview=", preview)
        print("---")

        await browser.close()


async def main() -> None:
    cookies = load_wsj_cookies()
    print("cookie_count=", len(cookies))
    await capture(False, cookies)
    await capture(True, cookies)


if __name__ == "__main__":
    asyncio.run(main())
