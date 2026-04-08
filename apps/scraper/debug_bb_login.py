"""One-shot debug: what does the headless browser see on bigbasket.com?"""
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth.stealth import stealth_async

async def debug():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        await stealth_async(context)
        page = await context.new_page()

        print("[Debug] Navigating to bigbasket.com...")
        await page.goto("https://www.bigbasket.com/", wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Screenshot 1: after load
        await page.screenshot(path="/tmp/bb_debug_1_loaded.png", full_page=False)
        print(f"[Debug] URL after load: {page.url}")

        # Find Login/SignIn related elements
        result = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('a, button, span, div'))
                .filter(e => e.innerText && e.innerText.match(/sign in|log in|login/i) && e.offsetParent !== null)
                .slice(0, 10)
                .map(e => ({
                    tag: e.tagName,
                    text: e.innerText.trim().slice(0, 60),
                    href: e.href || null,
                    classes: e.className.toString().slice(0, 80),
                    id: e.id
                }));
            return els;
        }""")
        print(f"[Debug] Login-related visible elements: {len(result)}")
        for el in result:
            print(f"  → <{el['tag']}> text='{el['text']}' href={el['href']} id={el['id']} class={el['classes'][:50]}")

        if result:
            # Try clicking the first one via JS
            clicked_href = result[0].get('href')
            print(f"[Debug] Clicking first match...")
            await page.evaluate("""() => {
                const el = Array.from(document.querySelectorAll('a, button, span, div'))
                    .find(e => e.innerText && e.innerText.match(/sign in|log in|login/i) && e.offsetParent !== null);
                if (el) el.click();
            }""")
            await asyncio.sleep(5)

        await page.screenshot(path="/tmp/bb_debug_2_after_click.png", full_page=False)
        print(f"[Debug] URL after click: {page.url}")

        # Check for phone inputs
        phone = await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input'))
                .map(i => ({ type: i.type, placeholder: i.placeholder, id: i.id, name: i.name, visible: i.offsetParent !== null }));
            return inputs;
        }""")
        print(f"[Debug] Inputs on page: {phone}")

        # Check all open pages (for popup detection)
        all_pages = context.pages
        print(f"[Debug] All open pages: {[p.url for p in all_pages]}")

        await browser.close()

asyncio.run(debug())
