from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth.stealth import stealth_async
import json
import os
from datetime import datetime

router = APIRouter()

# Global store for active login sessions (Phone -> Page/Context object)
active_sessions = {}

class AuthRequest(BaseModel):
    phone: str

class VerifyRequest(BaseModel):
    phone: str
    otp: str

# Platform configurations
PLATFORM_CONFIGS = {
    "zepto": {
        "url": "https://www.zepto.com/",
        "login_trigger": "button[aria-label='login'], button:has-text('Login')",
        "phone_input": "input[type='tel'], input[placeholder*='mobile']",
        "continue_btn": "button:has-text('Continue')",
        "otp_input_selector": "input[autocomplete='one-time-code'], input[maxLength='6'], input[maxlength='1'], div:has-text('Enter OTP') input",
        "verify_btn": "button:has-text('Verify'), button:has-text('Submit')",
        "otp_len": 6
    },
    "blinkit": {
        "url": "https://blinkit.com/",
        "login_trigger": "div:has-text('Login'), button:has-text('Login')",
        "phone_input": "input.login-phone__input.input, input[placeholder*='mobile']",
        "continue_btn": "button.PhoneNumberLogin__LoginButton-sc-1j06udd-4.gIRVaM, button:has-text('Continue')",
        "otp_input_selector": "input.otp__input.input",
        "verify_btn": None, # Blinkit usually auto-verifies after last digit
        "otp_len": 4
    },
    "bigbasket": {
        "url": "https://www.bigbasket.com/",
        "login_trigger": "button:has-text('Login'), a:has-text('Login'), div:has-text('Login'), button:has-text('Sign Up'), a:has-text('Sign Up')",
        "phone_input": "input[placeholder*='number'], input[type='tel'], input#multiform",
        "continue_btn": "button:has-text('Continue'), button:has-text('Verify')",
        "otp_input_selector": "input.w-10.text-center",
        "verify_btn": "button:has-text('Verify')",
        "otp_len": 6
    }
}

# Global Shadow-DOM Scanner Script
SHADOW_SCRIPT = """(sel) => {
    const findRecursive = (root) => {
        let found = null;
        try {
            if (sel.startsWith('text=')) {
                const searchText = sel.substring(5);
                found = Array.from(root.querySelectorAll('button, a, div, span'))
                    .find(el => el.innerText && el.innerText.includes(searchText));
            } else {
                found = root.querySelector(sel);
            }
        } catch(e) {}
        
        if (found) return { found: true, id: found.id, selector: sel };
        
        const shadows = Array.from(root.querySelectorAll('*')).filter(el => el.shadowRoot);
        for (const s of shadows) {
            const res = findRecursive(s.shadowRoot);
            if (res.found) return res;
        }
        return { found: false };
    };
    return findRecursive(document);
}"""

async def perform_bigbasket_resend(page, phone):
    """Background task to trigger High-Priority Resend OTP for Bigbasket"""
    print(f"[Auth] [BG] Starting Resend Handshake for {phone}...")
    await asyncio.sleep(35)
    try:
        import random
        # 1. Target Frame Sync
        target_frame = None
        for frame in page.frames:
            if "tata.digital" in frame.url or "authentication" in frame.url:
                target_frame = frame
                break
        
        if not target_frame: target_frame = page
        
        # 2. Shadow-Text Pulse for Resend Link
        res = await target_frame.evaluate(SHADOW_SCRIPT, "text=Resend OTP")
        if res and res["found"]:
            print(f"[Auth] [BG] Found Resend Link via Shadow-Text Pulse")
            rx = 720 + random.randint(-10, 10)
            ry = 650 + random.randint(-5, 5)
            await page.mouse.move(rx, ry)
            await asyncio.sleep(0.5)
            await page.mouse.click(rx, ry)
            print(f"[Auth] [BG] High-Priority Resend Success for {phone}")
        else:
            print(f"[Auth] [BG] Resend Link not found in Shadow Hub")
    except Exception as e:
        print(f"[Auth] [BG] Resend Task Error: {e}")

@router.post("/{platform}/trigger")
async def trigger_otp(platform: str, request: AuthRequest, background_tasks: BackgroundTasks):
    if platform not in PLATFORM_CONFIGS:
        raise HTTPException(status_code=400, detail=f"Platform {platform} not supported")
    
    config = PLATFORM_CONFIGS[platform]
    
    try:
        pw = await async_playwright().start()
        # Use headless=False (visible window) for all platforms to bypass TLS fingerprint detection.
        is_headless = False
        browser = await pw.chromium.launch(
            headless=is_headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"] if not is_headless else []
        )

        # 0. Define Location Manifests
        blinkit_cookies = [
            {"name": "gr_1_lat", "value": "28.642891499999998", "domain": ".blinkit.com", "path": "/"},
            {"name": "gr_1_lon", "value": "77.2190894", "domain": ".blinkit.com", "path": "/"},
            {"name": "gr_1_locality", "value": "New Delhi", "domain": ".blinkit.com", "path": "/"},
            {"name": "gr_1_deviceId", "value": "dfa3b4db-50d3-451d-b43a-84f2a2be71ac", "domain": ".blinkit.com", "path": "/"}
        ]
        
        bigbasket_cookies = [
            {"name": "_bb_pin_code", "value": "201316", "domain": ".bigbasket.com", "path": "/"},
            {"name": "_bb_nhid", "value": "7427", "domain": ".bigbasket.com", "path": "/"},
            {"name": "_bb_dsid", "value": "7427", "domain": ".bigbasket.com", "path": "/"},
            {"name": "_bb_dsevid", "value": "7427", "domain": ".bigbasket.com", "path": "/"},
            {"name": "_bb_addressinfo", "value": "MjguNTcxOTE2Njc5ODAxMzIzfDc3LjM4NTg3MzA4Njc1MDUxfEdhcmRlbmlhIEdhdGV3YXl8MjAxMzE2fE5vaWRhLUdoYXppYWJhZHwxfGZhbHNlfHRydWV8dHJ1ZXxCaWdiYXNrZXRlZXI=", "domain": ".bigbasket.com", "path": "/"},
            {"name": "_bb_lat_long", "value": "MjguNTcxOTE2Njc5ODAxMzIzfDc3LjM4NTg3MzA4Njc1MDUx", "domain": ".bigbasket.com", "path": "/"}
        ]
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        # 0.5 Activate Stealth
        await stealth_async(context)
        
        # 1. Pre-Inject Cookies
        if platform == "blinkit":
            await context.add_cookies(blinkit_cookies)
        elif platform == "bigbasket":
            await context.add_cookies(bigbasket_cookies)

        page = await context.new_page()
        
        # 2. Pre-Inject LocalStorage
        if platform == "blinkit":
            await page.add_init_script("""() => {
                const landmark = "Bhavbhuti Marg, Ratan Lal Market, Kamla Market, Ajmeri Gate, New Delhi, Delhi, 110006, India";
                const locData = {
                    "coords": {
                        "type": "SET_LOCATION",
                        "lat": 28.642891499999998,
                        "lon": 77.2190894,
                        "locality": "New Delhi",
                        "landmark": landmark,
                        "isDefault": false,
                        "cityName": "New Delhi",
                        "id": "New Delhi"
                    }
                };
                localStorage.setItem('location', JSON.stringify(locData));
                localStorage.setItem('user_city', 'New Delhi');
                localStorage.setItem('gr_1_lat', '28.642891499999998');
                localStorage.setItem('gr_1_lon', '77.2190894');
                localStorage.setItem('gr_1_locality', 'New Delhi');
                localStorage.setItem('gr_1_landmark', landmark);
            }""")
        elif platform == "bigbasket":
            await page.add_init_script("""() => {
                localStorage.setItem('address_tooltip_ack', 'true');
                localStorage.setItem('_bb_pincode', '201316');
                localStorage.setItem('_bb_hub_id', '7427');
            }""")

        print(f"[Auth] Navigating to {platform}...")
        await page.goto(config["url"], wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Handle any remaining popups/modals
        try:
            await page.evaluate("""() => {
                // Nuclear removal of blockers and high-z-index overlays
                const blockers = [
                    '.welcome-modal', 
                    'div[class*="Overlay"]', 
                    'div[class*="Location"]', 
                    '#address-tooltip',
                    '.modal-backdrop'
                ];
                blockers.forEach(s => {
                    document.querySelectorAll(s).forEach(e => e.remove());
                });
                
                // Clear ALL high z-index elements that might be blocking the header
                document.querySelectorAll('*').forEach(el => {
                    const zIndex = window.getComputedStyle(el).zIndex;
                    if (parseInt(zIndex) > 1000 && !el.innerText.includes('Login')) {
                        el.remove();
                    }
                });
                
                document.body.style.overflow = 'visible';
            }""")
            
            # Aggressive cleanup for Bigbasket "Got it" tooltips and backdrops
            if platform == "bigbasket":
                try:
                    await page.evaluate("""() => {
                        // 1. Remove anything containing "Got it"
                        document.querySelectorAll('*').forEach(el => {
                            if (el.innerText && el.innerText.includes('Got it')) {
                                el.remove();
                            }
                        });
                        
                        // 2. Remove high z-index overlays that might be blocking clicks
                        document.querySelectorAll('div').forEach(el => {
                            const style = window.getComputedStyle(el);
                            const zIndex = parseInt(style.zIndex);
                            if (zIndex > 100 || style.position === 'fixed' && style.backgroundColor.includes('rgba(0, 0, 0')) {
                                el.remove();
                            }
                        });
                        
                        document.body.style.overflow = 'visible';
                    }""")
                    await asyncio.sleep(2)
                except: pass
        except: pass

        # Handle other popups (Zepto specific/General)
        popups = [
            "button[aria-label='Location modal close Icon']",
            "button:has-text('Allow')", 
            "button:has-text('Use my location')", 
            "button:has-text('Select Location')",
            "button:has-text('Dismiss')"
        ]
        for sel in popups:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(1)
            except: pass

        # 2. Trigger Login Modal
        try:
            print(f"[Auth] Triggering {platform} login modal...")
            if platform == "zepto":
                await page.evaluate("""() => {
                    const btn = document.querySelector('button[aria-label="login"]') || 
                                [...document.querySelectorAll('button')].find(b => b.innerText.includes('Login'));
                    if(btn) btn.click();
                }""")
            elif platform == "bigbasket":
                # Bigbasket: Step 1 - dismiss overlays, Step 2 - click login
                try:
                    # Dismiss any 'Got it' / address tooltips first
                    await page.evaluate("""() => {
                        document.querySelectorAll('button').forEach(b => {
                            if (b.innerText && b.innerText.includes('Got it')) b.click();
                        });
                    }""")
                    await asyncio.sleep(1)
                except: pass

                # Try clicking login via multiple Playwright selectors
                login_selectors = [
                    "a:has-text('Sign In')",
                    "button:has-text('Sign In')",
                    "a:has-text('Login')",
                    "button:has-text('Login')",
                    "[data-qa='login-btn']",
                    "[class*='LoginBtn']",
                    "[class*='login']",
                ]
                clicked = False
                for sel in login_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, timeout=5000, state="visible")
                        await btn.click()
                        print(f"[Auth] Bigbasket login clicked via: {sel}")
                        clicked = True
                        break
                    except: continue

                if not clicked:
                    # JS fallback as absolute last resort for login button
                    await page.evaluate("""() => {
                        const trigger = Array.from(document.querySelectorAll('button, a'))
                            .find(e => e.innerText && e.innerText.match(/Sign In|Login/i) && e.offsetParent !== null);
                        if (trigger) trigger.click();
                    }""")
                    print("[Auth] Login button clicked via JS fallback")

                print("[Auth] Waiting 8s for login modal to open...")
                await asyncio.sleep(8)
            elif platform == "blinkit":
                # Blinkit requires clicking 'Account' to reveal 'Login'
                try:
                    account_btn = await page.wait_for_selector("div:has-text('Account'), .ProfileButton__Container-sc-975teb-3", timeout=5000)
                    await account_btn.click()
                    await asyncio.sleep(1)
                except:
                    print("[Auth] Account header not found, trying direct login click")
                
                login_btn = await page.wait_for_selector(config["login_trigger"], timeout=10000)
                await login_btn.click(force=True)
            else:
                login_btn = await page.wait_for_selector(config["login_trigger"], timeout=10000)
                await login_btn.click(force=True)
        except Exception as e:
            print(f"[Auth] Trigger failed: {e}")
            # Fallback for Blinkit/Others
            login_btn = await page.wait_for_selector(config["login_trigger"], timeout=5000)
            await login_btn.click(force=True)

        # 3. Enter Phone (Universal-Frame + Shadow-DOM Search)
        target_frame = page
        phone_input = None

        if platform == "bigbasket":
            import random
            print("[Auth] Searching for Bigbasket phone input on main page...")

            # input#multiform is the actual BB login phone field.
            # Put it first. Avoid 'number' which matches the pincode field.
            phone_selectors = [
                "input#multiform",
                "input[type='tel']",
                "input[placeholder*='Mobile']",
                "input[placeholder*='mobile']",
                "input[placeholder*='Phone']",
                "input[placeholder*='phone']",
                "input[name='mobile']",
                "input[name='phone']",
                "input[autocomplete='tel']",
            ]
            filled = False

            async def try_fill_and_submit(target_page, sel):
                """Try to fill a phone input and click continue. Returns True on success."""
                try:
                    loc = target_page.locator(sel).first
                    await loc.wait_for(state="visible", timeout=6000)
                    await loc.scroll_into_view_if_needed()
                    # Bigbasket uses a floating label that sits on top of the input.
                    # We must use force=True to click the input despite the label.
                    await loc.click(force=True)
                    await asyncio.sleep(0.8)  # Wait for modal animation
                    await loc.type(str(request.phone), delay=80)  # char-by-char, modal-safe
                    val = await loc.input_value()
                    if str(request.phone) not in val:
                        # Some inputs clear on type; fallback to fill
                        await loc.fill(str(request.phone))
                    print(f"[Auth] ✅ Typed phone via locator: {sel}")
                    
                    # Blur to ensure React registers the input
                    try: await loc.blur()
                    except: pass
                    
                    await asyncio.sleep(1)
                    
                    # Click the OTP trigger button
                    for cont_sel in [
                        "button[type='submit']",
                        "button:has-text('Continue')",
                        "button:has-text('Request OTP')",
                        "button:has-text('Get OTP')",
                        "button:has-text('Send OTP')",
                    ]:
                        try:
                            cont_loc = target_page.locator(cont_sel).locator("visible=true").first
                            await cont_loc.wait_for(state="visible", timeout=3000)
                            
                            # 1. Native slow human coordinate click
                            box = await cont_loc.bounding_box()
                            if box:
                                # Move the mouse smoothly to the button
                                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                                await target_page.mouse.move(x, y, steps=10)
                                # Slow click duration to mimic real human
                                await target_page.mouse.down()
                                await asyncio.sleep(0.15)
                                await target_page.mouse.up()
                                await asyncio.sleep(0.5)
                                
                            # We purposely omit 'cont_loc.click(force=True)' and JS 'el.click()' 
                            # because reCAPTCHA flags those synthetic events and ignores the submission.
                            
                            print(f"[Auth] ✅ Clicked submit (human simulation): {cont_sel}")
                            return True
                        except: continue
                    return True  # Phone typed even if no button found
                except Exception as ex:
                    print(f"[Auth] fill_and_submit failed for {sel}: {ex}")
                    return False

            # ── Strategy A: Direct page selectors ─────────────────────────────────────
            for sel in phone_selectors:
                if await try_fill_and_submit(page, sel):
                    filled = True
                    break

            # ── Strategy B: Page may have navigated to /login or Tata auth URL ────────
            if not filled:
                current_url = page.url
                print(f"[Auth] Phone input not found directly. Current URL: {current_url}")
                try:
                    await page.wait_for_url(lambda u: "login" in u or "auth" in u or "tata" in u, timeout=8000)
                    print(f"[Auth] Page navigated to: {page.url}")
                    for sel in phone_selectors:
                        if await try_fill_and_submit(page, sel):
                            filled = True
                            break
                except: pass

            # ── Strategy C: Coordinate pulse last resort ───────────────────────────────
            if not filled:
                print("[Auth] All selector strategies failed. Coordinate-pulse last resort...")
                await page.mouse.click(720, 435)
                await asyncio.sleep(1)
                for char in str(request.phone):
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.15, 0.35))
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                vx = 720 + random.randint(-10, 10)
                vy = 550 + random.randint(-5, 5)
                await page.mouse.click(vx, vy)

        else:

            phone_input = await target_frame.wait_for_selector(config["phone_input"], timeout=30000, state="visible")
            await phone_input.click()
            await asyncio.sleep(1)
            await phone_input.fill(str(request.phone))
            await asyncio.sleep(1)
            submit_btn = await target_frame.wait_for_selector(config["continue_btn"], timeout=10000)
            await submit_btn.click()
        
        # 5. Background the Resend-Pulse for Bigbasket to prevent API timeouts
        if platform == "bigbasket":
            background_tasks.add_task(perform_bigbasket_resend, page, request.phone)
            
        # Store session immediately with all primitives to avoid verify-step crashes
        active_sessions[f"{platform}_{request.phone}"] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
            "platform": platform,
            "phone": request.phone,
            "timestamp": datetime.now()
        }
        
        return {"success": True, "message": "Handshake initiated. Monitoring for OTP delivery."}
    except Exception as e:
        print(f"[Auth] {platform} Trigger Error: {e}")
        # Clean up on failure
        if 'browser' in locals(): await browser.close()
        if 'pw' in locals(): await pw.stop()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{platform}/verify")
async def verify_otp(platform: str, request: VerifyRequest):
    session_key = f"{platform}_{request.phone}"
    if session_key not in active_sessions:
        raise HTTPException(status_code=400, detail="No active session found. Please trigger OTP first.")
    
    session = active_sessions[session_key]
    page = session["page"]
    context = session["context"]
    config = PLATFORM_CONFIGS[platform]
    
    try:
        print(f"[Auth] Verifying OTP for {platform}...")
        
        target_frame = page
        if platform == "bigbasket":
            print("[Auth] Scanning for Bigbasket Verify Iframe...")
            for frame in page.frames:
                try:
                    if await frame.query_selector(config["verify_btn"]):
                        print(f"[Auth] Found Verify Button in Iframe: {frame.name or frame.url}")
                        target_frame = frame
                        break
                except: continue

        # Fill the OTP digits
        try:
            if config.get("otp_input_selector"):
                otp_input = target_frame.locator(config["otp_input_selector"]).first
                await otp_input.wait_for(state="visible", timeout=8000)
                await otp_input.scroll_into_view_if_needed()
                await otp_input.click(force=True)
                await otp_input.type(str(request.otp), delay=150)
                print(f"[Auth] ✅ Typed OTP: {request.otp}")
                await asyncio.sleep(2)  # wait for framework to register OTP
        except Exception as e:
            print(f"[Auth] Failed to type OTP: {e}")

        # Click verify button only for platforms that have one (not Zepto — it auto-submits)
        if config["verify_btn"]:
            try:
                verify_btn = await target_frame.wait_for_selector(config["verify_btn"], timeout=10000)
                await verify_btn.click()
                print(f"[Auth] Clicked verify button.")
            except Exception as e:
                print(f"[Auth] Verify button error (may be OK if auto-submit): {e}")

        # For Zepto: after OTP is typed, it auto-submits.
        # Wait up to 15 seconds for the login modal to close and profile to appear
        if platform == "zepto":
            print(f"[Auth] Zepto: Waiting for login to succeed...")
            try:
                # Look for a sign of successful login: the login modal is gone AND the 'Login' button in header is gone
                is_logged_in = False
                for _ in range(15):
                    login_modal = await page.query_selector("text='Enter OTP'")
                    
                    if not login_modal:
                        is_logged_in = True
                        print(f"[Auth] Zepto: Login successful (modal is gone)!")
                        break
                    await asyncio.sleep(1)
                
                if not is_logged_in:
                    print(f"[Auth] Zepto: Login validation timed out. Assuming failed login.")
                    raise Exception("OTP rejected or login timed out. Please try again.")
                
                # Give 4 extra seconds for cookies and local storage to fully settle
                await asyncio.sleep(4)
            except Exception as e:
                print(f"[Auth] Zepto login failed: {e}")
                raise
        else:
            # Non-Zepto: generic wait for success
            await asyncio.sleep(5)
        
        # Capture Storage State
        storage_state = None
        try:
            storage_state = await context.storage_state()
            cookie_count = len(storage_state.get('cookies', []))
            print(f"[Auth] ✅ Captured storage state: {cookie_count} cookies from {page.url}")
            if cookie_count == 0:
                print(f"[Auth] ⚠️ WARNING: Zero cookies captured — login may have failed!")
        except Exception as e:
            print(f"[Auth] Warning: Could not capture storage state: {e}")
        
        # Cleanup
        await session["browser"].close()
        await session["pw"].stop()
        if session_key in active_sessions:
            del active_sessions[session_key]
            print(f"[Auth] Cleaned up session for {session_key}")
        
        return {
            "success": True, 
            "storage_state": storage_state
        }
    except Exception as e:
        print(f"[Auth] Verify Error: {e}")
        try:
            await session["browser"].close()
            await session["pw"].stop()
        except: pass
        active_sessions.pop(session_key, None)
        raise HTTPException(status_code=500, detail=str(e))

