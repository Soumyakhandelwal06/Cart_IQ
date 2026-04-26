from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
from playwright.async_api import async_playwright, Playwright

router = APIRouter()

class CheckoutItem(BaseModel):
    product_url: str
    quantity: int
    name: Optional[str] = None

CLICK_PRODUCT_BTN_JS = """
(name) => {
    try {
        const searchWords = name.toLowerCase().split(' ').filter(w => w.length > 2).slice(0, 4);
        const els = Array.from(document.querySelectorAll('div, p, span, h1, h2, h3, h4'))
            .filter(e => {
                const txt = (e.innerText || "").toLowerCase();
                return searchWords.every(w => txt.includes(w)) && e.children.length === 0;
            });
        if (els.length === 0) return 'not_found';
        
        let current = els[0];
        let steps = 0;
        while (current && steps < 15) {
            let plusBtn = Array.from(current.querySelectorAll('div, button, span, a'))
                .find(e => {
                    const t = (e.innerText || "").trim();
                    return t === '+' || t === 'Increase Quantity';
                });
            let addBtn = Array.from(current.querySelectorAll('div, button, span, a'))
                .find(e => {
                    const t = (e.innerText || "").trim();
                    return t === 'ADD' || t === 'Add' || t === 'Add to basket' || t === 'Add to Cart';
                });
            let btn = plusBtn || addBtn;
            if (btn) {
                btn.click();
                return 'clicked';
            }
            current = current.parentElement;
            steps++;
        }
        return 'no_button';
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
        headless=False,  # Visible browser for user observation
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    
    # Load user's saved session
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    
    page = await context.new_page()
    
    # Land on homepage first to ensure cookies are applied correctly
    await page.goto("https://www.zeptonow.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://www.zeptonow.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            print(f"[Zepto Checkout] Navigating to {item.product_url}")
            await page.goto(item.product_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            # Logic to add to cart
            # 1. Try to find the initial "Add" button
            add_btn_selectors = [
                "button:has-text('Add')",
                "button[aria-label='Add']",
                "button:has-text('Add to Cart')"
            ]
            
            added = False
            for sel in add_btn_selectors:
                try:
                    btn = await page.wait_for_selector(sel, state="visible", timeout=3000)
                    if btn:
                        await btn.click()
                        print(f"[Zepto Checkout] Clicked initial 'Add' button for {item.product_url}")
                        await asyncio.sleep(1)
                        added = True
                        break
                except:
                    continue
            
            # 2. If quantity > 1, or if it was already in cart, click the [+] button
            if item.quantity > 1 or not added:
                # If it wasn't added by the initial 'Add' button, it might already be in the cart.
                # The plus button selector in Zepto is typically an SVG or button with '+' or 'plus'
                plus_selectors = [
                    "button[aria-label='Increase Quantity']",
                    "button[aria-label='plus']",
                    "button:has-text('+')"
                ]
                
                clicks_needed = item.quantity - 1 if added else item.quantity
                
                for _ in range(clicks_needed):
                    clicked_plus = False
                    for p_sel in plus_selectors:
                        try:
                            p_btn = await page.query_selector(p_sel)
                            if p_btn and await p_btn.is_visible():
                                await p_btn.click()
                                await asyncio.sleep(0.5)
                                clicked_plus = True
                                break
                        except:
                            pass
                    
                    if not clicked_plus:
                        print(f"[Zepto Checkout] Could not find [+] button for {item.product_url}")
                        break
            
            results.append({"url": item.product_url, "status": "success", "added_qty": item.quantity})
        except Exception as e:
            print(f"[Zepto Checkout] Failed to add item: {item.product_url} -> {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Open cart page and leave browser open
    await page.goto("https://www.zeptonow.com/cart")
    
    return results

async def add_items_to_blinkit_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    page = await context.new_page()
    await page.goto("https://blinkit.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://blinkit.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            print(f"[Blinkit Checkout] Navigating to {item.product_url}")
            await page.goto(item.product_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            success_clicks = 0
            for i in range(item.quantity):
                if item.name:
                    res = await page.evaluate(CLICK_PRODUCT_BTN_JS, item.name)
                    print(f"  -> JS Click for '{item.name}': {res}")
                    if res == 'clicked':
                        success_clicks += 1
                        await asyncio.sleep(1)
                        continue
                        
                # Fallback if name fails or is empty
                fallback_selectors = ["text='+'", "text='ADD'", "div:text-is('ADD')", ".add-to-cart"]
                clicked_fallback = False
                for sel in fallback_selectors:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            try:
                                await btn.click(timeout=1000)
                            except:
                                await btn.click(force=True)
                            success_clicks += 1
                            clicked_fallback = True
                            await asyncio.sleep(1)
                            break
                    except:
                        pass
                if not clicked_fallback:
                    print(f"  -> Fallback also failed for iteration {i+1}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Blinkit Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Open cart page and leave browser open
    await page.goto("https://blinkit.com/cart")

    return results

async def add_items_to_bigbasket_cart(p: Playwright, storage_state: dict, items: List[CheckoutItem]):
    browser = await p.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        storage_state=storage_state
    )
    page = await context.new_page()
    await page.goto("https://www.bigbasket.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    results = []
    for item in items:
        if not item.product_url or item.product_url == "https://www.bigbasket.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            print(f"[Bigbasket Checkout] Navigating to {item.product_url}")
            await page.goto(item.product_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3) # Wait a bit longer for Bigbasket
            
            success_clicks = 0
            for i in range(item.quantity):
                if item.name:
                    res = await page.evaluate(CLICK_PRODUCT_BTN_JS, item.name)
                    print(f"  -> JS Click for '{item.name}': {res}")
                    if res == 'clicked':
                        success_clicks += 1
                        await asyncio.sleep(1.5)
                        continue
                        
                # Fallback
                fallback_selectors = ["text='+'", "button[title='Increase Quantity']", "button:text-is('Add to basket')", "button:text-is('Add')", "text='Add'"]
                clicked_fallback = False
                for sel in fallback_selectors:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            try:
                                await btn.click(timeout=1000)
                            except:
                                await btn.click(force=True)
                            success_clicks += 1
                            clicked_fallback = True
                            await asyncio.sleep(1)
                            break
                    except:
                        pass
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            results.append({"url": item.product_url, "status": status, "added_qty": success_clicks})
        except Exception as e:
            print(f"[Bigbasket Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Open cart page and leave browser open
    await page.goto("https://www.bigbasket.com/basket/?nc=nb")

    return results
