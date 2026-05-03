from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
from playwright.async_api import async_playwright, Playwright
from playwright_stealth.stealth import stealth_async

router = APIRouter()

class CheckoutItem(BaseModel):
    product_url: str
    quantity: int
    name: Optional[str] = None

import re
def parse_bill(text: str) -> dict:
    totals = {}
    if not text: return totals
    lines = [line.strip().lower() for line in text.split('\n') if line.strip()]
    
    def get_price(idx):
        if idx + 1 < len(lines):
            val = lines[idx+1]
            if 'free' in val or 'strike' in val: return 0.0
            match = re.search(r'(\d+(\.\d+)?)', val)
            if match: return float(match.group(1))
        return None
        
    for i, line in enumerate(lines):
        if 'item total' in line or 'items total' in line or 'mrp total' in line or 'basket value' in line:
            if 'item_total' not in totals: totals['item_total'] = get_price(i)
        elif 'delivery charge' in line or 'delivery fee' in line or ('delivery' in line and len(line) < 15):
            if 'delivery_fee' not in totals: totals['delivery_fee'] = get_price(i)
        elif 'handling charge' in line or 'handling fee' in line or 'platform fee' in line:
            if 'handling_fee' not in totals: totals['handling_fee'] = get_price(i)
        elif 'surge' in line or 'small cart' in line or 'rain' in line:
            if 'surge_fee' not in totals: totals['surge_fee'] = get_price(i)
        elif line in ['to pay', 'grand total', 'total amount', 'total payable', 'amount payable']:
            if 'total_payable' not in totals: totals['total_payable'] = get_price(i)

    # Blinkit format: "N item ₹XX" or "N items ₹XX" on same line
    if 'item_total' not in totals:
        blinkit_match = re.search(r'\d+\s+items?\s+[₹$]?\s*(\d+(?:\.\d+)?)', ' '.join(lines))
        if blinkit_match:
            totals['item_total'] = float(blinkit_match.group(1))
            
    return totals

CLICK_PRODUCT_BTN_JS = r"""
(name) => {
    try {
        // Use only the first line of the name (ignoring weight/price on newlines)
        const baseName = name.split('\n')[0].toLowerCase();
        // Remove symbols, numbers, and weight units. Extract up to 3 core words.
        const searchWords = baseName
            .replace(/[^a-z0-9\s]/g, ' ')
            .split(/\s+/)
            .filter(w => w.length > 2 && !/^\d+$/.test(w) && !/^(kg|gm|g|ml|ltr|l|pack|pcs|pieces)$/.test(w))
            .slice(0, 3);
        if (searchWords.length === 0) return 'no_search_words';
        
        // Find product cards or containers that have ALL search words AND an add button
        const els = Array.from(document.querySelectorAll('div, a, li'))
            .filter(e => {
                const txt = (e.innerText || "").toLowerCase();
                if (!searchWords.every(w => txt.includes(w))) return false;
                
                // Must have some kind of add/plus button inside it to be considered a product card
                return Array.from(e.querySelectorAll('button, div, span, a')).some(c => {
                    const ct = (c.innerText || "").trim().toUpperCase();
                    return ct === 'ADD' || ct === 'ADD TO BASKET' || ct === 'ADD TO CART' || ct === '+';
                });
            });
            
        if (els.length === 0) return 'not_found';
        
        // Sort by DOM depth (deepest first) to get the specific product card
        els.sort((a, b) => {
            let depthA = 0, depthB = 0;
            let curr = a; while(curr) { depthA++; curr = curr.parentElement; }
            curr = b; while(curr) { depthB++; curr = curr.parentElement; }
            return depthB - depthA;
        });
        
        const card = els[0];
        
        // 1. Try to find ADD button inside the card
        let addBtn = Array.from(card.querySelectorAll('div, button, span, a')).find(e => {
            const t = (e.innerText || "").trim().toUpperCase();
            return t === 'ADD' || t === 'ADD TO BASKET' || t === 'ADD TO CART';
        });
        if (addBtn) { addBtn.click(); return 'clicked'; }
        
        // 2. Try to find exact '+' button
        let plusBtn = Array.from(card.querySelectorAll('div, button, span, a')).find(e => {
            const t = (e.innerText || "").trim();
            const aria = (e.getAttribute && e.getAttribute('aria-label') || "").trim().toLowerCase();
            const cls = (e.className && typeof e.className === 'string' ? e.className : "").toLowerCase();
            return t === '+' || t === 'Increase Quantity' || aria.includes('increase') || aria.includes('plus') || cls.includes('plus') || cls.includes('increment');
        });
        if (plusBtn) { plusBtn.click(); return 'clicked'; }
        
        // 3. Fallback to stepper structure
        let numberEl = Array.from(card.querySelectorAll('div, span')).find(e => 
            /^[1-9]\d*$/.test((e.innerText || "").trim()) && e.parentElement && e.parentElement.children.length === 3
        );
        if (numberEl && numberEl.parentElement && numberEl.parentElement.children[2]) {
            numberEl.parentElement.children[2].click();
            return 'clicked';
        }
        
        return 'no_button_inside_card';
    } catch(e) {
        return 'error';
    }
}
"""

class CheckoutRequest(BaseModel):
    storage_state: Dict[str, Any]
    items: List[CheckoutItem]

@router.post("/{platform}")
async def process_checkout(platform: str, request: CheckoutRequest, req: Request):
    if platform not in ["zepto", "blinkit", "bigbasket"]:
        raise HTTPException(status_code=400, detail="Platform not supported for checkout right now.")
    
    if not request.items:
        raise HTTPException(status_code=400, detail="No items to add to cart.")

    p = req.app.state.playwright

    # Launch Playwright and add items
    try:
        if platform == "zepto":
            results = await add_items_to_zepto_cart(p, request.storage_state, request.items)
        elif platform == "blinkit":
            results = await add_items_to_blinkit_cart(p, request.storage_state, request.items)
        elif platform == "bigbasket":
            results = await add_items_to_bigbasket_cart(p, request.storage_state, request.items)
        return {"success": True, "results": results}
    except Exception as e:
        print(f"Checkout Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def add_items_to_zepto_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=False,  # Visible browser — Zepto detects headless and marks sessions as guest
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-position=0,0",
        ]
    )
    
    # Load user's saved session
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    await stealth_async(context)
    
    page = await context.new_page()
    
    # Land on homepage first — cookies must be applied before navigating to products
    try:
        await page.goto("https://www.zepto.com", wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"[Zepto Checkout] Homepage load warning (ignoring): {e}")
    await asyncio.sleep(5)  # Wait for React to hydrate localStorage from cookies
    
    # If still showing Login, reload once to force cookie application
    header_text = await page.evaluate("() => document.body.innerText.substring(0, 200)")
    if 'Login' in header_text and 'Account' not in header_text:
        print("[Zepto Checkout] Session not yet visible, reloading...")
        try:
            await page.reload(wait_until="domcontentloaded", timeout=20000)
        except: pass
        await asyncio.sleep(4)
    
    # Debug: check if logged in — Zepto stores user as { state: { user: {...}, isAuth: true }, version: 1 }
    await asyncio.sleep(2)  # Extra wait for visible browser to hydrate localStorage from cookies
    login_state = await page.evaluate(r'''
        () => {
            try {
                // Zepto uses Zustand: localStorage.user = { state: { user: {...}, isAuth: bool }, version: N }
                const u = localStorage.getItem("user");
                const parsed = u ? JSON.parse(u) : null;
                
                // Check 1: Zustand-style nested structure (Zepto's actual format)
                const userState = parsed?.state?.user;
                const isAuth = parsed?.state?.isAuth;
                if (userState && (userState.mobileNumber || userState.fullName || userState.id)) {
                    const id = userState.mobileNumber || userState.fullName || userState.id;
                    return "logged_in:" + id;
                }
                if (isAuth === true) return "logged_in:isAuth";
                
                // Check 2: Flat structure (older Zepto sessions)
                if (parsed && (parsed.phone || parsed.name || parsed.mobileNumber)) {
                    return "logged_in:" + (parsed.phone || parsed.mobileNumber || parsed.name);
                }
                
                // Check 3: customerId / id at top level
                if (parsed && (parsed.customerId || parsed.id || parsed.userId)) {
                    return "logged_in:customer_" + (parsed.id || parsed.customerId);
                }
                
                // Check 4: any auth-related key
                const auth = localStorage.getItem("auth") || localStorage.getItem("authKey") || localStorage.getItem("authKeyITS");
                if (auth && auth.length > 10) return "logged_in:auth_token";
                
                return "guest";
            } catch(e) { return "error:" + e.message; }
        }
    ''')
    print(f"[Zepto Checkout] Login state after loading cookies: {login_state}")
    if login_state.startswith("guest") or login_state.startswith("error"):
        print("[Zepto Checkout] Aborting: Session expired or invalid. Cart will not sync to user's device.")
        await browser.close()
        return [{"url": i.product_url, "status": "error", "error": "Session Expired. Please reconnect Zepto."} for i in items]
    
    # ── Clear the existing cart first so we start fresh ──────────────────────
    print("[Zepto Checkout] Clearing existing cart...")
    try:
        await page.goto("https://www.zepto.com/?cart=open", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        # Repeatedly find and click all '-' (decrease) buttons until they're gone
        for _ in range(30):  # max 30 decrements
            removed = await page.evaluate(r'''
                () => {
                    // Find a minus/remove button in the cart
                    const btns = Array.from(document.querySelectorAll("button"));
                    // Look for the "-" button in the stepper (aria-label='Decrease quantity by one')
                    const minusBtn = btns.find(b => 
                        (b.getAttribute("aria-label") || "").toLowerCase().includes("decrease") ||
                        (b.innerText || "").trim() === "-"
                    );
                    if (minusBtn) { minusBtn.click(); return true; }
                    return false;
                }
            ''')
            if not removed:
                break
            await asyncio.sleep(0.8)
        print("[Zepto Checkout] Cart cleared.")
    except Exception as e:
        print(f"[Zepto Checkout] Cart clear warning: {e}")
    

    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://www.zepto.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            print(f"[Zepto Checkout] Navigating to {item.product_url}")
            try:
                await page.goto(item.product_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"[Zepto Checkout] Product page load warning (ignoring): {e}")
            await asyncio.sleep(3)  # Extra wait for JS to hydrate the product page
            
            # Scroll down to reveal Add button below sticky header
            await page.evaluate("window.scrollBy(0, 300)")
            await asyncio.sleep(1)
            
            # Dismiss any location / promo popups that may cover the Add button
            for popup_sel in [
                "button[aria-label='Location modal close Icon']",
                "button[aria-label='Close']",
                "button:has-text('Dismiss')",
                "button:has-text('Not now')",
            ]:
                try:
                    btn = await page.query_selector(popup_sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(1)
                except:
                    pass

            # ─── PHASE 1: Click ADD once — filter to VIEWPORT-VISIBLE elements only ───
            # Zepto product pages have off-screen carousels with ADD buttons at x>1280/y>800
            # We must only click elements whose CENTER is within the visible viewport
            added = False
            clean_name = " ".join((item.name or "").replace("\n", " ").split()).strip()
            
            add_coords = await page.evaluate(r"""
            (name) => {
                const vw = window.innerWidth;
                const vh = window.innerHeight;
                const headerHeight = 100; // Typical sticky header height
                
                const words = name ? name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w => w.length > 3).slice(0, 2) : [];
                
                const all = Array.from(document.querySelectorAll('button, div[role="button"], span, div'));
                const candidates = all.filter(e => {
                    const t = (e.innerText || '').trim().toLowerCase();
                    if (t !== 'add to cart' && t !== 'add' && t !== 'add to basket') return false;
                    
                    const r = e.getBoundingClientRect();
                    const cx = r.x + r.width / 2;
                    const cy = r.y + r.height / 2;
                    
                    // Filter: Must be within viewport, below header, and have reasonable size
                    return cx > 0 && cx < vw && 
                           cy > headerHeight && cy < vh && 
                           r.width > 20 && r.height > 20;
                });
                
                if (!candidates.length) return null;
                
                // Priority 1: Large "Add To Cart" button (likely the main product page button)
                const mainBtn = candidates.find(e => {
                    const t = (e.innerText || '').trim().toLowerCase();
                    const r = e.getBoundingClientRect();
                    return (t === 'add to cart' || t === 'add to basket') && r.width > 100;
                });
                if (mainBtn) {
                    mainBtn.scrollIntoView({block: 'center', behavior: 'instant'});
                    const r = mainBtn.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2, found: 'main_button'};
                }
                
                // Priority 2: Use product name matching to find the correct card
                if (words.length) {
                    for (const el of candidates) {
                        let parent = el.parentElement;
                        for (let d = 0; d < 12 && parent; d++) {
                            const txt = (parent.innerText || '').toLowerCase();
                            if (words.every(w => txt.includes(w))) {
                                el.scrollIntoView({block: 'center', behavior: 'instant'});
                                const r = el.getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2, found: 'name_match'};
                            }
                            parent = parent.parentElement;
                        }
                    }
                }
                
                // Priority 3: Fallback to the largest visible candidate
                candidates.sort((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    return (rb.width * rb.height) - (ra.width * ra.height);
                });
                
                candidates[0].scrollIntoView({block: 'center', behavior: 'instant'});
                const r = candidates[0].getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2, found: 'fallback_size'};
            }
            """, clean_name)
            
            if add_coords:
                await asyncio.sleep(0.4)
                await page.mouse.click(add_coords['x'], add_coords['y'])
                print(f"[Zepto Checkout] ADD click [{add_coords['found']}] at ({add_coords['x']:.0f},{add_coords['y']:.0f}) ✅")
                await asyncio.sleep(3)  # Wait for morphing to stepper
                added = True
                success_clicks = 1  # Track successful clicks
            else:
                print(f"[Zepto Checkout] WARNING: No ADD element found for {item.product_url}")
                success_clicks = 0

            # ─── PHASE 2: Click + stepper (quantity - 1) more times ──────────────────
            # NOTE: Zepto uses SVG icons for + button, NOT text '+'. Use aria-label.
            if added and item.quantity > 1:
                for extra in range(item.quantity - 1):
                    plus_clicked = False
                    for attempt in range(3):
                        try:
                            plus_coords = await page.evaluate(r"""
                            ({name, targetY}) => {
                                const vw = window.innerWidth;
                                const vh = window.innerHeight;
                                const headerHeight = 100;
                                
                                // Zepto stepper: look for button with aria-label containing 'increase'
                                let ariaPlus = Array.from(document.querySelectorAll('button, [role="button"]')).filter(e => {
                                    const a = (e.getAttribute('aria-label') || '').toLowerCase();
                                    return a.includes('increase') || a.includes('add more');
                                }).filter(e => { 
                                    const r = e.getBoundingClientRect(); 
                                    const cx = r.x + r.width/2;
                                    const cy = r.y + r.height/2;
                                    // TIGHT FILTER: Must be in viewport, below header, and VERY near targetY
                                    return cx > 0 && cx < vw && cy > headerHeight && cy < vh && Math.abs(cy - targetY) < 40;
                                });
                                
                                if (ariaPlus.length) {
                                    // Match product name keywords if possible
                                    if (name) {
                                        const words = name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w => w.length > 3).slice(0,2);
                                        for (const el of ariaPlus) {
                                            let parent = el.parentElement;
                                            for (let d = 0; d < 12 && parent; d++) {
                                                if (words.every(w => (parent.innerText||'').toLowerCase().includes(w))) {
                                                    el.scrollIntoView({block:'center',behavior:'instant'});
                                                    const r = el.getBoundingClientRect();
                                                    return {x: r.x+r.width/2, y: r.y+r.height/2, via:'aria-name'};
                                                }
                                                parent = parent.parentElement;
                                            }
                                        }
                                    }
                                    
                                    // Fallback: the one closest to targetY (already filtered by 40px)
                                    ariaPlus.sort((a,b) => {
                                        const ra = a.getBoundingClientRect();
                                        const rb = b.getBoundingClientRect();
                                        return Math.abs((ra.y+ra.height/2) - targetY) - Math.abs((rb.y+rb.height/2) - targetY);
                                    });
                                    
                                    ariaPlus[0].scrollIntoView({block:'center',behavior:'instant'});
                                    const r = ariaPlus[0].getBoundingClientRect();
                                    return {x: r.x+r.width/2, y: r.y+r.height/2, via:'aria-proximity'};
                                }
                                
                                // Last resort: look for '+' text nodes in viewport within tight Y range
                                const plusEls = Array.from(document.querySelectorAll('*')).filter(e => {
                                    const directText = Array.from(e.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
                                    return directText === '+';
                                }).filter(e => { 
                                    const r = e.getBoundingClientRect(); 
                                    const cx = r.x + r.width/2;
                                    const cy = r.y + r.height/2;
                                    return cx > 0 && cx < vw && cy > headerHeight && cy < vh && Math.abs(cy - targetY) < 40;
                                });
                                
                                if (!plusEls.length) return null;
                                plusEls[0].scrollIntoView({block:'center',behavior:'instant'});
                                const r = plusEls[0].getBoundingClientRect();
                                return {x: r.x+r.width/2, y: r.y+r.height/2, via:'text'};
                            }
                            """, {"name": clean_name, "targetY": add_coords['y']})
                            
                            if plus_coords:
                                await asyncio.sleep(0.3)
                                await page.mouse.click(plus_coords['x'], plus_coords['y'])
                                plus_clicked = True
                                success_clicks += 1
                                print(f"[Zepto Checkout] + click #{extra+2} at ({plus_coords['x']:.0f},{plus_coords['y']:.0f}) ✅")
                                await asyncio.sleep(2.5)
                                break
                            else:
                                print(f"[Zepto Checkout] + stepper attempt {attempt+1}: not found")
                                await asyncio.sleep(1)
                        except Exception as ce:
                            print(f"[Zepto Checkout] + stepper attempt {attempt+1} error: {ce}")
                            await asyncio.sleep(0.5)
                    if not plus_clicked:
                        print(f"[Zepto Checkout] Could not click + for unit {extra+2}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            print(f"[Zepto Checkout] '{item.name}': {success_clicks}/{item.quantity} → {status}")
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Zepto Checkout] Failed to add item: {item.product_url} -> {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Navigate to cart and extract bill info
    success = any(r.get('status') in ['success', 'partial'] for r in results)
    try:
        await page.goto("https://www.zepto.com/cart", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(3)
        
        text = await page.evaluate("document.body.innerText")
        totals = parse_bill(text)
        if totals and (totals.get('item_total') or totals.get('total_payable')):
            results.append({"type": "cart_summary", "totals": totals})
            print(f"[Zepto Checkout] Cart Verified: {totals} ✅")
        else:
            print("[Zepto Checkout] Bill extraction incomplete. Items may still be in cart.")
            
        # Always capture state if we had some success
        if success:
            updated_state = await context.storage_state()
            results.append({"type": "updated_storage_state", "state": updated_state})
    except Exception as e:
        print(f"[Zepto Checkout] Final navigation/verification failed: {e}")

    # If any items were added successfully, keep the browser open in a background task
    if success:
        async def keep_zepto_open():
            try:
                print(f"[Zepto Checkout] Browser kept open for 5 minutes for user checkout 🛒")
                await asyncio.sleep(300) 
            except: pass
            finally:
                try: await browser.close()
                except: pass
        asyncio.create_task(keep_zepto_open())
        return results
    
    await browser.close()
    return results

async def add_items_to_blinkit_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=False,  # Visible browser — Blinkit React events don't fire properly in headless
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-position=0,0",
        ]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    await stealth_async(context)
    page = await context.new_page()
    try:
        await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=20000)
    except: pass
    await asyncio.sleep(2)
    
    # Clear localStorage cart before adding — prevents stale data making verification pass
    await page.evaluate("() => { try { localStorage.removeItem('cart'); } catch(e) {} }")
    print("[Blinkit Checkout] Cleared stale localStorage cart")
    
    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://blinkit.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            clean_url = item.product_url.replace("\n", "").replace("\r", "").replace("%0A", "").replace("%0a", "").strip()
            clean_name = " ".join((item.name or "").replace("\n", " ").replace("\r", " ").split()).strip()
            if not clean_url or clean_url == "https://blinkit.com":
                results.append({"url": clean_url, "status": "skipped", "reason": "No valid URL"})
                continue
            print(f"[Blinkit Checkout] Navigating to {clean_url}")
            try:
                await page.goto(clean_url, wait_until="domcontentloaded", timeout=20000)
            except: pass
            
            # Wait for React to fully hydrate product cards (up to 8 seconds)
            try:
                await page.wait_for_function(
                    "() => document.querySelectorAll('*').length > 100 && document.body.innerText.includes('ADD')",
                    timeout=8000
                )
            except: pass
            await asyncio.sleep(3)  # Extra wait for React event listeners to attach
            
            success_clicks = 0
            
            # ─── PHASE 1: Find the correct product card and click ADD once ───────────────
            add_coords = None
            for attempt in range(4):
                try:
                    add_coords = await page.evaluate(r"""
                    (name) => {
                        // Find any visible element whose direct text is exactly "ADD"
                        const addEls = Array.from(document.querySelectorAll('*')).filter(e => {
                            const directText = Array.from(e.childNodes)
                                .filter(n => n.nodeType === 3)
                                .map(n => n.textContent.trim()).join('');
                            return directText === 'ADD' || (e.childNodes.length === 0 && (e.textContent||'').trim() === 'ADD');
                        }).filter(e => {
                            const r = e.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        });
                        
                        if (!addEls.length) return null;
                        
                        // Match to correct product card using name keywords
                        if (name) {
                            const words = name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/)
                                .filter(w => w.length > 3).slice(0, 2);
                            
                            for (const addEl of addEls) {
                                let parent = addEl.parentElement;
                                for (let depth = 0; depth < 15 && parent; depth++) {
                                    const txt = (parent.innerText || '').toLowerCase();
                                    if (words.length && words.every(w => txt.includes(w))) {
                                        addEl.scrollIntoView({block: 'center', behavior: 'instant'});
                                        const r = addEl.getBoundingClientRect();
                                        return {x: r.x + r.width/2, y: r.y + r.height/2, found: 'name_match'};
                                    }
                                    parent = parent.parentElement;
                                }
                            }
                        }
                        
                        // Fallback: first visible ADD
                        addEls[0].scrollIntoView({block: 'center', behavior: 'instant'});
                        const r = addEls[0].getBoundingClientRect();
                        return {x: r.x + r.width/2, y: r.y + r.height/2, found: 'fallback'};
                    }
                    """, clean_name)
                    
                    if add_coords:
                        await asyncio.sleep(0.4)
                        await page.mouse.click(add_coords['x'], add_coords['y'])
                        success_clicks += 1
                        print(f"  -> Blinkit ADD click for '{clean_name}' [{add_coords['found']}]: ({add_coords['x']:.0f},{add_coords['y']:.0f}) ✅")
                        await asyncio.sleep(2)  # Wait for ADD to morph into stepper
                        break
                    else:
                        print(f"  -> Blinkit Phase1 attempt {attempt+1}: no ADD found for '{clean_name}'")
                        await asyncio.sleep(1.5)
                except Exception as ce:
                    print(f"  -> Blinkit Phase1 attempt {attempt+1} error: {ce}")
                    await asyncio.sleep(1)
            
            # ─── PHASE 2: Click the + stepper N-1 more times in the SAME card ──────────
            if add_coords and item.quantity > 1:
                for extra in range(item.quantity - 1):
                    plus_clicked = False
                    for attempt in range(3):
                        try:
                            plus_coords = await page.evaluate(r"""
                            (name) => {
                                // Find stepper '+' button inside the product card matching our name
                                const words = name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/)
                                    .filter(w => w.length > 3).slice(0, 2);
                                
                                // Find all '+' elements (stepper increment)
                                const plusEls = Array.from(document.querySelectorAll('*')).filter(e => {
                                    const directText = Array.from(e.childNodes)
                                        .filter(n => n.nodeType === 3)
                                        .map(n => n.textContent.trim()).join('');
                                    return directText === '+' || e.getAttribute('aria-label') === 'Increase quantity';
                                }).filter(e => {
                                    const r = e.getBoundingClientRect();
                                    return r.width > 0 && r.height > 0;
                                });
                                
                                if (!plusEls.length) return null;
                                
                                // Find the + inside the correct product card
                                if (words.length) {
                                    for (const plusEl of plusEls) {
                                        let parent = plusEl.parentElement;
                                        for (let depth = 0; depth < 15 && parent; depth++) {
                                            const txt = (parent.innerText || '').toLowerCase();
                                            if (words.every(w => txt.includes(w))) {
                                                plusEl.scrollIntoView({block: 'center', behavior: 'instant'});
                                                const r = plusEl.getBoundingClientRect();
                                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                                            }
                                            parent = parent.parentElement;
                                        }
                                    }
                                }
                                
                                // Fallback: first + button
                                plusEls[0].scrollIntoView({block: 'center', behavior: 'instant'});
                                const r = plusEls[0].getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                            }
                            """, clean_name)
                            
                            if plus_coords:
                                await asyncio.sleep(0.3)
                                await page.mouse.click(plus_coords['x'], plus_coords['y'])
                                success_clicks += 1
                                plus_clicked = True
                                print(f"  -> Blinkit + click #{extra+2} for '{clean_name}': ({plus_coords['x']:.0f},{plus_coords['y']:.0f}) ✅")
                                await asyncio.sleep(1)
                                break
                            else:
                                print(f"  -> Blinkit Phase2 attempt {attempt+1}: no + stepper found for '{clean_name}'")
                                await asyncio.sleep(1)
                        except Exception as ce:
                            print(f"  -> Blinkit Phase2 attempt {attempt+1} error: {ce}")
                            await asyncio.sleep(0.5)
                    
                    if not plus_clicked:
                        print(f"  -> Blinkit could not click + for '{clean_name}' unit {extra+2}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Blinkit Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Verify cart via localStorage — Blinkit stores cart in localStorage.cart
    try:
        cart_info = await page.evaluate(r'''
            () => {
                try {
                    const cart = JSON.parse(localStorage.getItem('cart') || 'null');
                    if (!cart) return null;
                    let count = 0;
                    if (cart.items && typeof cart.items === 'object' && !Array.isArray(cart.items)) {
                        count = Object.values(cart.items).reduce((s, v) => s + (v.quantity || v.qty || 1), 0);
                    } else if (Array.isArray(cart.items)) {
                        count = cart.items.reduce((s, v) => s + (v.quantity || v.qty || 1), 0);
                    } else {
                        count = cart.count || cart.total_count || 0;
                    }
                    return {count, total: cart.total_price || cart.item_total || 0};
                } catch(e) { return null; }
            }
        ''')
        print(f"[Blinkit Checkout] localStorage cart: {cart_info}")
        if cart_info and cart_info.get('count', 0) > 0:
            full_cart = await page.evaluate("() => localStorage.getItem('cart')")
            results.append({
                "type": "cart_summary",
                "totals": {"item_total": cart_info.get('total', 0), "item_count": cart_info['count']},
                "cart_data": full_cart
            })
            print(f"[Blinkit Checkout] Cart verified via localStorage: {cart_info['count']} items ✅")
            
            # Save updated storageState back so MongoDB gets the new cart
            updated_state = await context.storage_state()
            results.append({"type": "updated_storage_state", "state": updated_state})
            print("[Blinkit Checkout] Updated storageState captured for saving back to MongoDB ✅")
            
            # Navigate to blinkit.com/cart and keep browser open in background
            # This is the ONLY way to let the user see their cart since Blinkit is localStorage-only
            async def keep_open_and_navigate():
                try:
                    await page.goto("https://blinkit.com/cart", wait_until="domcontentloaded", timeout=15000)
                    print("[Blinkit Checkout] Navigated to blinkit.com/cart — browser open for user 🛒")
                    await asyncio.sleep(300)  # Keep open for 5 minutes
                except: pass
                finally:
                    try: await browser.close()
                    except: pass
            asyncio.create_task(keep_open_and_navigate())
            return results  # Return immediately — browser stays open in background
        else:
            # Fallback: go to cart page and parse text
            try:
                await page.goto("https://blinkit.com/cart", wait_until="domcontentloaded", timeout=15000)
            except: pass
            await asyncio.sleep(3)
            text = await page.evaluate("document.body.innerText")
            totals = parse_bill(text)
            if totals and (totals.get('item_total') or totals.get('total_payable')):
                results.append({"type": "cart_summary", "totals": totals})
                print(f"[Blinkit Checkout] Cart verified via page text: {totals} ✅")
            else:
                steppers = await page.evaluate("() => document.querySelectorAll('button[aria-label*=\"Increase\"], button[aria-label*=\"increase\"]').length")
                if steppers > 0:
                    results.append({"type": "cart_summary", "totals": {"item_count": steppers}})
                    print(f"[Blinkit Checkout] Cart verified via stepper count: {steppers} ✅")
                else:
                    print("[Blinkit Checkout] Cart empty after all verification attempts.")
                    for r in results:
                        if r.get('status') in ['success', 'partial']:
                            r['status'] = 'error'
                            r['error'] = 'Session expired or item unavailable.'
    except Exception as e:
        print(f"[Blinkit Checkout] Failed to verify cart: {e}")
    await browser.close()
    return results

async def add_items_to_bigbasket_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=False, # Necessary to bypass BigBasket's Akamai bot protection
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--window-position=0,0",
        ]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1"
        },
        storage_state=storage_state
    )
    await stealth_async(context)
    page = await context.new_page()
    await page.goto("https://www.bigbasket.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    results = []
    for item in items:
        if not item.product_url:
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            # Bigbasket product_url is either a direct URL or a search URL (/ps/?q=...)
            # In both cases, navigate there and use the JS clicker to find the right product card
            print(f"[Bigbasket Checkout] Navigating to {item.product_url}")
            try:
                await page.goto(item.product_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                print(f"[Bigbasket Checkout] Product page load warning (ignoring): {e}")
            await asyncio.sleep(3)  # Bigbasket is slow to render
            
            success_clicks = 0
            # ─── PHASE 1: Find the correct product card and click ADD once ───────────
            add_coords = None
            base_name = item.name.split('\n')[0].strip() if item.name else "item"
            
            for attempt in range(4):
                try:
                    add_coords = await page.evaluate(r"""
                    (name) => {
                        const words = name.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/)
                            .filter(w => w.length > 2 && !/^(\d+|kg|gm|g|ml|ltr|l|pack|pcs)$/.test(w))
                            .slice(0, 2);
                        
                        const cards = Array.from(document.querySelectorAll('div, li, article'))
                            .filter(e => {
                                const txt = (e.innerText || '').toLowerCase();
                                if (words.length && !words.every(w => txt.includes(w))) return false;
                                const r = e.getBoundingClientRect();
                                return r.width > 50 && r.height > 50;
                            });
                        if (!cards.length) return null;
                        
                        cards.sort((a, b) => (a.offsetWidth * a.offsetHeight) - (b.offsetWidth * b.offsetHeight));
                        
                        for (const card of cards.slice(0, 5)) {
                            const btn = Array.from(card.querySelectorAll('button'))
                                .find(b => {
                                    const t = (b.innerText || '').trim().toLowerCase();
                                    return t === 'add' || t === 'add to basket';
                                });
                            if (btn) {
                                btn.scrollIntoView({block: 'center', behavior: 'instant'});
                                const r = btn.getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                            }
                        }
                        return null;
                    }
                    """, base_name)
                    
                    if add_coords:
                        await asyncio.sleep(0.4)
                        await page.mouse.click(add_coords['x'], add_coords['y'])
                        success_clicks += 1
                        print(f"  -> BB ADD click for '{base_name}': ({add_coords['x']:.0f},{add_coords['y']:.0f}) ✅")
                        await asyncio.sleep(3) # Wait for stepper to appear
                        break
                    else:
                        print(f"  -> BB Phase1 attempt {attempt+1}: not found for '{base_name}'")
                        await asyncio.sleep(1.5)
                except Exception as ce:
                    print(f"  -> BB Phase1 attempt {attempt+1} error: {ce}")
                    await asyncio.sleep(1)

            # ─── PHASE 2: Click [+] stepper for extra quantities ───────────────────
            if add_coords and item.quantity > 1:
                for extra in range(item.quantity - 1):
                    plus_clicked = False
                    for attempt in range(3):
                        try:
                            plus_coords = await page.evaluate(r"""
                            (name) => {
                                const words = name.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/)
                                    .filter(w => w.length > 2).slice(0, 2);
                                
                                const plusBtns = Array.from(document.querySelectorAll('button, div'))
                                    .filter(e => {
                                        const t = (e.innerText || '').trim();
                                        const aria = (e.getAttribute('aria-label') || '').toLowerCase();
                                        return t === '+' || aria.includes('increase') || aria.includes('add');
                                    }).filter(e => {
                                        const r = e.getBoundingClientRect();
                                        return r.width > 0 && r.height > 0;
                                    });
                                
                                if (!plusBtns.length) return null;
                                
                                for (const btn of plusBtns) {
                                    let p = btn.parentElement;
                                    for (let d = 0; d < 12 && p; d++) {
                                        const txt = (p.innerText || '').toLowerCase();
                                        if (words.every(w => txt.includes(w))) {
                                            btn.scrollIntoView({block: 'center', behavior: 'instant'});
                                            const r = btn.getBoundingClientRect();
                                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                                        }
                                        p = p.parentElement;
                                    }
                                }
                                return null;
                            }
                            """, base_name)
                            
                            if plus_coords:
                                await asyncio.sleep(0.3)
                                await page.mouse.click(plus_coords['x'], plus_coords['y'])
                                success_clicks += 1
                                plus_clicked = True
                                print(f"  -> BB + click #{extra+2} for '{base_name}': ({plus_coords['x']:.0f},{plus_coords['y']:.0f}) ✅")
                                await asyncio.sleep(1.5)
                                break
                            else:
                                print(f"  -> BB Phase2 attempt {attempt+1}: + not found")
                                await asyncio.sleep(1)
                        except: await asyncio.sleep(0.5)
                    if not plus_clicked:
                        print(f"  -> BB could not click + for unit {extra+2}")

            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            print(f"[Bigbasket Checkout] '{item.name}': {success_clicks}/{item.quantity} → {status}")
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Bigbasket Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Verify cart via Bigbasket cart API (avoids /basket/ redirect issues with bot-flagged sessions)
    try:
        cart_result = await page.evaluate(r'''
            async () => {
                try {
                    const resp = await fetch("/api/v2/cart/", {
                        headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
                    });
                    if (!resp.ok) return {count: 0, status: resp.status};
                    const data = await resp.json();
                    const count = data?.cart_item_count || data?.tab_details?.length || 0;
                    const total = data?.order_info?.total_amount || data?.bill_details?.bill_total || 0;
                    return {count: parseInt(count) || 0, total: parseFloat(total) || 0};
                } catch(e) { return {count: 0, error: e.toString()}; }
            }
        ''')
        print(f"[Bigbasket Checkout] Cart API result: {cart_result}")
        if cart_result and (cart_result.get('count', 0) > 0 or cart_result.get('total', 0) > 0):
            results.append({"type": "cart_summary", "totals": {"item_total": cart_result.get('total', 0), "item_count": cart_result.get('count', 0)}})
            print(f"[Bigbasket Checkout] Cart verified via API ✅")
        else:
            # Fallback: count '+' stepper buttons visible on the current product page
            steppers = await page.evaluate(r"""
                () => Array.from(document.querySelectorAll('button')).filter(b => {
                    const t = (b.innerText||'').trim();
                    const a = (b.getAttribute('aria-label')||'').toLowerCase();
                    return t === '+' || a.includes('increase') || a.includes('plus');
                }).length
            """)
            print(f"[Bigbasket Checkout] Stepper buttons visible: {steppers}")
            success_results = [r for r in results if r.get('status') in ['success', 'partial']]
            if steppers > 0 or len(success_results) > 0:
                results.append({"type": "cart_summary", "totals": {"item_count": max(steppers, len(success_results))}})
                print(f"[Bigbasket Checkout] Cart verified via clicks/steppers ✅")
            else:
                print("[Bigbasket Checkout] Cart appears empty after all verification. Session may be expired.")
                for r in results:
                    if r.get('status') in ['success', 'partial']:
                        r['status'] = 'error'
                        r['error'] = 'Session expired or cart not persisted. Please reconnect Bigbasket.'
    except Exception as e:
        print(f"[Bigbasket Checkout] Failed to verify cart: {e}")
    await browser.close()
    return results

