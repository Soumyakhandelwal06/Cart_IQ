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
    
    # Land on homepage first to ensure cookies are applied correctly
    try:
        await page.goto("https://www.zepto.com", wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"[Zepto Checkout] Homepage load warning (ignoring): {e}")
    await asyncio.sleep(3)
    
    # Debug: check if logged in — check multiple auth signals (localStorage + cookies)
    await asyncio.sleep(2)  # Extra wait for visible browser to hydrate localStorage from cookies
    login_state = await page.evaluate(r'''
        () => {
            try {
                // Check 1: localStorage.user
                const u = localStorage.getItem("user");
                const parsed = u ? JSON.parse(u) : null;
                if (parsed && (parsed.phone || parsed.name)) return "logged_in:" + (parsed.phone || parsed.name);
                
                // Check 2: localStorage.auth or authKey
                const auth = localStorage.getItem("auth") || localStorage.getItem("authKey") || localStorage.getItem("authKeyITS");
                if (auth && auth.length > 10) return "logged_in:auth_token";
                
                // Check 3: localStorage.user but with customerId
                if (parsed && (parsed.customerId || parsed.id || parsed.userId)) return "logged_in:customer";
                
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

            # Click the initial ADD button using Playwright native click (React requires real pointer events)
            added = False
            for add_sel in [
                "button:has-text('Add To Cart')",
                "button:has-text('Add to Cart')",
                "button:has-text('ADD')",
                "button:has-text('Add')",
                "div[role='button']:has-text('Add')",
                "button[aria-label='Increase quantity by one']",
            ]:
                try:
                    add_btn = page.locator(add_sel).first
                    if await add_btn.is_visible():
                        await add_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await add_btn.click()
                        print(f"[Zepto Checkout] Clicked ADD via '{add_sel}'")
                        await asyncio.sleep(3)  # Wait for button to morph into [- qty +]
                        added = True
                        break
                except:
                    continue
            
            # Fallback: try JS click
            if not added:
                add_result = await page.evaluate(r'''
                    () => {
                        const all = Array.from(document.querySelectorAll("button, div[role='button']"));
                        const addBtn = all.find(b => {
                            const t = (b.innerText || "").trim().toLowerCase();
                            return t === "add" || t === "add to cart" || t === "add to basket";
                        });
                        if (addBtn) { addBtn.click(); return "clicked_add:" + addBtn.innerText.trim(); }
                        const plus = document.querySelector("button[aria-label='Increase quantity by one']");
                        if (plus) return "already_in_cart";
                        return "not_found";
                    }
                ''')
                if add_result and (add_result.startswith("clicked_add") or add_result == "already_in_cart"):
                    print(f"[Zepto Checkout] JS fallback add: {add_result}")
                    await asyncio.sleep(3)
                    added = True
                else:
                    print(f"[Zepto Checkout] WARNING: Could not click 'Add' button for {item.product_url}. Result: {add_result}")
            
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
            for i in range(item.quantity):
                clicked = False
                
                for attempt in range(4):
                    try:
                        # Find the first visible ADD element (any tag — Blinkit uses styled divs/spans)
                        add_coords = await page.evaluate("""
                        (name) => {
                            // Find any element whose text is exactly "ADD"
                            const addEls = Array.from(document.querySelectorAll('*')).filter(e => {
                                // Skip elements with children (we want the leaf text node)
                                const directText = Array.from(e.childNodes)
                                    .filter(n => n.nodeType === 3)
                                    .map(n => n.textContent.trim())
                                    .join('');
                                return directText === 'ADD' || (e.childNodes.length === 0 && (e.textContent||'').trim() === 'ADD');
                            });
                            
                            // Filter to only visible ones
                            const visible = addEls.filter(e => {
                                const r = e.getBoundingClientRect();
                                return r.width > 0 && r.height > 0;
                            });
                            
                            if (!visible.length) return null;
                            
                            // If we have a name, try to find the one closest to the product
                            // Otherwise just take the first one
                            if (name) {
                                const words = name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/)
                                    .filter(w => w.length > 3).slice(0, 2);
                                
                                // Find product card for this item
                                for (const addEl of visible) {
                                    let parent = addEl.parentElement;
                                    let found = false;
                                    for (let depth = 0; depth < 15 && parent; depth++) {
                                        const txt = (parent.innerText || '').toLowerCase();
                                        if (words.length && words.every(w => txt.includes(w))) {
                                            found = true;
                                            break;
                                        }
                                        parent = parent.parentElement;
                                    }
                                    if (found) {
                                        addEl.scrollIntoView({block: 'center', behavior: 'instant'});
                                        const r = addEl.getBoundingClientRect();
                                        return {x: r.x + r.width/2, y: r.y + r.height/2};
                                    }
                                }
                            }
                            
                            // Fallback: click first visible ADD
                            visible[0].scrollIntoView({block: 'center', behavior: 'instant'});
                            const r = visible[0].getBoundingClientRect();
                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                        """, clean_name)
                        
                        if add_coords:
                            await asyncio.sleep(0.4)  # Let scroll settle
                            await page.mouse.click(add_coords['x'], add_coords['y'])
                            success_clicks += 1
                            clicked = True
                            print(f"  -> Blinkit mouse.click for '{clean_name}': clicked at ({add_coords['x']:.0f},{add_coords['y']:.0f}) ✅")
                            await asyncio.sleep(2)
                            break
                        else:
                            print(f"  -> Blinkit attempt {attempt+1}: no ADD element found for '{clean_name}'")
                            if attempt < 3:
                                await asyncio.sleep(1.5)
                    except Exception as ce:
                        print(f"  -> Blinkit attempt {attempt+1} error: {ce}")
                        await asyncio.sleep(1)
                
                if not clicked:
                    print(f"  -> Blinkit could not click ADD for '{clean_name}' qty {i+1}")
            
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
            results.append({"type": "cart_summary", "totals": {"item_total": cart_info.get('total', 0), "item_count": cart_info['count']}})
            print(f"[Blinkit Checkout] Cart verified via localStorage: {cart_info['count']} items ✅")
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
                # Final fallback: count stepper '+' buttons
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
            for i in range(item.quantity):
                clicked = False
                
                if item.name:
                    base_name = item.name.split('\n')[0].strip()
                    
                    for attempt in range(4):
                        try:
                            # Find the correct product card and get the Add button's screen coordinates
                            btn_info = await page.evaluate("""
                            (name) => {
                                const baseName = name.split('\\n')[0].toLowerCase();
                                const words = baseName.replace(/[^a-z0-9\\s]/g, ' ').split(/\\s+/)
                                    .filter(w => w.length > 2 && !/^(\\d+|kg|gm|g|ml|ltr|l|pack|pcs)$/.test(w))
                                    .slice(0, 2);
                                if (!words.length) return null;
                                
                                // Find all product cards that contain our words
                                const cards = Array.from(document.querySelectorAll('div, li, article'))
                                    .filter(e => {
                                        const txt = (e.innerText || '').toLowerCase();
                                        if (!words.every(w => txt.includes(w))) return false;
                                        const rect = e.getBoundingClientRect();
                                        // Must be a reasonably sized element (not the whole page)
                                        return rect.width > 50 && rect.width < 700 && rect.height > 50 && rect.height < 700;
                                    });
                                if (!cards.length) return {found: false, reason: 'no_card'};
                                
                                // Sort by smallest area to get most specific card
                                cards.sort((a, b) => {
                                    const ra = a.getBoundingClientRect();
                                    const rb = b.getBoundingClientRect();
                                    return (ra.width * ra.height) - (rb.width * rb.height);
                                });
                                
                                for (const card of cards.slice(0, 5)) {
                                    const addBtn = Array.from(card.querySelectorAll('button'))
                                        .find(b => (b.innerText || '').trim().toLowerCase() === 'add');
                                    if (addBtn) {
                                        addBtn.scrollIntoView({block: 'center', behavior: 'instant'});
                                        const r = addBtn.getBoundingClientRect();
                                        if (r.width === 0) return {found: false, reason: 'btn_zero_size'};
                                        return {found: true, x: r.x + r.width/2, y: r.y + r.height/2};
                                    }
                                }
                                return {found: false, reason: 'no_add_btn_in_card'};
                            }
                            """, base_name)
                            
                            if btn_info and btn_info.get('found'):
                                await asyncio.sleep(0.3)  # Let scroll settle
                                await page.mouse.click(btn_info['x'], btn_info['y'])
                                success_clicks += 1
                                clicked = True
                                print(f"  -> BB click attempt {attempt+1} for '{base_name}': clicked at ({btn_info['x']:.0f},{btn_info['y']:.0f}) ✅")
                                await asyncio.sleep(2.5)
                                break
                            else:
                                reason = btn_info.get('reason', 'unknown') if btn_info else 'null_result'
                                print(f"  -> BB attempt {attempt+1}: not found ({reason}) for '{base_name}'")
                                if attempt < 3:
                                    await page.evaluate("window.scrollTo(0, 0)")  # Scroll back to top and retry
                                    await asyncio.sleep(1)
                        except Exception as ce:
                            print(f"  -> BB attempt {attempt+1} error: {ce}")
                        await asyncio.sleep(1.5)
                
                if not clicked:
                    print(f"  -> BB could not click add for '{item.name}' qty {i+1}")
            
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
            steppers = await page.evaluate("""
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

