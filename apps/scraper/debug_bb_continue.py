import asyncio
from playwright.async_api import async_playwright

async def test_bb_click():
    async with async_playwright() as pw:
        # Use stealth args just in case
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        page = await browser.new_page()
        print("Navigating to bigbasket")
        await page.goto("https://www.bigbasket.com/")
        
        # Click login
        login_btn = await page.wait_for_selector("button:has-text('Login'), a:has-text('Login')", state="visible")
        await login_btn.click()
        print("Clicked login modal trigger")
        
        # Wait for input
        inp = await page.wait_for_selector("input#multiform", state="visible")
        await inp.click(force=True)
        await inp.type("9462783629", delay=100)
        print("Typed phone number")
        await page.evaluate("(el) => el.blur()", inp)

        await asyncio.sleep(2)
        
        # Fetch the Continue button
        btns = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('Continue') || b.innerText.includes('OTP')).map(b => ({
                text: b.innerText,
                className: b.className,
                id: b.id,
                visible: b.offsetParent !== null,
                disabled: b.disabled
            }));
        }""")
        print(f"Buttons found: {btns}")
        
        # Try finding the real visible button
        cont_btn = await page.query_selector("button[type='submit']")
        if not cont_btn:
             cont_btn = await page.locator("button:has-text('Continue')").locator("visible=true").element_handle()
             
        if cont_btn:
            print(f"Found Continue button. Disabled? {await cont_btn.is_disabled()}")
            box = await cont_btn.bounding_box()
            print(f"Box: {box}")
            # Do a slow human click
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
            await page.mouse.down()
            await asyncio.sleep(0.1)
            await page.mouse.up()
            print("Performed human mouse click")
            await asyncio.sleep(2)
            try:
                otp_visible = await page.wait_for_selector("input.w-10.text-center", state="visible", timeout=5000)
                print(f"OTP Box appeared: {otp_visible is not None}")
            except:
                print("OTP Box did not appear")
                await page.screenshot(path="bb_fail_otp.png")
            print("URL after click:", page.url)
        else:
            print("No Continue button found")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_bb_click())
