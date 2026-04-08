import asyncio
from playwright.async_api import async_playwright
import os

async def debug_zepto_trigger(phone):
    print(f"🚀 Starting Zepto Debug for {phone}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            print("1. Navigating to Zepto...")
            await page.goto("https://www.zepto.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_1_landing.png")
            print("📸 Captured Landing Screenshot")

            # Handle popups
            popup_selectors = [
                "button[aria-label='Location modal close Icon']",
                "button:has-text('Allow')", 
                "button:has-text('Use my location')", 
                "button:has-text('Select Location')"
            ]
            for sel in popup_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        print(f"✨ Found popup: {sel}. Clicking...")
                        await btn.click()
                        await asyncio.sleep(2)
                except: pass

            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_2_after_popups.png")
            print("📸 Captured Post-Popup Screenshot")

            # Find Login
            print("2. Looking for Login button...")
            login_btn = await page.wait_for_selector("button[aria-label='login'], button:has-text('Login')", timeout=15000)
            await login_btn.click(force=True)
            await asyncio.sleep(3)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_3_after_login_click.png")
            print("📸 Captured After Login Click Screenshot")

            # Enter Phone
            print("3. Entering Phone Number...")
            phone_input = await page.wait_for_selector("input[placeholder='Enter Phone Number'], input[type='tel']", timeout=15000)
            await phone_input.fill(phone)
            await asyncio.sleep(2)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_4_phone_filled.png")

            # Click Continue
            print("4. Clicking Continue...")
            submit_btn = await page.wait_for_selector("button:has-text('Continue')", timeout=10000)
            await submit_btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_5_final.png")
            print("✅ If no errors occurred, check your phone for OTP!")

        except Exception as e:
            print(f"❌ Error during debug: {e}")
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_zepto_error.png")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_zepto_trigger("9462783629"))
