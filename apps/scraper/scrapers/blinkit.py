"""
Blinkit Real-Time Scraper — Uses Playwright to fetch live prices from blinkit.com
"""
import asyncio
import re
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright
from playwright_stealth.stealth import stealth_async
from scrapers.stealth_helper import apply_stealth
from scrapers.utils import get_final_quantity, normalize_query_words

DEFAULT_LAT = 28.6139  # New Delhi default
DEFAULT_LON = 77.2090


async def scrape_blinkit(items, lat: Optional[float], lon: Optional[float], storage_state: Optional[Dict[str, Any]] = None):
    from routes.scrape import PlatformCart, PlatformItemResult

    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    result_items = []
    item_total = 0.0
    delivery_fee = 29.0
    handling_fee = 9.0
    surge_fee = 0.0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        ctx_kwargs = dict(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
            print("[Blinkit Scrape] Using authenticated session")
        context = await browser.new_context(**ctx_kwargs)
        await stealth_async(context)
        page = await context.new_page()
        await apply_stealth(page)

        # Set location cookie first
        await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        for item in items:
            try:
                search_query = item.brand + " " + item.name if item.brand else item.name
                url = f"https://blinkit.com/s/?q={search_query.replace(' ', '+')}"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                await asyncio.sleep(2)

                # Try to get product data
                product = await _extract_first_product_blinkit(page, item)

                if product:
                    unit_price = product["price"]
                    
                    adjusted_qty = get_final_quantity(item, product["name"])
                    
                    subtotal = unit_price * adjusted_qty
                    item_total += subtotal

                    result_items.append(PlatformItemResult(
                        platform="blinkit",
                        item_name=item.name,
                        matched_product_name=product["name"],
                        available=True,
                        unit_price=round(unit_price, 2),
                        quantity=adjusted_qty,
                        subtotal=round(subtotal, 2),
                        product_url=product.get("url") or f"https://blinkit.com/s/?q={search_query.replace(' ', '+')}",
                        image_url=product.get("image_url")
                    ))
                else:
                    result_items.append(PlatformItemResult(
                        platform="blinkit",
                        item_name=item.name,
                        matched_product_name="Not found on Blinkit",
                        available=False,
                        unit_price=0.0,
                        quantity=item.quantity,
                        subtotal=0.0
                    ))
            except Exception as e:
                print(f"[Blinkit] Error scraping {item.name}: {e}")
                result_items.append(PlatformItemResult(
                    platform="blinkit",
                    item_name=item.name,
                    matched_product_name="Error fetching",
                    available=False,
                    unit_price=0.0,
                    quantity=item.quantity,
                    subtotal=0.0
                ))

        await browser.close()

    # Small cart surcharge
    if item_total < 199:
        handling_fee += 15.0

    all_available = all(i.available for i in result_items)
    total = item_total + delivery_fee + handling_fee + surge_fee

    return PlatformCart(
        platform="blinkit",
        platform_display="Blinkit",
        color="#F8C200",
        items=result_items,
        item_total=round(item_total, 2),
        delivery_fee=delivery_fee,
        handling_fee=handling_fee,
        surge_fee=surge_fee,
        total_payable=round(total, 2),
        estimated_delivery_min=10,
        all_items_available=all_available
    )


async def _extract_first_product_blinkit(page, item) -> Optional[dict]:
    """
    Robust universal extractor: finds all price-looking strings and their
    associated product names by proximity in the DOM.
    """
    import json
    search_query = item.brand + " " + item.name if item.brand else item.name
    query_words = normalize_query_words(search_query)
    
    # Use evaluate to find potential product cards based on common patterns
    # We pass query_words as an argument to avoid f-string curly brace issues
    products = await page.evaluate("""
        (queryWords) => {
            const results = [];
            
            // Find all elements containing ₹
            const allElements = Array.from(document.querySelectorAll('div, span, p, h1, h2, h3, h4'));
            const priceElements = allElements.filter(el => {
                const txt = el.innerText || "";
                return txt.includes('₹') && 
                       /₹\\s*\\d+/.test(txt) &&
                       el.children.length === 0 // Leaf node for price
            });
            
            for (const pEl of priceElements) {
                const priceText = pEl.innerText || "";
                const match = priceText.match(/₹\\s*(\\d+)/);
                if (!match) continue;
                const price = parseFloat(match[1]);
                if (price < 1 || price > 10000) continue;
                
                // For this price, find the nearest name (upwards or nearby in the DOM)
                let current = pEl;
                let foundName = null;
                let searchSteps = 0;
                
                while (current && searchSteps < 10) {
                    // Get all candidate text elements within this ancestor
                    const candidates = Array.from(current.querySelectorAll('div, span, p, h1, h2, h3, h4'))
                        .map(el => (el.innerText || "").trim())
                        .filter(t => t.length > 3 && t.length < 100 && !t.includes('₹') && !t.toLowerCase().includes('showing results'));
                        
                    for (const cand of candidates) {
                        const lowerCand = cand.toLowerCase();
                        if (queryWords.some(w => lowerCand.includes(w)) && !lowerCand.includes('safari')) {
                            foundName = cand;
                            break;
                        }
                    }
                    if (foundName) break;
                    
                    current = current.parentElement;
                    searchSteps++;
                }
                
                if (foundName && price) {
                    let foundWeight = null;
                    const weightRegex = /(\\d+(?:\\.\\d+)?\\s*(?:g|kg|ml|l|gm|ltr|pcs|pc|pieces|units|pack))/i;
                    const finalCandidates = Array.from(current.querySelectorAll('div, span, p'))
                        .map(el => (el.innerText || "").trim());
                    for (const cand of finalCandidates) {
                        const match = cand.match(weightRegex);
                        if (match) {
                            foundWeight = match[1].trim();
                            break;
                        }
                    }
                    if (foundWeight) {
                        const nameNoSpace = foundName.toLowerCase().replace(/\\s/g, '');
                        const weightNoSpace = foundWeight.toLowerCase().replace(/\\s/g, '');
                        if (!nameNoSpace.includes(weightNoSpace)) {
                            foundName = foundName.trim() + ' ' + foundWeight.trim();
                        }
                    }
                    // Normalize: remove all newlines and extra spaces from name
                    foundName = foundName.replace(/[\\n\\r]/g, ' ').replace(/\\s+/g, ' ').trim();
                    
                    // Try to find the product URL (nearest <a> tag with a product-style href)
                    let url = null;
                    let urlCurrent = pEl;
                    let urlSteps = 0;
                    while (urlCurrent && urlSteps < 15) {
                        if (urlCurrent.tagName === 'A' && urlCurrent.href && 
                            urlCurrent.href.includes('blinkit.com') &&
                            !urlCurrent.href.endsWith('/')) {
                            url = urlCurrent.href;
                            break;
                        }
                        const anchor = urlCurrent.querySelector('a[href]');
                        if (anchor && anchor.href && 
                            anchor.href.includes('blinkit.com') &&
                            !anchor.href.endsWith('/')) {
                            url = anchor.href;
                            break;
                        }
                        urlCurrent = urlCurrent.parentElement;
                        urlSteps++;
                    }
                    // Fallback: construct a focused search URL for this specific product name
                    if (!url && foundName) {
                        const searchTerms = foundName.split(' ').slice(0, 4).join('+');
                        url = 'https://blinkit.com/s/?q=' + encodeURIComponent(searchTerms);
                    }
                    // 3. Find image (Blinkit uses grofers/blinkit CDNs)
                    let foundImage = null;
                    const nameSnippet = foundName.split(' ')[0];
                    const img = current.querySelector(`img[src*="blinkit"], img[src*="grofers"], img[alt*="${nameSnippet}"]`);
                    if (img) foundImage = img.src;

                    results.push({ name: foundName, price: price, url: url, image_url: foundImage });
                }
            }
            return results;
        }
    """, query_words)

    if products and len(products) > 0:
        # Brand matching: if a brand is requested, prefer products that contain it
        if item.brand:
            brand_lower = item.brand.lower()
            brand_products = [p for p in products if brand_lower in p["name"].lower()]
            if brand_products:
                products = brand_products
            else:
                print(f"[Blinkit] Brand '{item.brand}' not found, falling back to other brands.")

        # Sort by relevance: name that has the most query words first
        def score(p):
            n = p["name"].lower()
            match_count = sum(1 for w in query_words if w in n)
            starts_with_bonus = 0.5 if any(n.startswith(w) for w in query_words) else 0
            return match_count + starts_with_bonus
            
        valid_products = [p for p in products if sum(1 for w in query_words if w in p["name"].lower()) > 0]
        
        if not valid_products:
            print(f"[Blinkit] No products found containing query keywords: {query_words}")
            return None
        
        # If no brand is specified, pick the cheapest among the top-scoring products
        # (same relevance = same item, just different brands → pick min price)
        if not item.brand:
            top_score = score(max(valid_products, key=score))
            top_products = [p for p in valid_products if score(p) == top_score]
            best = min(top_products, key=lambda p: p["price"])
            if len(top_products) > 1:
                print(f"[Blinkit] No brand specified — picking cheapest among {len(top_products)} matches: {best['name']} @ ₹{best['price']}")
        else:
            best = max(valid_products, key=score)
        # Sanitize name: remove newlines, collapse whitespace
        clean_name = " ".join(best["name"].replace("\n", " ").replace("\r", " ").split())[:60]
        # Sanitize URL: remove newline-encoded characters
        clean_url = best.get("url", "") or ""
        if "\n" in clean_url or "%0A" in clean_url or "%0a" in clean_url:
            clean_url = f"https://blinkit.com/s/?q={'+'.join(clean_name.split()[:4])}"
        return {
            "name": clean_name,
            "price": best["price"],
            "url": clean_url or None,
            "image_url": best.get("image_url"),
            "per_kg": "kg" in clean_name.lower() or "kg" in item.name.lower()
        }

    return None




def _parse_weight_kg(weight_str: str) -> float:
    if not weight_str:
        return 1.0
    weight_str = weight_str.lower().replace(" ", "")
    if "kg" in weight_str:
        return float(weight_str.replace("kg", ""))
    elif "g" in weight_str:
        return float(weight_str.replace("g", "")) / 1000
    return 1.0
