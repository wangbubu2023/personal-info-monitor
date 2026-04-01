import asyncio
from playwright.async_api import async_playwright

URL = "https://news.google.com/rss/articles/CBMilwNBVV95cUxOMGh6Wm9iOFJtSlNadVFKSmdmc29Ga3pmWHZSZkJJR2FWRWlDckRvcGhsN3FyZ1p5enFMNFhvcXU2dUVfREFHUml3elFlQkd6TksyWDI0a3I0QTY4dVhGZXBVcnNTcEZIbnVlbmJ3ZnVVcUdvU0c1WFlIWEJDYVJvYWVRd1JSZ2lXNGF5dThmbEU1UjlZbjFQNzlZZEdSakdCWVBKZjB0ZUVIN0Q2c1ZHbFFrRjJGSndGWjd6YnVhb2ZIRmZZSUdybklDZGFoR3ZSMWEyS1l4ajRrZmFzU1J2alViUzhzNmh5cEx1LVJBREl0NmpVeWtqZEVlbjlXd0p0Wnktb2MwOW1fT0I4bk1LWk4wN0Utcmp5d0xsbjRXdWtFbkRUelFrZFl0aG00c2N4MGs0TVJfNllST0NTZldqRk1CbWhTSllWX3FNcFdIanZ0aWRjaXctT2lFQkJhU3RjSlp0ZmpGNFVnT0kwdWpGa3NBVC01WEhYSGVQc1ZINS1hSUNZdXAyQTdLNlI5cGNDVk1mQk5RWQ?oc=5"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        print("page_url=", page.url)

        links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        wsj = [u for u in links if "wsj.com" in u]
        print("wsj_link_count=", len(wsj))
        for u in wsj[:30]:
            print("wsj_link=", u)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
