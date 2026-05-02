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
        headless=True,  # Headless — cart is server-side, user views via 'Go to Cart' button
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    
    # Load user's saved session
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    await stealth_async(context)
    
    page = await context.new_page()
    
    # Land on homepage first to ensure cookies are applied correctly
    await page.goto("https://www.zepto.com", wait_until="domcontentloaded")
    await asyncio.sleep(3)
    
    # Debug: check if logged in
    login_state = await page.evaluate(r'''
        () => {
            try {
                const u = localStorage.getItem("user");
                const parsed = u ? JSON.parse(u) : null;
                // If the user object is valid and has a name or phone, we're fully logged in
                return parsed && (parsed.phone || parsed.name) ? "logged_in:" + (parsed.phone || parsed.name) : "guest";
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
            await page.goto(item.product_url, wait_until="domcontentloaded", timeout=15000)
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

            # Click the initial ADD button (the big button before the stepper appears)
            added = False
            add_result = await page.evaluate(r'''
                () => {
                    // First look for the big ADD / Add To Cart button (NOT the + increment)
                    const all = Array.from(document.querySelectorAll("button, div[role='button']"));
                    const addBtn = all.find(b => {
                        const t = (b.innerText || "").trim().toLowerCase();
                        return t === "add" || t === "add to cart" || t === "add to basket";
                    });
                    if (addBtn) { addBtn.click(); return "clicked_add:" + addBtn.innerText.trim(); }
                    // If stepper already visible (+ button exists), item already added
                    const plus = document.querySelector("button[aria-label='Increase quantity by one']");
                    if (plus) return "already_in_cart";
                    return "not_found";
                }
            ''')
            if add_result and (add_result.startswith("clicked_add") or add_result == "already_in_cart"):
                print(f"[Zepto Checkout] Initial add result: {add_result}")
                await asyncio.sleep(3)  # Wait for the button to morph into [- qty +]
                added = True
            else:
                print(f"[Zepto Checkout] JS click failed ({add_result}), trying Playwright selectors...")
                for sel in ["button[aria-label='Increase quantity by one']", "text='Add To Cart'", "text='Add to Cart'", "button:has-text('Add To Cart')"]:
                    try:
                        btn = await page.wait_for_selector(sel, state="visible", timeout=4000)
                        if btn:
                            await btn.scroll_into_view_if_needed()
                            await btn.click(force=True)
                            print(f"[Zepto Checkout] Clicked initial 'Add' button via '{sel}'")
                            await asyncio.sleep(3)
                            added = True
                            break
                    except:
                        continue
            
            if not added:
                print(f"[Zepto Checkout] WARNING: Could not click 'Add' button for {item.product_url}")

            # Click [+] for additional quantity (if quantity > 1)
            # NOTE: after clicking "Add", the button changes to a [ - N + ] stepper.
            # We need to click '+' exactly (quantity - 1) more times.
            extra_clicks = item.quantity - 1 if added else item.quantity
            print(f"[Zepto Checkout] item.quantity={item.quantity}, extra_clicks={extra_clicks}")
            
            # Read what the current counter shows before we start incrementing
            current_qty = await page.evaluate(r'''
                () => {
                    const counterEl = Array.from(document.querySelectorAll('button, div, span'))
                        .find(e => {
                            const t = (e.innerText || "").trim();
                            return /^\d+$/.test(t) && parseInt(t) >= 1 &&
                                   e.parentElement && e.parentElement.children.length === 3;
                        });
                    return counterEl ? parseInt(counterEl.innerText.trim()) : 1;
                }
            ''')
            print(f"[Zepto Checkout] Current counter = {current_qty}, target = {item.quantity}")
            
            for click_num in range(extra_clicks):
                target_after_click = current_qty + 1
                clicked_plus = False
                
                # Try up to 5 times — verify the counter actually incremented
                for attempt in range(5):
                    res = await page.evaluate(r'''
                        () => {
                            let plusBtn = document.querySelector("button[aria-label='Increase quantity by one']");
                            if (plusBtn) { plusBtn.click(); return 'clicked:aria-label'; }
                            const counterEl = Array.from(document.querySelectorAll('button, div, span'))
                                .find(e => {
                                    const t = (e.innerText || "").trim();
                                    return /^\d+$/.test(t) && parseInt(t) >= 1 &&
                                           e.parentElement && e.parentElement.children.length === 3;
                                });
                            if (counterEl && counterEl.parentElement) {
                                const btn = counterEl.parentElement.children[2];
                                if (btn) { btn.click(); return 'clicked:stepper-' + counterEl.innerText; }
                            }
                            return 'not_found';
                        }
                    ''')
                    
                    if not res or not res.startswith('clicked'):
                        await asyncio.sleep(2)
                        continue
                    
                    # Wait and verify the counter actually went up
                    await asyncio.sleep(2.5)
                    new_qty = await page.evaluate(r'''
                        () => {
                            const counterEl = Array.from(document.querySelectorAll('button, div, span'))
                                .find(e => {
                                    const t = (e.innerText || "").trim();
                                    return /^\d+$/.test(t) && parseInt(t) >= 1 &&
                                           e.parentElement && e.parentElement.children.length === 3;
                                });
                            return counterEl ? parseInt(counterEl.innerText.trim()) : -1;
                        }
                    ''')
                    print(f"[Zepto Checkout] [+] click {click_num+1} attempt {attempt+1}: {res} → counter now={new_qty} (expected {target_after_click})")
                    
                    if new_qty == target_after_click:
                        current_qty = new_qty
                        clicked_plus = True
                        break
                    # Counter didn't update — retry after a longer pause
                    await asyncio.sleep(2)
                
                if not clicked_plus:
                    print(f"[Zepto Checkout] ❌ Could not increment to {target_after_click} for {item.product_url}")
            

            results.append({"url": item.product_url, "status": "success", "added_qty": item.quantity})
        except Exception as e:
            print(f"[Zepto Checkout] Failed to add item: {item.product_url} -> {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Navigate to cart then close — cart is saved server-side, user clicks 'Go to Cart'
    try:
        await page.goto("https://www.zepto.com/?cart=open", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        text = await page.evaluate("document.body.innerText")
        totals = parse_bill(text)
        if totals and (totals.get('item_total') or totals.get('total_payable')):
            results.append({"type": "cart_summary", "totals": totals})
            print(f"[Zepto Checkout] Cart Bill Extracted: {totals}")
        else:
            print("[Zepto Checkout] Cart is empty after adding items! Session likely expired.")
            for r in results:
                if r.get('status') == 'success':
                    r['status'] = 'error'
                    r['error'] = 'Session expired or item unavailable.'
    except Exception as e:
        print(f"[Zepto Checkout] Failed to extract bill: {e}")
    await browser.close()
    return results

async def add_items_to_blinkit_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=True,  # Headless — cart is server-side, user views via 'Go to Cart' button
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    await stealth_async(context)
    page = await context.new_page()
    await page.goto("https://blinkit.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://blinkit.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            # Sanitize URL and name — strip any newlines that may have been stored in cached results
            clean_url = item.product_url.replace("\n", "").replace("\r", "").replace("%0A", "").replace("%0a", "").strip()
            clean_name = " ".join((item.name or "").replace("\n", " ").replace("\r", " ").split()).strip()
            if not clean_url or clean_url == "https://blinkit.com":
                results.append({"url": clean_url, "status": "skipped", "reason": "No valid URL"})
                continue
            print(f"[Blinkit Checkout] Navigating to {clean_url}")
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            success_clicks = 0
            for i in range(item.quantity):
                if clean_name:
                    res = await page.evaluate(CLICK_PRODUCT_BTN_JS, clean_name)
                    print(f"  -> JS Click for '{clean_name}': {res}")
                    if res == 'clicked':
                        success_clicks += 1
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        print(f"  -> JS Click failed for iteration {i+1} with reason: {res}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Blinkit Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Navigate to cart then close — cart is saved server-side
    try:
        await page.goto("https://blinkit.com/cart", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        text = await page.evaluate("document.body.innerText")
        totals = parse_bill(text)
        if totals and (totals.get('item_total') or totals.get('total_payable')):
            results.append({"type": "cart_summary", "totals": totals})
            print(f"[Blinkit Checkout] Cart Bill Extracted: {totals}")
        else:
            print("[Blinkit Checkout] Cart is empty after adding items! Session likely expired.")
            for r in results:
                if r.get('status') in ['success', 'partial']:
                    r['status'] = 'error'
                    r['error'] = 'Session expired or item unavailable.'
    except Exception as e:
        print(f"[Blinkit Checkout] Failed to extract bill: {e}")
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
            await page.goto(item.product_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # Bigbasket is slow to render
            
            success_clicks = 0
            for i in range(item.quantity):
                clicked = False
                
                # Try JS clicker first (uses product name to find the right card)
                if item.name:
                    for attempt in range(3):
                        res = await page.evaluate(CLICK_PRODUCT_BTN_JS, item.name)
                        print(f"  -> BB JS click attempt {attempt+1} for '{item.name}': {res}")
                        if res == 'clicked':
                            success_clicks += 1
                            clicked = True
                            await asyncio.sleep(2)
                            break
                        await asyncio.sleep(1.5)
                

                
                if not clicked:
                    print(f"  -> BB could not click add for '{item.name}' qty {i+1}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            print(f"[Bigbasket Checkout] '{item.name}': {success_clicks}/{item.quantity} → {status}")
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Bigbasket Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Navigate to cart to extract exact totals
    try:
        await page.goto("https://www.bigbasket.com/basket/?nc=nb", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        text = await page.evaluate("document.body.innerText")
        totals = parse_bill(text)
        if totals and (totals.get('item_total') or totals.get('total_payable')):
            results.append({"type": "cart_summary", "totals": totals})
            print(f"[Bigbasket Checkout] Cart Bill Extracted: {totals}")
        else:
            print("[Bigbasket Checkout] Cart is empty after adding items! Session likely expired.")
            for r in results:
                if r.get('status') in ['success', 'partial']:
                    r['status'] = 'error'
                    r['error'] = 'Session expired or item unavailable.'
    except Exception as e:
        print(f"[Bigbasket Checkout] Failed to extract bill: {e}")
    await browser.close()
    return results

