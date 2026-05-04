from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
from playwright.async_api import async_playwright, Playwright
from scrapers.stealth_helper import stealth_async

router = APIRouter()

class CheckoutItem(BaseModel):
    product_url: str
    quantity: int
    name: Optional[str] = None
    unit_price: Optional[float] = None

def _normalize_zepto_product_url(url: str) -> str:
    if not url:
        return url
    return (
        url.strip()
        .replace("https://www.zeptonow.com", "https://www.zepto.com")
        .replace("https://zeptonow.com", "https://www.zepto.com")
        .replace("http://www.zeptonow.com", "https://www.zepto.com")
        .replace("http://zeptonow.com", "https://www.zepto.com")
    )

import re
def parse_bill(text: str) -> dict:
    totals = {}
    if not text: return totals
    lines = [line.strip().lower() for line in text.split('\n') if line.strip()]

    def rupee_values(value: str) -> List[float]:
        matches = re.findall(r'(?:₹|rs\.?)\s*(\d+(?:\.\d+)?)', value, flags=re.I)
        return [float(m) for m in matches]

    label_re = re.compile(
        r'(item total|items total|mrp total|basket value|delivery charge|delivery fee|handling charge|handling fee|platform fee|surge|small cart|rain|to pay|grand total|total amount|total payable|amount payable)'
    )
    
    def get_price(idx, is_fee=False):
        values = []
        # First, try to find a price on the SAME line as the label
        line = lines[idx]
        same_line_values = rupee_values(line)
        if same_line_values:
            # For fees, if there's a 'FREE', it's 0.
            if is_fee and 'free' in line: return 0.0
            # Otherwise take the LAST value on the same line
            val = same_line_values[-1]
            if is_fee and val > 5000: pass # Ignore suspiciously large fee values
            else: return val

        # If not found on same line, look at subsequent lines
        for j in range(idx + 1, min(len(lines), idx + 4)):
            val = lines[j]
            if label_re.search(val): break # Stop if we hit another label
            
            if is_fee and 'free' in val: return 0.0
            
            found = rupee_values(val)
            if found:
                price = found[-1]
                if is_fee and price > 5000: continue # Skip large numbers for fees
                return price
        return None
        
    for i, line in enumerate(lines):
        if any(x in line for x in ['item total', 'items total', 'mrp total', 'basket value', 'subtotal']):
            if 'item_total' not in totals: totals['item_total'] = get_price(i)
        elif any(x in line for x in ['delivery charge', 'delivery fee', 'shipping', 'delivery']):
            if 'delivery_fee' not in totals: totals['delivery_fee'] = get_price(i, is_fee=True)
        elif any(x in line for x in ['handling charge', 'handling fee', 'platform fee', 'conveyance']):
            if 'handling_fee' not in totals: totals['handling_fee'] = get_price(i, is_fee=True)
        elif any(x in line for x in ['surge', 'small cart', 'rain', 'night']):
            if 'surge_fee' not in totals: totals['surge_fee'] = get_price(i, is_fee=True)
        elif any(x in line for x in ['to pay', 'grand total', 'total amount', 'total payable', 'amount payable', 'bill total']):
            if 'total_payable' not in totals: totals['total_payable'] = get_price(i)

    # Blinkit format fallback: "N item ₹XX"
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

ZEPTO_STEPPER_STATE_JS = r"""
({name, targetX, targetY}) => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const headerHeight = 80;
    const words = name
        ? name.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter(w => w.length > 3).slice(0, 2)
        : [];

    const directText = (el) => Array.from(el.childNodes || [])
        .filter(n => n.nodeType === 3)
        .map(n => (n.textContent || '').trim())
        .join('')
        .trim();
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
            r.x < vw && r.right > 0 && r.y < vh && r.bottom > headerHeight;
    };
    const textOf = (el) => ((el.innerText || el.textContent || '').trim());
    const isPlus = (el) => {
        const t = textOf(el);
        const dt = directText(el);
        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
        const title = (el.getAttribute('title') || '').toLowerCase();
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        return t === '+' || dt === '+' ||
            aria.includes('increase') || aria.includes('increment') || aria.includes('add more') ||
            title.includes('increase') || title.includes('plus') ||
            cls.includes('increase') || cls.includes('plus');
    };
    const isMinus = (el) => {
        const t = textOf(el);
        const dt = directText(el);
        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
        const title = (el.getAttribute('title') || '').toLowerCase();
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        return t === '-' || t === '−' || dt === '-' || dt === '−' ||
            aria.includes('decrease') || aria.includes('remove') ||
            title.includes('decrease') || title.includes('minus') ||
            cls.includes('decrease') || cls.includes('minus');
    };
    const quantityFrom = (el) => {
        const t = directText(el);
        if (/^[1-9]\d*$/.test(t)) return parseInt(t, 10);
        return null;
    };

    const candidates = [];
    const qtyEls = Array.from(document.querySelectorAll('button, div, span, [role="button"]'))
        .filter(visible)
        .map(el => ({el, qty: quantityFrom(el)}))
        .filter(x => x.qty !== null && x.qty <= 99);

    for (const {el: qtyEl, qty} of qtyEls) {
        let container = qtyEl.parentElement;
        for (let depth = 0; depth < 7 && container; depth++, container = container.parentElement) {
            if (!visible(container)) continue;
            const cr = container.getBoundingClientRect();
            if (cr.width < 45 || cr.width > 240 || cr.height < 28 || cr.height > 110) continue;

            const controls = Array.from(container.querySelectorAll('button, div, span, [role="button"]')).filter(visible);
            const plusEl = controls.find(isPlus);
            const minusEl = controls.find(isMinus);
            const text = textOf(container);
            if (text.includes('₹')) continue;
            const looksLikeStepper = plusEl || minusEl || /^[\s\d+\-−]+$/.test(text);
            if (!looksLikeStepper) continue;

            let productMatch = false;
            let ancestor = container;
            for (let d = 0; d < 14 && ancestor; d++, ancestor = ancestor.parentElement) {
                const ancestorText = (ancestor.innerText || '').toLowerCase();
                if (words.length && words.every(w => ancestorText.includes(w))) {
                    productMatch = true;
                    break;
                }
            }

            let plusX;
            let plusY;
            let via = 'stepper-edge';
            if (plusEl) {
                const pr = plusEl.getBoundingClientRect();
                plusX = pr.x + pr.width / 2;
                plusY = pr.y + pr.height / 2;
                via = 'plus-element';
            } else {
                plusX = cr.right - Math.min(24, Math.max(12, cr.width * 0.18));
                plusY = cr.y + cr.height / 2;
            }

            const centerX = cr.x + cr.width / 2;
            const centerY = cr.y + cr.height / 2;
            const distance = Math.abs(centerY - targetY) + Math.abs(centerX - targetX) * 0.25;
            candidates.push({
                quantity: qty,
                plusX,
                plusY,
                centerX,
                centerY,
                productMatch,
                distance,
                area: cr.width * cr.height,
                via,
            });
            break;
        }
    }

    if (!candidates.length) return null;
    candidates.sort((a, b) =>
        Number(b.productMatch) - Number(a.productMatch) ||
        a.distance - b.distance ||
        a.area - b.area
    );
    return candidates[0];
}
"""

ZEPTO_CART_ROW_STATE_JS = r"""
({name}) => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const unitWords = new Set(['g', 'gm', 'kg', 'ml', 'l', 'ltr', 'pack', 'packs', 'piece', 'pieces', 'pc', 'pcs']);
    const words = name
        ? name.toLowerCase()
            .replace(/[^a-z0-9 ]/g, ' ')
            .split(/\s+/)
            .filter(w => w.length > 2 && !/^\d+$/.test(w) && !unitWords.has(w))
            .slice(0, 3)
        : [];

    const directText = (el) => Array.from(el.childNodes || [])
        .filter(n => n.nodeType === 3)
        .map(n => (n.textContent || '').trim())
        .join('')
        .trim();
    const textOf = (el) => ((el.innerText || el.textContent || '').trim());
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
            r.x < vw && r.right > 0 && r.y < vh && r.bottom > 0;
    };
    const isPlus = (el) => {
        const t = textOf(el);
        const dt = directText(el);
        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
        const title = (el.getAttribute('title') || '').toLowerCase();
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        return t === '+' || dt === '+' ||
            aria.includes('increase') || aria.includes('increment') || aria.includes('add more') ||
            title.includes('increase') || title.includes('plus') ||
            cls.includes('increase') || cls.includes('plus');
    };
    const isMinus = (el) => {
        const t = textOf(el);
        const dt = directText(el);
        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
        const title = (el.getAttribute('title') || '').toLowerCase();
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        return t === '-' || t === '−' || dt === '-' || dt === '−' ||
            aria.includes('decrease') || aria.includes('remove') ||
            title.includes('decrease') || title.includes('minus') ||
            cls.includes('decrease') || cls.includes('minus');
    };
    const quantityFrom = (el) => {
        const t = directText(el);
        if (/^[1-9]\d*$/.test(t)) return parseInt(t, 10);
        return null;
    };
    const wordMatch = (text) => words.length > 0 && words.every(w => text.includes(w));
    const bodyText = (document.body.innerText || '').toLowerCase();
    const cartContext = bodyText.includes('item total') ||
        bodyText.includes('items total') ||
        bodyText.includes('proceed to pay') ||
        bodyText.includes('checkout');

    const candidates = [];
    const qtyEls = Array.from(document.querySelectorAll('button, div, span, [role="button"]'))
        .filter(visible)
        .map(el => ({el, qty: quantityFrom(el)}))
        .filter(x => x.qty !== null && x.qty <= 99);

    for (const {el: qtyEl, qty} of qtyEls) {
        let stepper = qtyEl.parentElement;
        for (let depth = 0; depth < 7 && stepper; depth++, stepper = stepper.parentElement) {
            if (!visible(stepper)) continue;
            const sr = stepper.getBoundingClientRect();
            if (sr.width < 45 || sr.width > 260 || sr.height < 28 || sr.height > 120) continue;

            const controls = Array.from(stepper.querySelectorAll('button, div, span, [role="button"]')).filter(visible);
            const plusEl = controls.find(isPlus);
            const minusEl = controls.find(isMinus);
            if (!plusEl && !minusEl && !/^[\s\d+\-−]+$/.test(textOf(stepper))) continue;

            let row = stepper;
            for (let rowDepth = 0; rowDepth < 12 && row; rowDepth++, row = row.parentElement) {
                if (!visible(row)) continue;
                const rowText = textOf(row).toLowerCase();
                if (!wordMatch(rowText)) continue;

                const rr = row.getBoundingClientRect();
                const rowTooLarge = rr.height > Math.min(vh * 0.7, 520) || rr.width > vw * 0.98;
                if (rowTooLarge && rowDepth > 4) continue;

                let plusX;
                let plusY;
                let via = 'cart-stepper-edge';
                if (plusEl) {
                    const pr = plusEl.getBoundingClientRect();
                    plusX = pr.x + pr.width / 2;
                    plusY = pr.y + pr.height / 2;
                    via = 'cart-plus-element';
                } else {
                    plusX = sr.right - Math.min(24, Math.max(12, sr.width * 0.18));
                    plusY = sr.y + sr.height / 2;
                }

                candidates.push({
                    quantity: qty,
                    plusX,
                    plusY,
                    centerX: sr.x + sr.width / 2,
                    centerY: sr.y + sr.height / 2,
                    rowHeight: rr.height,
                    rowArea: rr.width * rr.height,
                    via,
                });
                break;
            }
            break;
        }
    }

    if (!candidates.length && cartContext) {
        const rowCandidates = Array.from(document.querySelectorAll('div, li, article, section'))
            .filter(visible)
            .map(row => {
                const text = textOf(row);
                const lower = text.toLowerCase();
                const r = row.getBoundingClientRect();
                return {row, text, lower, height: r.height, area: r.width * r.height};
            })
            .filter(c =>
                c.height >= 40 &&
                c.height <= Math.min(vh * 0.5, 420) &&
                wordMatch(c.lower) &&
                !c.lower.includes('bill details') &&
                !c.lower.includes('grand total')
            )
            .sort((a, b) => a.area - b.area);

        if (rowCandidates.length) {
            const rowText = rowCandidates[0].text;
            const qtyMatch = rowText.match(/[−-]\s*([1-9]\d*)\s*\+/) ||
                rowText.match(/\bqty\s*([1-9]\d*)\b/i);
            return {
                quantity: qtyMatch ? parseInt(qtyMatch[1], 10) : 1,
                centerX: 0,
                centerY: 0,
                via: 'cart-row-text',
            };
        }
        return null;
    }
    candidates.sort((a, b) =>
        a.rowHeight - b.rowHeight ||
        a.rowArea - b.rowArea
    );
    return candidates[0];
}
"""

ZEPTO_OPEN_CART_JS = r"""
() => {
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
            r.right > 0 && r.bottom > 0 &&
            r.x < window.innerWidth && r.y < window.innerHeight;
    };
    const candidates = Array.from(document.querySelectorAll('button, a, div[role="button"], [aria-label]'))
        .filter(visible)
        .filter(el => {
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            if (
                aria.includes('add to cart') ||
                text === 'add to cart' ||
                text === 'add' ||
                text === '+'
            ) {
                return false;
            }
            return text === 'cart' ||
                /^cart\s*\d*/.test(text) ||
                text.includes('view cart') ||
                text.includes('go to cart') ||
                aria === 'cart';
        });
    candidates.sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        const aHeaderCart = (a.getAttribute('aria-label') || '').trim().toLowerCase() === 'cart' ? 0 : 1;
        const bHeaderCart = (b.getAttribute('aria-label') || '').trim().toLowerCase() === 'cart' ? 0 : 1;
        return aHeaderCart - bHeaderCart ||
            br.x - ar.x ||
            ar.y - br.y;
    });
    const target = candidates[0];
    if (!target) return false;
    target.click();
    return true;
}
"""

class CheckoutRequest(BaseModel):
    storage_state: Dict[str, Any]
    items: List[CheckoutItem]
    lat: Optional[float] = None
    lon: Optional[float] = None

async def _get_zepto_stepper_state(page, name: str, target_x: float = 0, target_y: float = 0):
    try:
        return await page.evaluate(
            ZEPTO_STEPPER_STATE_JS,
            {"name": name, "targetX": target_x, "targetY": target_y}
        )
    except Exception as e:
        print(f"[Zepto Checkout] Stepper read warning for '{name}': {e}")
        return None

async def _get_zepto_cart_row_state(page, name: str):
    try:
        return await page.evaluate(ZEPTO_CART_ROW_STATE_JS, {"name": name})
    except Exception as e:
        print(f"[Zepto Checkout] Cart row read warning for '{name}': {e}")
        return None

async def _open_zepto_cart(page) -> None:
    try:
        await page.goto("https://www.zepto.com/?cart=open", wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        print(f"[Zepto Checkout] Cart URL load warning (ignoring): {e}")
    await asyncio.sleep(2.5)

    try:
        body_text = (await page.evaluate("() => document.body.innerText.toLowerCase()")).lower()
        if "item total" in body_text or "items total" in body_text or "proceed to pay" in body_text:
            return
        clicked = await page.evaluate(ZEPTO_OPEN_CART_JS)
        if clicked:
            await asyncio.sleep(2)
    except Exception as e:
        print(f"[Zepto Checkout] Cart open click warning: {e}")

async def _click_zepto_control_at(page, x: float, y: float) -> bool:
    try:
        return bool(await page.evaluate(
            r"""
            ({x, y}) => {
                let el = document.elementFromPoint(x, y);
                for (let depth = 0; depth < 6 && el; depth++, el = el.parentElement) {
                    const text = (el.innerText || el.textContent || '').trim();
                    const aria = (el.getAttribute && (el.getAttribute('aria-label') || '').toLowerCase()) || '';
                    const role = (el.getAttribute && (el.getAttribute('role') || '').toLowerCase()) || '';
                    if (
                        el.tagName === 'BUTTON' ||
                        role === 'button' ||
                        text === '+' ||
                        aria.includes('increase') ||
                        aria.includes('increment')
                    ) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            {"x": x, "y": y}
        ))
    except Exception as e:
        print(f"[Zepto Checkout] DOM click warning at ({x}, {y}): {e}")
        return False

async def _ensure_zepto_location(page) -> None:
    """
    Zepto ignores cart mutations when the web session is still on Select Location.
    The browser context already has geolocation permission; this just drives the
    visible location prompt if Zepto asks for it.
    """
    try:
        header_text = (await page.evaluate("() => document.body.innerText.substring(0, 500)")).lower()
        if "select location" not in header_text and "use my location" not in header_text:
            return

        for sel in [
            "button:has-text('Select Location')",
            "text='Select Location'",
            "[aria-label*='location' i]",
        ]:
            try:
                loc = await page.query_selector(sel)
                if loc and await loc.is_visible():
                    await loc.click()
                    await asyncio.sleep(1.5)
                    break
            except:
                pass

        for sel in [
            "button:has-text('Use my location')",
            "button:has-text('Use Current Location')",
            "button:has-text('Detect my location')",
            "button:has-text('Allow')",
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    break
            except:
                pass
    except Exception as e:
        print(f"[Zepto Checkout] Location setup warning: {e}")

async def _raise_zepto_cart_quantity(page, name: str, target_qty: int, initial_state: Optional[dict] = None) -> int:
    """
    Zepto product pages sometimes stop accepting product-page + clicks one unit
    early, while the cart row still accepts increments. Reconcile on the cart
    page before reporting the final quantity.
    """
    target_x = 0
    target_y = 0
    actual_qty = 0
    stepper_state = initial_state
    no_progress_attempts = 0

    while no_progress_attempts < 8:
        if not stepper_state:
            stepper_state = await _get_zepto_cart_row_state(page, name)
            if not stepper_state:
                stepper_state = await _get_zepto_stepper_state(page, name, target_x, target_y)

        if not stepper_state or not stepper_state.get("quantity"):
            return actual_qty

        actual_qty = int(stepper_state["quantity"])
        target_x = stepper_state.get("centerX", target_x)
        target_y = stepper_state.get("centerY", target_y)
        if actual_qty >= target_qty:
            return actual_qty

        plus_x = stepper_state.get("plusX")
        plus_y = stepper_state.get("plusY")
        if plus_x is None or plus_y is None:
            return actual_qty

        await page.mouse.click(plus_x, plus_y)
        await asyncio.sleep(1.4)

        updated_state = await _get_zepto_cart_row_state(page, name)
        if not updated_state:
            updated_state = await _get_zepto_stepper_state(page, name, target_x, target_y)
        updated_qty = int(updated_state.get("quantity") or 0) if updated_state else 0
        if updated_state:
            target_x = updated_state.get("centerX", target_x)
            target_y = updated_state.get("centerY", target_y)

        if updated_qty > actual_qty:
            actual_qty = updated_qty
            stepper_state = updated_state
            no_progress_attempts = 0
            print(f"[Zepto Checkout] Cart + verified qty {actual_qty}/{target_qty} for '{name}' ✅")
        else:
            dom_clicked = await _click_zepto_control_at(page, plus_x, plus_y)
            if dom_clicked:
                await asyncio.sleep(1.4)
                updated_state = await _get_zepto_cart_row_state(page, name)
                if not updated_state:
                    updated_state = await _get_zepto_stepper_state(page, name, target_x, target_y)
                updated_qty = int(updated_state.get("quantity") or 0) if updated_state else 0
                if updated_qty > actual_qty:
                    actual_qty = updated_qty
                    stepper_state = updated_state
                    no_progress_attempts = 0
                    print(f"[Zepto Checkout] Cart DOM + verified qty {actual_qty}/{target_qty} for '{name}' ✅")
                    continue

            stepper_state = None
            no_progress_attempts += 1
            print(f"[Zepto Checkout] Cart + did not change qty ({actual_qty} → {updated_qty or 'unknown'}), retry {no_progress_attempts}/8")

    return actual_qty

async def _extract_blinkit_cart_rows(page, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        return await page.evaluate(
            r"""
            (items) => {
                const unitWords = new Set(['g', 'gm', 'kg', 'ml', 'l', 'ltr', 'pack', 'packs', 'piece', 'pieces', 'pc', 'pcs', 'new', 'crop']);
                const directText = (el) => Array.from(el.childNodes || [])
                    .filter(n => n.nodeType === 3)
                    .map(n => (n.textContent || '').trim())
                    .join(' ')
                    .trim();
                const textOf = (el) => ((el.innerText || el.textContent || '').trim());
                const clean = (text) => (text || '').replace(/[\n\r]/g, ' ').replace(/\s+/g, ' ').trim();
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0;
                };
                const isStruck = (el, stopAt) => {
                    let current = el;
                    while (current) {
                        const cls = (typeof current.className === 'string' ? current.className : '').toLowerCase();
                        const style = window.getComputedStyle(current);
                        if (
                            current.tagName === 'S' ||
                            current.tagName === 'DEL' ||
                            cls.includes('line-through') ||
                            cls.includes('strike') ||
                            style.textDecorationLine.includes('line-through')
                        ) return true;
                        if (current === stopAt) break;
                        current = current.parentElement;
                    }
                    return false;
                };
                const wordsFor = (name) => clean(name).toLowerCase()
                    .replace(/[^a-z0-9 ]/g, ' ')
                    .split(/\s+/)
                    .filter(w => w.length > 2 && !/^\d+$/.test(w) && !unitWords.has(w))
                    .slice(0, 3);
                const rupeesFrom = (text) => [...clean(text).matchAll(/₹\s*(\d+(?:\.\d+)?)/g)].map(m => parseFloat(m[1]));
                const quantityFrom = (row, fallbackQty) => {
                    const nums = Array.from(row.querySelectorAll('button, div, span, [role="button"]'))
                        .filter(visible)
                        .map(el => ({el, text: directText(el) || textOf(el)}))
                        .filter(x => /^[1-9]\d*$/.test(x.text.trim()))
                        .map(x => {
                            let parent = x.el.parentElement;
                            let stepper = false;
                            for (let d = 0; d < 4 && parent; d++, parent = parent.parentElement) {
                                const pt = textOf(parent);
                                if ((pt.includes('+') && (pt.includes('-') || pt.includes('−'))) || /[−-]\s*\d+\s*\+/.test(pt)) {
                                    stepper = true;
                                    break;
                                }
                            }
                            return {qty: parseInt(x.text.trim(), 10), stepper};
                        })
                        .filter(x => x.qty > 0 && x.qty < 100);
                    const stepperQty = nums.find(x => x.stepper);
                    if (stepperQty) return stepperQty.qty;
                    if (nums.length) return nums[0].qty;
                    return fallbackQty || 1;
                };
                const priceFrom = (row) => {
                    const candidates = [];
                    const priceEls = Array.from(row.querySelectorAll('div, span, p'))
                        .filter(el => visible(el) && /₹\s*\d/.test(textOf(el) || directText(el)));
                    for (const el of priceEls) {
                        const txt = directText(el) || textOf(el);
                        const lower = txt.toLowerCase();
                        for (const value of rupeesFrom(txt)) {
                            if (value <= 0 || value > 10000) continue;
                            candidates.push({
                                value,
                                struck: isStruck(el, row),
                                promo: lower.includes('saved') || lower.includes('save') || lower.includes('off') || lower.includes('coupon'),
                            });
                        }
                    }
                    const best = candidates.find(c => !c.struck && !c.promo) ||
                        candidates.find(c => !c.promo) ||
                        candidates[0];
                    if (best) return best.value;

                    const textValues = rupeesFrom(textOf(row));
                    return textValues.length ? textValues[0] : null;
                };

                return items.map(item => {
                    const words = wordsFor(item.name || '');
                    const fallbackQty = parseInt(item.target_qty || item.added_qty || 1, 10) || 1;
                    const candidates = Array.from(document.querySelectorAll('div, li, article, section'))
                        .filter(visible)
                        .map(el => {
                            const text = clean(textOf(el));
                            const lower = text.toLowerCase();
                            const r = el.getBoundingClientRect();
                            return {el, text, lower, area: r.width * r.height, height: r.height};
                        })
                        .filter(c => {
                            if (!c.text.includes('₹')) return false;
                            if (c.lower.includes('bill details') || c.lower.includes('grand total')) return false;
                            if (c.height < 45 || c.height > 360) return false;
                            return words.length > 0 && words.every(w => c.lower.includes(w));
                        })
                        .sort((a, b) => a.area - b.area);

                    const best = candidates[0];
                    if (!best) return null;
                    const unitPrice = priceFrom(best.el);
                    const quantity = quantityFrom(best.el, fallbackQty);
                    if (!unitPrice) return {name: item.name, quantity, text: best.text.slice(0, 240)};
                    return {
                        name: item.name,
                        quantity,
                        unit_price: unitPrice,
                        subtotal: Math.round(unitPrice * quantity * 100) / 100,
                        text: best.text.slice(0, 240),
                    };
                });
            }
            """,
            items,
        )
    except Exception as e:
        print(f"[Blinkit Checkout] Cart row extraction warning: {e}")
        return []

def _parse_blinkit_cart_rows_from_text(text: str, items: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    if not text:
        return [None for _ in items]

    unit_words = {
        "g", "gm", "kg", "ml", "l", "ltr", "pack", "packs", "piece", "pieces",
        "pc", "pcs", "new", "crop", "local", "tamatar", "aloo",
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lower_lines = [line.lower() for line in lines]

    def words_for(name: str) -> List[str]:
        return [
            w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
            if len(w) > 2 and not w.isdigit() and w not in unit_words
        ][:2]

    parsed_rows: List[Optional[Dict[str, Any]]] = []
    for item in items:
        words = words_for(item.get("name") or "")
        if not words:
            parsed_rows.append(None)
            continue

        row = None
        for idx, lower in enumerate(lower_lines):
            if not all(w in lower for w in words):
                continue

            window = " ".join(lines[idx: idx + 7])
            if "bill details" in window.lower():
                window = " ".join(lines[idx: idx + 4])

            prices = re.findall(r"₹\s*(\d+(?:\.\d+)?)", window)
            if not prices:
                continue

            qty_match = re.search(r"[−-]\s*([1-9]\d*)\s*\+", window)
            quantity = int(qty_match.group(1)) if qty_match else int(item.get("target_qty") or item.get("added_qty") or 1)
            unit_price = float(prices[0])
            row = {
                "name": item.get("name"),
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": round(unit_price * quantity, 2),
                "text": window[:240],
            }
            break

        parsed_rows.append(row)

    return parsed_rows

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
            results = await add_items_to_zepto_cart(p, request.storage_state, request.items, request.lat, request.lon)
        elif platform == "blinkit":
            results = await add_items_to_blinkit_cart(p, request.storage_state, request.items)
        elif platform == "bigbasket":
            results = await add_items_to_bigbasket_cart(p, request.storage_state, request.items)
        return {"success": True, "results": results}
    except Exception as e:
        print(f"Checkout Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def add_items_to_zepto_cart(
    p: Playwright,
    storage_state: dict,
    items: List[CheckoutItem],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
):
    lat = lat or 28.6139
    lon = lon or 77.2090

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
        storage_state=storage_state,
        geolocation={"latitude": lat, "longitude": lon},
        permissions=["geolocation"],
    )
    await stealth_async(context)
    
    page = await context.new_page()
    
    # Land on homepage first — cookies must be applied before navigating to products
    try:
        await page.goto("https://www.zepto.com", wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"[Zepto Checkout] Homepage load warning (ignoring): {e}")
    await asyncio.sleep(5)  # Wait for React to hydrate localStorage from cookies
    await _ensure_zepto_location(page)
    
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
        await _open_zepto_cart(page)
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
        product_url = _normalize_zepto_product_url(item.product_url)
        if not product_url or product_url == "https://www.zepto.com":
            results.append({"url": item.product_url, "status": "skipped", "reason": "No valid URL"})
            continue
            
        try:
            print(f"[Zepto Checkout] Navigating to {product_url}")
            try:
                await page.goto(product_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"[Zepto Checkout] Product page load warning (ignoring): {e}")
            await asyncio.sleep(3)  # Extra wait for JS to hydrate the product page
            await _ensure_zepto_location(page)
            
            # Scroll down to reveal Add button below sticky header
            await page.evaluate("window.scrollBy(0, 300)")
            await asyncio.sleep(1)
            
            # Dismiss any location / promo popups that may cover the Add button
            for popup_sel in [
                "button[aria-label='Location modal close Icon']",
                "button[aria-label='Close']",
                "button:has-text('Use my location')",
                "button:has-text('Use Current Location')",
                "button:has-text('Detect my location')",
                "button:has-text('Allow')",
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
            initial_stepper_state = None
            
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
                    return {x: r.x + r.width/2, y: r.y + r.height/2, width: r.width, height: r.height, found: 'main_button'};
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
                                return {x: r.x + r.width/2, y: r.y + r.height/2, width: r.width, height: r.height, found: 'name_match'};
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
                return {x: r.x + r.width/2, y: r.y + r.height/2, width: r.width, height: r.height, found: 'fallback_size'};
            }
            """, clean_name)

            if not add_coords:
                for selector in [
                    "button:has-text('Add To Cart')",
                    "button:has-text('Add to Cart')",
                    "button:has-text('ADD')",
                    "[role='button']:has-text('ADD')",
                    "[role='button']:has-text('Add')",
                ]:
                    try:
                        locator = page.locator(selector).first
                        if await locator.count() == 0:
                            continue
                        box = await locator.bounding_box()
                        if not box:
                            continue
                        cx = box["x"] + box["width"] / 2
                        cy = box["y"] + box["height"] / 2
                        if cx <= 0 or cy <= 100 or cx >= 1280 or cy >= 800:
                            continue
                        await locator.click(force=True, timeout=3000)
                        add_coords = {"x": cx, "y": cy, "width": box["width"], "height": box["height"], "found": f"locator:{selector}"}
                        print(f"[Zepto Checkout] ADD locator click [{selector}] at ({cx:.0f},{cy:.0f}) ✅")
                        await asyncio.sleep(1.5)
                        break
                    except Exception:
                        continue
            
            if add_coords:
                if not str(add_coords.get("found", "")).startswith("locator:"):
                    await asyncio.sleep(0.4)
                    await page.mouse.click(add_coords['x'], add_coords['y'])
                    print(f"[Zepto Checkout] ADD click [{add_coords['found']}] at ({add_coords['x']:.0f},{add_coords['y']:.0f}) ✅")
                    await asyncio.sleep(1.5)

                initial_stepper_state = await _get_zepto_stepper_state(
                    page,
                    clean_name,
                    add_coords['x'],
                    add_coords['y'],
                )
                if not initial_stepper_state:
                    dom_clicked = await _click_zepto_control_at(page, add_coords['x'], add_coords['y'])
                    if dom_clicked:
                        print("[Zepto Checkout] Retried ADD through DOM target")
                        await asyncio.sleep(1.5)
                        initial_stepper_state = await _get_zepto_stepper_state(
                            page,
                            clean_name,
                            add_coords['x'],
                            add_coords['y'],
                        )

                if initial_stepper_state and initial_stepper_state.get("quantity"):
                    success_clicks = int(initial_stepper_state["quantity"])
                    print(f"[Zepto Checkout] ADD verified visible qty {success_clicks} for '{clean_name}' ✅")
                else:
                    # Some Zepto layouts do not expose a numeric stepper on the
                    # product page. Final cart verification below will confirm
                    # whether the mutation persisted.
                    success_clicks = 1
                    print(f"[Zepto Checkout] ADD clicked for '{clean_name}', no product-page counter visible; will verify from cart")
                added = True
            else:
                print(f"[Zepto Checkout] WARNING: No ADD element found for {product_url}")
                success_clicks = 0

            # ─── PHASE 2: Click + until the visible stepper reaches target qty ────────
            # Zepto can render multiple nearby plus buttons. Trust the observed stepper
            # quantity, not the number of mouse clicks we attempted.
            if added:
                target_x = add_coords['x'] if add_coords else 0
                target_y = add_coords['y'] if add_coords else 0
                stepper_state = initial_stepper_state or await _get_zepto_stepper_state(page, clean_name, target_x, target_y)
                if stepper_state and stepper_state.get("quantity"):
                    success_clicks = int(stepper_state["quantity"])
                    target_x = stepper_state.get("centerX", target_x)
                    target_y = stepper_state.get("centerY", target_y)

                if not stepper_state and add_coords:
                    print("[Zepto Checkout] No numeric product-page stepper; trying product-page coordinate + fallback")
                    fallback_width = float(add_coords.get("width") or 440)
                    fallback_height = float(add_coords.get("height") or 48)
                    plus_x = min(1270, max(10, float(add_coords["x"]) + fallback_width * 0.44))
                    plus_y = min(790, max(110, float(add_coords["y"]) + fallback_height * 0.02))
                    fallback_attempts = 0
                    while success_clicks < item.quantity and fallback_attempts < max(0, item.quantity - success_clicks):
                        await page.mouse.click(plus_x, plus_y)
                        await asyncio.sleep(1.4)

                        updated_state = await _get_zepto_stepper_state(page, clean_name, add_coords["x"], add_coords["y"])
                        observed_qty = int(updated_state.get("quantity") or 0) if updated_state else 0
                        if observed_qty > success_clicks:
                            success_clicks = observed_qty
                            print(f"[Zepto Checkout] coordinate + verified qty {success_clicks}/{item.quantity} ✅")
                        else:
                            # Zepto's authenticated PDP sometimes hides the
                            # counter text from the DOM, but the right edge of
                            # the morphed ADD control still increments. Final
                            # cart verification below remains authoritative.
                            success_clicks += 1
                            print(f"[Zepto Checkout] coordinate + attempted qty {success_clicks}/{item.quantity}")
                        fallback_attempts += 1
                else:
                    no_progress_attempts = 0
                    while success_clicks < item.quantity and no_progress_attempts < 8:
                        stepper_state = await _get_zepto_stepper_state(page, clean_name, target_x, target_y)
                        if not stepper_state:
                            no_progress_attempts += 1
                            print(f"[Zepto Checkout] + stepper attempt {no_progress_attempts}: not found")
                            await asyncio.sleep(1)
                            continue

                        before_qty = int(stepper_state.get("quantity") or success_clicks)
                        target_x = stepper_state.get("centerX", target_x)
                        target_y = stepper_state.get("centerY", target_y)
                        plus_x = stepper_state.get("plusX")
                        plus_y = stepper_state.get("plusY")
                        if plus_x is None or plus_y is None:
                            no_progress_attempts += 1
                            print(f"[Zepto Checkout] + stepper attempt {no_progress_attempts}: no plus coordinate")
                            await asyncio.sleep(1)
                            continue

                        await page.mouse.click(plus_x, plus_y)
                        await asyncio.sleep(1.4)

                        updated_state = await _get_zepto_stepper_state(page, clean_name, target_x, target_y)
                        observed_qty = int(updated_state.get("quantity") or 0) if updated_state else 0
                        if updated_state:
                            target_x = updated_state.get("centerX", target_x)
                            target_y = updated_state.get("centerY", target_y)

                        if observed_qty > before_qty:
                            success_clicks = observed_qty
                            no_progress_attempts = 0
                            print(f"[Zepto Checkout] + verified qty {success_clicks}/{item.quantity} [{stepper_state.get('via', 'unknown')}] ✅")
                        else:
                            no_progress_attempts += 1
                            print(f"[Zepto Checkout] + click did not change qty ({before_qty} → {observed_qty or 'unknown'}), retry {no_progress_attempts}/8")

                    if success_clicks < item.quantity:
                        print(f"[Zepto Checkout] Could only verify {success_clicks}/{item.quantity} units for '{clean_name}'")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            print(f"[Zepto Checkout] '{item.name}': {success_clicks}/{item.quantity} → {status}")
            results.append({
                "url": item.product_url,
                "status": status,
                "added_qty": success_clicks,
                "target_qty": item.quantity,
                "name": item.name,
                "unit_price": item.unit_price,
            })
        except Exception as e:
            print(f"[Zepto Checkout] Failed to add item: {item.product_url} -> {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Navigate to cart and extract bill info
    success = any(r.get('status') in ['success', 'partial'] for r in results)
    try:
        await _open_zepto_cart(page)

        # Final guardrail: update added_qty from the cart page itself. This keeps
        # the comparison table honest if Zepto accepted a click visually but did
        # not persist the quantity.
        for r in results:
            if r.get("status") not in ["success", "partial"] or not r.get("name"):
                continue
            cart_state = await _get_zepto_cart_row_state(page, r["name"])
            if not cart_state:
                cart_state = await _get_zepto_stepper_state(page, r["name"], 0, 0)
            if not cart_state or not cart_state.get("quantity"):
                r["added_qty"] = 0
                r["status"] = "error"
                r["error"] = "Cart row not found after add."
                print(f"[Zepto Checkout] Cart row missing for '{r['name']}' after add; marking as error")
                continue

            actual_qty = int(cart_state["quantity"])
            target_qty = int(r.get("target_qty") or r.get("added_qty") or actual_qty)
            if actual_qty < target_qty:
                print(f"[Zepto Checkout] Cart has {actual_qty}/{target_qty} units for '{r['name']}', correcting in cart...")
                actual_qty = await _raise_zepto_cart_quantity(
                    page,
                    r["name"],
                    target_qty,
                    initial_state=cart_state,
                )

            if actual_qty != r.get("added_qty"):
                print(f"[Zepto Checkout] Cart verified '{r['name']}': {actual_qty}/{target_qty} units")

            r["added_qty"] = actual_qty
            r["status"] = "success" if actual_qty >= target_qty else "partial" if actual_qty > 0 else "error"

        success = any(r.get('status') in ['success', 'partial'] for r in results)
        
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
                            ({name, targetX, targetY}) => {
                                const vw = window.innerWidth;
                                const vh = window.innerHeight;
                                const headerHeight = 100;

                                // Find all potential stepper '+' buttons
                                const plusEls = Array.from(document.querySelectorAll('button, div, span, a, [role="button"]')).filter(e => {
                                    const text = (e.innerText || '').trim();
                                    const directText = Array.from(e.childNodes || [])
                                        .filter(n => n.nodeType === 3)
                                        .map(n => (n.textContent || '').trim())
                                        .join('');
                                    const aria = (e.getAttribute('aria-label') || '').toLowerCase();
                                    const title = (e.getAttribute('title') || '').toLowerCase();
                                    const testid = (e.getAttribute('data-testid') || '').toLowerCase();
                                    const cls = (typeof e.className === 'string' ? e.className : '').toLowerCase();
                                    return text === '+' ||
                                        directText === '+' ||
                                        aria.includes('increase') ||
                                        aria.includes('increment') ||
                                        aria.includes('add more') ||
                                        title.includes('increase') ||
                                        title.includes('plus') ||
                                        testid.includes('plus') ||
                                        testid.includes('increase') ||
                                        cls.includes('plus') ||
                                        cls.includes('increment');
                                }).filter(e => {
                                    const r = e.getBoundingClientRect();
                                    const cx = r.x + r.width/2;
                                    const cy = r.y + r.height/2;
                                    // Keep this tied to the row where we clicked ADD, but allow UI shifts after hydration.
                                    return cx > 0 && cx < vw && cy > headerHeight && cy < vh && Math.abs(cy - targetY) < 90;
                                });
                                
                                const words = name ? name.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w => w.length > 3).slice(0,2) : [];

                                if (plusEls.length && words.length) {
                                    for (const el of plusEls) {
                                        let parent = el.parentElement;
                                        for (let d = 0; d < 12 && parent; d++) {
                                            const txt = (parent.innerText || '').toLowerCase();
                                            if (words.every(w => txt.includes(w))) {
                                                el.scrollIntoView({block:'center',behavior:'instant'});
                                                const r = el.getBoundingClientRect();
                                                return {x: r.x + r.width/2, y: r.y + r.height/2, via:'name'};
                                            }
                                            parent = parent.parentElement;
                                        }
                                    }
                                }
                                
                                if (plusEls.length) {
                                    // Priority 2: Closest to the original ADD click.
                                    plusEls.sort((a,b) => {
                                        const ra = a.getBoundingClientRect();
                                        const rb = b.getBoundingClientRect();
                                        const da = Math.abs((ra.y+ra.height/2) - targetY) + Math.abs((ra.x+ra.width/2) - targetX) * 0.25;
                                        const db = Math.abs((rb.y+rb.height/2) - targetY) + Math.abs((rb.x+rb.width/2) - targetX) * 0.25;
                                        return da - db;
                                    });
                                    
                                    plusEls[0].scrollIntoView({block:'center',behavior:'instant'});
                                    const r = plusEls[0].getBoundingClientRect();
                                    return {x: r.x + r.width/2, y: r.y + r.height/2, via:'proximity'};
                                }

                                // Blinkit often renders the plus as an SVG-only target with no label/text.
                                // After ADD morphs to a stepper, the plus sits just to the right of the ADD center.
                                const fallbackX = Math.min(vw - 16, Math.max(16, targetX + 34));
                                const fallbackY = Math.min(vh - 16, Math.max(headerHeight + 16, targetY));
                                const el = document.elementFromPoint(fallbackX, fallbackY);
                                if (el) {
                                    let parent = el;
                                    for (let d = 0; d < 8 && parent; d++) {
                                        const txt = (parent.innerText || '').toLowerCase();
                                        if (!words.length || words.some(w => txt.includes(w)) || txt.includes('+')) {
                                            return {x: fallbackX, y: fallbackY, via:'coordinate-fallback'};
                                        }
                                        parent = parent.parentElement;
                                    }
                                }
                                return null;
                            }
                            """, {"name": clean_name, "targetX": add_coords['x'], "targetY": add_coords['y']})
                            
                            if plus_coords:
                                await asyncio.sleep(0.3)
                                await page.mouse.click(plus_coords['x'], plus_coords['y'])
                                success_clicks += 1
                                plus_clicked = True
                                print(f"  -> Blinkit + click #{extra+2} for '{clean_name}' [{plus_coords.get('via','unknown')}]: ({plus_coords['x']:.0f},{plus_coords['y']:.0f}) ✅")
                                await asyncio.sleep(2.5)
                                break
                            else:
                                print(f"  -> Blinkit Phase2 attempt {attempt+1}: no + stepper found for '{clean_name}'")
                                await asyncio.sleep(1.5)
                        except Exception as ce:
                            print(f"  -> Blinkit Phase2 attempt {attempt+1} error: {ce}")
                            await asyncio.sleep(1)
                    
                    if not plus_clicked:
                        print(f"  -> Blinkit could not click + for '{clean_name}' unit {extra+2}")
            
            status = "success" if success_clicks == item.quantity else "partial" if success_clicks > 0 else "error"
            results.append({
                "url": item.product_url,
                "status": status,
                "added_qty": success_clicks,
                "target_qty": item.quantity,
                "name": item.name,
                "unit_price": item.unit_price,
            })
        except Exception as e:
            print(f"[Blinkit Checkout] Failed to add item: {str(e)}")
            results.append({"url": item.product_url, "status": "error", "error": str(e)})

    # Verify against the actual cart page first. Blinkit localStorage can lag or
    # contain estimate fields that do not match the visible checkout bill.
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

        try:
            await page.goto("https://blinkit.com/cart", wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"[Blinkit Checkout] Cart page load warning (ignoring): {e}")
        await asyncio.sleep(3)

        text = await page.evaluate("document.body.innerText")
        totals = parse_bill(text) or {}

        item_results = [r for r in results if r.get("status") in ["success", "partial"] and r.get("name")]
        cart_rows = await _extract_blinkit_cart_rows(page, item_results)
        text_rows = _parse_blinkit_cart_rows_from_text(text, item_results)
        cart_rows = [
            row if row else text_rows[idx] if idx < len(text_rows) else None
            for idx, row in enumerate(cart_rows or [])
        ]
        if len(cart_rows) < len(item_results):
            cart_rows.extend(text_rows[len(cart_rows):])
        row_total = 0.0
        row_count = 0

        for result, row in zip(item_results, cart_rows):
            if not row:
                continue
            quantity = int(row.get("quantity") or result.get("added_qty") or 0)
            if quantity > 0:
                result["added_qty"] = quantity
                row_count += quantity
            if row.get("unit_price") is not None:
                result["unit_price"] = round(float(row["unit_price"]), 2)
            if row.get("subtotal") is not None:
                result["subtotal"] = round(float(row["subtotal"]), 2)
                row_total += result["subtotal"]
            elif row.get("unit_price") is not None and quantity > 0:
                result["subtotal"] = round(float(row["unit_price"]) * quantity, 2)
                row_total += result["subtotal"]

            target_qty = int(result.get("target_qty") or result.get("added_qty") or quantity)
            result["status"] = "success" if quantity >= target_qty else "partial" if quantity > 0 else "error"
            print(f"[Blinkit Checkout] Cart row verified '{result.get('name')}': qty={quantity}, unit=₹{result.get('unit_price')}, subtotal=₹{result.get('subtotal')}")

        if totals.get("item_count") is None:
            totals["item_count"] = row_count or (cart_info or {}).get("count", 0)
        if (totals.get("item_total") is None or totals.get("item_total") == 0) and row_total > 0:
            totals["item_total"] = round(row_total, 2)
        elif totals.get("item_total") is None and cart_info and cart_info.get("total"):
            totals["item_total"] = cart_info["total"]

        has_verified_cart = bool(totals.get("item_count") or row_count or (cart_info and cart_info.get("count", 0) > 0))

        if has_verified_cart:
            full_cart = await page.evaluate("() => localStorage.getItem('cart')")
            results.append({"type": "cart_summary", "totals": totals, "cart_data": full_cart})
            print(f"[Blinkit Checkout] Cart verified via page/localStorage: {totals} ✅")

            updated_state = await context.storage_state()
            results.append({"type": "updated_storage_state", "state": updated_state})
            print("[Blinkit Checkout] Updated storageState captured for saving back to MongoDB ✅")

            async def keep_open_and_navigate():
                try:
                    print("[Blinkit Checkout] Navigated to blinkit.com/cart — browser open for user 🛒")
                    await asyncio.sleep(300)  # Keep open for 5 minutes
                except: pass
                finally:
                    try: await browser.close()
                    except: pass
            asyncio.create_task(keep_open_and_navigate())
            return results  # Return immediately — browser stays open in background

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
                            ({name, targetX, targetY}) => {
                                const vw = window.innerWidth;
                                const vh = window.innerHeight;
                                const words = name.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/)
                                    .filter(w => w.length > 2).slice(0, 2);
                                
                                const plusBtns = Array.from(document.querySelectorAll('button, div, span, [role="button"]'))
                                    .filter(e => {
                                        const t = (e.innerText || '').trim();
                                        const directText = Array.from(e.childNodes || [])
                                            .filter(n => n.nodeType === 3)
                                            .map(n => (n.textContent || '').trim())
                                            .join('');
                                        const aria = (e.getAttribute('aria-label') || '').toLowerCase();
                                        const title = (e.getAttribute('title') || '').toLowerCase();
                                        const testid = (e.getAttribute('data-testid') || '').toLowerCase();
                                        const cls = (typeof e.className === 'string' ? e.className : '').toLowerCase();
                                        return t === '+' ||
                                            directText === '+' ||
                                            aria.includes('increase') ||
                                            aria.includes('plus') ||
                                            title.includes('increase') ||
                                            title.includes('plus') ||
                                            testid.includes('increase') ||
                                            testid.includes('plus') ||
                                            cls.includes('increase') ||
                                            cls.includes('plus') ||
                                            cls.includes('qty');
                                    }).filter(e => {
                                        const r = e.getBoundingClientRect();
                                        const cx = r.x + r.width/2;
                                        const cy = r.y + r.height/2;
                                        return r.width > 0 && r.height > 0 &&
                                            cx > 0 && cx < vw && cy > 0 && cy < vh &&
                                            Math.abs(cy - targetY) < 120;
                                    });
                                
                                for (const btn of plusBtns) {
                                    let p = btn.parentElement;
                                    for (let d = 0; d < 12 && p; d++) {
                                        const txt = (p.innerText || '').toLowerCase();
                                        if (words.every(w => txt.includes(w))) {
                                            btn.scrollIntoView({block: 'center', behavior: 'instant'});
                                            const r = btn.getBoundingClientRect();
                                            return {x: r.x + r.width/2, y: r.y + r.height/2, via: 'name'};
                                        }
                                        p = p.parentElement;
                                    }
                                }

                                if (plusBtns.length) {
                                    plusBtns.sort((a,b) => {
                                        const ra = a.getBoundingClientRect();
                                        const rb = b.getBoundingClientRect();
                                        const da = Math.abs((ra.y+ra.height/2) - targetY) + Math.abs((ra.x+ra.width/2) - targetX) * 0.25;
                                        const db = Math.abs((rb.y+rb.height/2) - targetY) + Math.abs((rb.x+rb.width/2) - targetX) * 0.25;
                                        return da - db;
                                    });
                                    plusBtns[0].scrollIntoView({block: 'center', behavior: 'instant'});
                                    const r = plusBtns[0].getBoundingClientRect();
                                    return {x: r.x + r.width/2, y: r.y + r.height/2, via: 'proximity'};
                                }

                                // Bigbasket sometimes paints the quantity control as icon-only.
                                // Fallback to the right side of the stepper that replaced ADD.
                                const fallbackX = Math.min(vw - 16, Math.max(16, targetX + 34));
                                const fallbackY = Math.min(vh - 16, Math.max(16, targetY));
                                const el = document.elementFromPoint(fallbackX, fallbackY);
                                if (el) return {x: fallbackX, y: fallbackY, via: 'coordinate-fallback'};
                                return null;
                            }
                            """, {"name": base_name, "targetX": add_coords['x'], "targetY": add_coords['y']})
                            
                            if plus_coords:
                                await asyncio.sleep(0.3)
                                await page.mouse.click(plus_coords['x'], plus_coords['y'])
                                success_clicks += 1
                                plus_clicked = True
                                print(f"  -> BB + click #{extra+2} for '{base_name}' [{plus_coords.get('via','unknown')}]: ({plus_coords['x']:.0f},{plus_coords['y']:.0f}) ✅")
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
            results.append({
                "url": item.product_url, 
                "status": status, 
                "added_qty": success_clicks,
                "target_qty": item.quantity,
                "name": item.name,
                "unit_price": item.unit_price,
            })
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
