import asyncio
from playwright.async_api import async_playwright
import os

async def debug_blinkit_trigger(phone):
    print(f"🚀 Starting Blinkit Debug for {phone}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()
        
        try:
            print("1. Navigating to Blinkit...")
            await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_1_landing.png")
            print("📸 Captured Landing Screenshot")

            # Handle Location Wall
            print("2. Clearing Location Wall...")
            try:
                detect_btn = await page.wait_for_selector("button.location-box, button:has-text('Detect my location')", timeout=5000)
                await detect_btn.click()
                print("✨ Clicked 'Detect my location'")
                await asyncio.sleep(4)
            except:
                print("⚠️ Detect button not found, trying manual type fallback...")
                loc_input = await page.wait_for_selector("input[placeholder*='location']", timeout=3000)
                await loc_input.type("New Delhi", delay=100)
                await asyncio.sleep(2)
                suggestion = await page.wait_for_selector("div[class*='SuggestionItem']", timeout=3000)
                await suggestion.click()
                await asyncio.sleep(4)

            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_2_after_location.png")
            print("📸 Captured Post-Location Screenshot")

            # Trigger Login
            print("3. Clicking Login Button...")
            login_btn = await page.wait_for_selector("div:has-text('Login'), button:has-text('Login')", timeout=10000)
            await login_btn.click(force=True)
            await asyncio.sleep(3)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_3_after_login_click.png")

            # Find Phone Input
            print("4. Looking for Phone Input...")
            # Check current working directory
            import os
            print(f"📁 Current Working Directory: {os.getcwd()}")
            
            error_path = "/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_error.png"
            await page.screenshot(path=error_path)
            if os.path.exists(error_path):
                print(f"📸 VERIFIED: Screenshot saved at {error_path}")
            else:
                print(f"❌ FAILED: Screenshot NOT found at {error_path}")

            phone_input = await page.wait_for_selector("input.login-phone__input.input, input[placeholder*='mobile']", timeout=15000)
            print(f"✅ Found phone input! Filling {phone}...")
            await phone_input.fill(phone)
            await asyncio.sleep(2)
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_4_phone_filled.png")

        except Exception as e:
            print(f"❌ Error during debug: {e}")
            await page.screenshot(path="/Users/soumyakhandelwal/Desktop/Projects 2/Minor 2/apps/scraper/debug_blinkit_error.png")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_blinkit_trigger("9462783629"))
