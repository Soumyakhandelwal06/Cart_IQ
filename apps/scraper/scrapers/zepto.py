"""
Zepto Real-Time Scraper — Uses Playwright to fetch live prices from zeptonow.com
"""
import asyncio
import re
from typing import Optional
from playwright.async_api import async_playwright
from scrapers.stealth_helper import apply_stealth
from scrapers.utils import get_final_quantity, normalize_query_words, parse_pieces_from_name, get_requested_pieces

DEFAULT_LAT = 28.6139
DEFAULT_LON = 77.2090


async def scrape_zepto(items, lat: Optional[float], lon: Optional[float]):
    from routes.scrape import PlatformCart, PlatformItemResult

    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    result_items = []
    item_total = 0.0
    delivery_fee = 25.0
    handling_fee = 6.0
    surge_fee = 0.0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        await apply_stealth(page)

        # Land on Zepto first to set cookies & location
        try:
            await page.goto("https://www.zeptonow.com", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            # Dismiss any location popups
            for popup_sel in ["button:has-text('Allow')", "button:has-text('Use my location')", "[class*='close']"]:
                try:
                    btn = await page.query_selector(popup_sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(1)
                except:
                    pass
        except:
            pass

        for item in items:
            try:
                search_query = item.brand + " " + item.name if item.brand else item.name
                url = f"https://www.zeptonow.com/search?query={search_query.replace(' ', '%20')}"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                await asyncio.sleep(2)
                await page.screenshot(path="/tmp/zepto_debug.png", full_page=True)

                product = await _extract_first_product_zepto(page, item)

                if product:
                    unit_price = product["price"]
                    
                    adjusted_qty = get_final_quantity(item, product["name"])
                    
                    subtotal = unit_price * adjusted_qty
                    item_total += subtotal

                    result_items.append(PlatformItemResult(
                        platform="zepto",
                        item_name=item.name,
                        matched_product_name=product["name"],
                        available=True,
                        unit_price=round(unit_price, 2),
                        quantity=adjusted_qty,
                        subtotal=round(subtotal, 2),
                        product_url=product.get("url") or page.url,
                        image_url=product.get("image_url")
                    ))
                else:
                    result_items.append(PlatformItemResult(
                        platform="zepto",
                        item_name=item.name,
                        matched_product_name="Not found on Zepto",
                        available=False,
                        unit_price=0.0,
                        quantity=item.quantity,
                        subtotal=0.0
                    ))
            except Exception as e:
                print(f"[Zepto] Error scraping {item.name}: {e}")
                result_items.append(PlatformItemResult(
                    platform="zepto",
                    item_name=item.name,
                    matched_product_name="Error fetching",
                    available=False,
                    unit_price=0.0,
                    quantity=item.quantity,
                    subtotal=0.0
                ))

        await browser.close()

    # Zepto small order surge fee removed based on user app feedback

    all_available = all(i.available for i in result_items)
    total = item_total + delivery_fee + handling_fee + surge_fee

    return PlatformCart(
        platform="zepto",
        platform_display="Zepto",
        color="#8B5CF6",
        items=result_items,
        item_total=round(item_total, 2),
        delivery_fee=delivery_fee,
        handling_fee=handling_fee,
        surge_fee=surge_fee,
        total_payable=round(total, 2),
        estimated_delivery_min=8,
        all_items_available=all_available
    )


async def _extract_first_product_zepto(page, item) -> Optional[dict]:
    """
    Robust universal extractor: finds all price-looking strings and their
    associated product names by proximity in the DOM.
    """
    search_query = item.brand + " " + item.name if item.brand else item.name
    query_words = normalize_query_words(search_query)
    
    products = await page.evaluate("""
        (queryWords) => {
            const results = [];
            
            // Link-first approach: find all product card links (/pn/ URLs)
            // This guarantees the URL always belongs to the product we extract.
            const productLinks = Array.from(document.querySelectorAll('a[href*="/pn/"]'));
            const seen = new Set();
            
            for (const link of productLinks) {
                const url = link.href;
                if (!url || seen.has(url)) continue;
                
                // Get all text inside this product card
                const allText = Array.from(link.querySelectorAll('div, span, p, h1, h2, h3, h4'))
                    .map(el => (el.innerText || '').trim())
                    .filter(t => t.length > 0);
                
                // Find the product name: first text that matches any query word
                let foundName = null;
                for (const t of allText) {
                    if (t.length > 3 && t.length < 120 && !t.includes('₹') && 
                        queryWords.some(w => t.toLowerCase().includes(w))) {
                        foundName = t;
                        break;
                    }
                }
                if (!foundName) continue;
                
                // Find the price: first ₹N pattern in the card
                let price = null;
                for (const t of allText) {
                    const m = t.match(/₹\s*(\d+(?:\.\d+)?)/);
                    if (m) {
                        const p = parseFloat(m[1]);
                        if (p >= 1 && p <= 10000) { price = p; break; }
                    }
                }
                if (!price) continue;
                
                // Append weight info to name
                const weightRegex = /(\d+(?:\.\d+)?\s*(?:g|kg|ml|l|gm|ltr|pcs|pc|pieces|units|pack))/gi;
                const allWeights = [];
                for (const t of allText) {
                    const matches = [...t.matchAll(weightRegex)];
                    for (const m of matches) {
                        const w = m[1].trim().toLowerCase();
                        if (!allWeights.includes(w)) allWeights.push(w);
                    }
                }
                if (allWeights.length > 0) {
                    const nameNoSpace = foundName.toLowerCase().replace(/\s/g, '');
                    for (const w of allWeights) {
                        if (!nameNoSpace.includes(w.replace(/\s/g, ''))) {
                            foundName = foundName + ' ' + w;
                        }
                    }
                }
                
                // Find image
                const img = link.querySelector('img');
                const image_url = img ? img.src : null;
                
                seen.add(url);
                results.push({ name: foundName, price: price, url: url, image_url: image_url });
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
                print(f"[Zepto] Brand '{item.brand}' not found, falling back to other brands.")

        req_pieces = get_requested_pieces(item)
        
        def score(p):
            n = p["name"].lower()
            match_count = sum(1 for w in query_words if w in n)
            starts_with_bonus = 0.5 if any(n.startswith(w) for w in query_words) else 0
            
            piece_bonus = 0
            if req_pieces > 0:
                p_pieces = parse_pieces_from_name(p["name"])
                if p_pieces == req_pieces:
                    piece_bonus = 5.0
                    
            return match_count + starts_with_bonus + piece_bonus
        
        # Filter out products that have 0 matching keywords to avoid random garbage 
        # (like "Modelling Dough" when searching for "aloo")
        valid_products = [p for p in products if sum(1 for w in query_words if w in p["name"].lower()) > 0]
        
        if not valid_products:
            print(f"[Zepto] No products found containing query keywords: {query_words}")
            return None

        # If no brand is specified, pick the cheapest among the top-scoring products
        # (same relevance = same item, just different brands → pick min price)
        if not item.brand:
            top_score = score(max(valid_products, key=score))
            top_products = [p for p in valid_products if score(p) == top_score]
            best = min(top_products, key=lambda p: p["price"])
            if len(top_products) > 1:
                print(f"[Zepto] No brand specified — picking cheapest among {len(top_products)} matches: {best['name']} @ ₹{best['price']}")
        else:
            best = max(valid_products, key=score)
        return {
            "name": best["name"][:60],
            "price": best["price"],
            "url": best.get("url"),
            "image_url": best.get("image_url")
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
