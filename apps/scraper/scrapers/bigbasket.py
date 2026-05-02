"""
Bigbasket Real-Time Scraper — Uses Playwright to fetch live prices from bigbasket.com
"""
import asyncio
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright
from playwright_stealth.stealth import stealth_async
from scrapers.stealth_helper import apply_stealth
from scrapers.utils import get_final_quantity, normalize_query_words, parse_pieces_from_name, get_requested_pieces

DEFAULT_LAT = 28.6139
DEFAULT_LON = 77.2090

async def scrape_bigbasket(items, lat: Optional[float], lon: Optional[float], storage_state: Optional[Dict[str, Any]] = None):
    from routes.scrape import PlatformCart, PlatformItemResult

    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    result_items = []
    item_total = 0.0
    delivery_fee = 35.0  # Bigbasket standard delivery fee
    handling_fee = 5.0
    surge_fee = 0.0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, # Necessary to bypass BigBasket's Akamai bot protection consistently locally
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--window-position=0,0",
            ]
        )
        ctx_kwargs = dict(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
            print("[Bigbasket Scrape] Using authenticated session")
        context = await browser.new_context(**ctx_kwargs)
        await stealth_async(context)
        page = await context.new_page()
        await apply_stealth(page)

        try:
            print("[Bigbasket] Landing on homepage...")
            await page.goto("https://www.bigbasket.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[Bigbasket] Homepage load timeout/warning (ignoring): {e}")
            
        # Close any initial popups if present
        try:
            close_btn = await page.query_selector("button[class*='close'], .close-btn")
            if close_btn: await close_btn.click()
        except:
            pass

        for item in items:
            try:
                search_query = item.brand + " " + item.name if item.brand else item.name
                print(f"[Bigbasket] Searching for: {search_query}")
                try:
                    await page.goto(f"https://www.bigbasket.com/ps/?q={search_query.replace(' ', '+')}&nc=as", wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    print(f"[Bigbasket] Search page load warning (ignoring): {e}")
                await asyncio.sleep(3)
                
                # BigBasket Search Bar placeholder is specifically "Search for Products..."
                # Use strict desktop container or force click to avoid interception by hidden mobile headers
                search_input = await page.wait_for_selector("input[placeholder*='Search for Products']", state="visible", timeout=12000)
                if not search_input:
                    raise Exception("Could not find search bar")
                
                # Clear and type
                await search_input.click(force=True)
                await search_input.fill("")
                await search_input.type(search_query, delay=100)
                await asyncio.sleep(4) # Wait for autocomplete dropdown

                # Try to extract from autocomplete dropdown first (faster, avoids page load blocks)
                product = await _extract_from_autocomplete(page, item)
                
                # If autocomplete fails, press Enter and try the main results page
                if not product:
                    print("[Bigbasket] Autocomplete failed, hitting Enter...")
                    await search_input.press("Enter")
                    await asyncio.sleep(6)
                    product = await _extract_from_page(page, item)

                if product:
                    unit_price = product["price"]
                    
                    adjusted_qty = get_final_quantity(item, product["name"])
                    
                    subtotal = unit_price * adjusted_qty
                    item_total += subtotal

                    result_items.append(PlatformItemResult(
                        platform="bigbasket",
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
                    print(f"[Bigbasket] {item.name} not found.")
                    result_items.append(PlatformItemResult(
                        platform="bigbasket",
                        item_name=item.name,
                        matched_product_name="Not found on Bigbasket",
                        available=False,
                        unit_price=0.0,
                        quantity=item.quantity,
                        subtotal=0.0
                    ))
            except Exception as e:
                print(f"[Bigbasket] Error scraping {item.name}: {e}")
                result_items.append(PlatformItemResult(
                    platform="bigbasket",
                    item_name=item.name,
                    matched_product_name="Error fetching",
                    available=False,
                    unit_price=0.0,
                    quantity=item.quantity,
                    subtotal=0.0
                ))

        await browser.close()

    all_available = all(i.available for i in result_items)
    if item_total > 500: delivery_fee = 0.0
    total = item_total + delivery_fee + handling_fee + surge_fee

    return PlatformCart(
        platform="bigbasket",
        platform_display="Bigbasket",
        color="#84C225",
        items=result_items,
        item_total=round(item_total, 2),
        delivery_fee=delivery_fee,
        handling_fee=handling_fee,
        surge_fee=surge_fee,
        total_payable=round(total, 2),
        estimated_delivery_min=20,
        all_items_available=all_available
    )


async def _extract_from_autocomplete(page, item) -> Optional[dict]:
    search_query = item.brand + " " + item.name if item.brand else item.name
    query_words = normalize_query_words(search_query)
    products = await page.evaluate("""
        (queryWords) => {
            const results = [];
            // Target the autocomplete dropdown container
            const dropdowns = Array.from(document.querySelectorAll('ul, div[class*="autocomplete"], div[class*="dropdown"]'));
            if (!dropdowns.length) return [];
            
            const activeDropdown = dropdowns.find(d => d.innerText.includes('₹') || d.innerText.toLowerCase().includes('rs'));
            if (!activeDropdown) return [];

            const priceCandidates = Array.from(activeDropdown.querySelectorAll('span, div, p')).filter(el => {
                const txt = (el.innerText || "").trim().toLowerCase();
                return (txt.includes('₹') || txt.includes('rs')) && 
                       el.children.length === 0 &&
                       !txt.includes('save') && 
                       !txt.includes('off') && 
                       !txt.includes('mrp');
            });

            for (const pEl of priceCandidates) {
                let cleanText = pEl.innerText.replace('₹', '').replace(/rs\\.?/i, '').trim();
                const priceMatch = cleanText.match(/\\d+(\\.\\d+)?/);
                if (!priceMatch) continue;
                const price = parseFloat(priceMatch[0]);
                
                let current = pEl;
                let foundName = null;
                let foundImage = null;
                let foundUrl = null;
                let searchSteps = 0;
                
                while (current && searchSteps < 6) {
                    if (!foundName) {
                        const texts = Array.from(current.querySelectorAll('span, div, p, h3'))
                            .map(el => (el.innerText || "").trim())
                            .filter(t => t.length > 3 && !t.includes('₹') && !t.toLowerCase().includes('rs'));
                        
                        for (const t of texts) {
                            if (queryWords.some(w => t.toLowerCase().includes(w))) {
                                foundName = t; break;
                            }
                        }
                    }
                    if (!foundImage) {
                        const img = current.querySelector('img');
                        if (img && img.src && !img.src.includes('data:image')) foundImage = img.src;
                    }
                    if (!foundUrl) {
                        const a = current.closest('a');
                        if (a && a.href) foundUrl = a.href;
                    }
                    if (foundName && price) break;
                    current = current.parentElement;
                    searchSteps++;
                }
                if (foundName && price) {
                    let foundWeight = null;
                    const weightRegex = /(\\d+(?:\\.\\d+)?\\s*(?:g|kg|ml|l|gm|ltr|pcs|pc|pieces|units|pack))/gi;
                    const finalCandidates = Array.from(current.querySelectorAll('div, span, p'))
                        .map(el => (el.innerText || "").trim());
                    
                    let allWeights = [];
                    for (const cand of finalCandidates) {
                        const matches = [...cand.matchAll(weightRegex)];
                        for (const m of matches) {
                            if (!allWeights.includes(m[1].trim().toLowerCase())) {
                                allWeights.push(m[1].trim().toLowerCase());
                            }
                        }
                    }
                    if (allWeights.length > 0) {
                        foundWeight = allWeights.join(' ');
                        const nameNoSpace = foundName.toLowerCase().replace(/\\s/g, '');
                        for (const w of allWeights) {
                            const weightNoSpace = w.replace(/\\s/g, '');
                            if (!nameNoSpace.includes(weightNoSpace)) {
                                foundName = foundName + ' ' + w;
                            }
                        }
                    }
                    
                    results.push({ name: foundName, price, url: foundUrl, image_url: foundImage });
                }
            }
            return results;
        }
    """, query_words)
    return _score_and_pick(products, query_words, item)

async def _extract_from_page(page, item) -> Optional[dict]:
    search_query = item.brand + " " + item.name if item.brand else item.name
    query_words = normalize_query_words(search_query)
    products = await page.evaluate("""
        (queryWords) => {
            const results = [];
            const priceCandidates = Array.from(document.querySelectorAll('span, div, p')).filter(el => {
                const txt = (el.innerText || "").trim().toLowerCase();
                return (txt.includes('₹') || txt.includes('rs')) && 
                       el.children.length === 0 &&
                       !txt.includes('save') && 
                       !txt.includes('off') &&
                       !txt.includes('mrp');
            });

            for (const pEl of priceCandidates) {
                let cleanText = pEl.innerText.replace('₹', '').replace(/rs\\.?/i, '').trim();
                const priceMatch = cleanText.match(/\\d+(\\.\\d+)?/);
                if (!priceMatch) continue;
                const price = parseFloat(priceMatch[0]);
                
                let current = pEl;
                let foundName = null;
                let foundImage = null;
                let foundUrl = null;
                let searchSteps = 0;
                   while (current && searchSteps < 8) {
                    if (!foundName) {
                        const texts = Array.from(current.querySelectorAll('h3, span, div, p'))
                            .map(el => (el.innerText || "").trim())
                            .filter(t => t.length > 3 && t.length < 150 && !t.includes('₹') && !t.toLowerCase().includes('rs'));
                        
                        for (const t of texts) {
                            if (queryWords.some(w => t.toLowerCase().includes(w))) {
                                foundName = t; break;
                            }
                        }
                    }
                    if (!foundUrl) {
                        const a = current.closest('a');
                        if (a && a.href && !a.href.includes('javascript:')) foundUrl = a.href;
                    }
                    
                    // Stop climbing once we have isolated the product card (name + price)
                    if (foundName && price) {
                        // Extract image strictly from this card to prevent stealing ad images
                        const img = current.querySelector('img');
                        if (img) {
                            // Try to get high-res from srcset if lazy-loaded
                            if (img.srcset) {
                                const srcset = img.srcset.split(',')[0].trim().split(' ')[0];
                                if (srcset && !srcset.includes('data:image')) {
                                    foundImage = srcset;
                                }
                            }
                            if (!foundImage) foundImage = img.src;
                        }
                        break;
                    }
                    
                    current = current.parentElement;
                    searchSteps++;
                }
                if (foundName && price) {
                    let foundWeight = null;
                    const weightRegex = /(\\d+(?:\\.\\d+)?\\s*(?:g|kg|ml|l|gm|ltr|pcs|pc|pieces|units|pack))/gi;
                    const finalCandidates = Array.from(current.querySelectorAll('div, span, p'))
                        .map(el => (el.innerText || "").trim());
                        
                    let allWeights = [];
                    for (const cand of finalCandidates) {
                        const matches = [...cand.matchAll(weightRegex)];
                        for (const m of matches) {
                            if (!allWeights.includes(m[1].trim().toLowerCase())) {
                                allWeights.push(m[1].trim().toLowerCase());
                            }
                        }
                    }
                    if (allWeights.length > 0) {
                        foundWeight = allWeights.join(' ');
                        const nameNoSpace = foundName.toLowerCase().replace(/\\s/g, '');
                        for (const w of allWeights) {
                            const weightNoSpace = w.replace(/\\s/g, '');
                            if (!nameNoSpace.includes(weightNoSpace)) {
                                foundName = foundName + ' ' + w;
                            }
                        }
                    }
                    
                    results.push({ name: foundName, price, url: foundUrl, image_url: foundImage });
                }
            }
            return results;
        }
    """, query_words)
    return _score_and_pick(products, query_words, item)

def _score_and_pick(products, query_words, item):
    if not products: return None

    # ── Reject processed/snack products when looking for fresh produce ─────────
    # e.g. avoid matching "Fun Flips Potato Chips" when searching for "potato"
    PRODUCE_TERMS = {"tomato", "potato", "onion", "garlic", "ginger", "lemon", "lime",
                     "carrot", "cabbage", "spinach", "coriander", "cucumber", "brinjal",
                     "capsicum", "peas", "beans", "radish", "beetroot", "cauliflower"}
    PROCESSED_TERMS = {"chips", "crisps", "wafers", "biscuit", "cookie", "namkeen",
                       "snack", "fries", "processed", "instant", "nugget", "masala mix",
                       "pickle", "sauce", "ketchup", "puree", "paste", "powder", "juice"}
    is_produce_query = any(qw in PRODUCE_TERMS for qw in query_words)
    if is_produce_query and not item.brand:
        filtered = []
        for p in products:
            name_lower = p["name"].lower()
            if any(pt in name_lower for pt in PROCESSED_TERMS):
                print(f"[Bigbasket] Skipping processed product: {p['name']}")
                continue
            filtered.append(p)
        if filtered:  # Only apply filter if it doesn't wipe everything out
            products = filtered

    # Brand matching: if a brand is requested, prefer products that contain it
    if item.brand:
        brand_lower = item.brand.lower()
        brand_products = [p for p in products if brand_lower in p["name"].lower()]
        if brand_products:
            products = brand_products
        else:
            print(f"[Bigbasket] Brand '{item.brand}' not found, falling back to other brands.")
        
    unique = []
    seen = set()
    for r in products:
        k = r["name"].lower()
        if k not in seen:
            seen.add(k)
            unique.append(r)
            
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
        
    valid_products = [p for p in unique if sum(1 for w in query_words if w in p["name"].lower()) > 0]
    if not valid_products:
        print(f"[BigBasket] No products found containing query keywords: {query_words}")
        return None
    
    # If no brand is specified, pick the cheapest among the top-scoring products
    if not item.brand:
        top_score = score(max(valid_products, key=score))
        top_products = [p for p in valid_products if score(p) == top_score]
        best = min(top_products, key=lambda p: p["price"])
        if len(top_products) > 1:
            print(f"[BigBasket] No brand specified — picking cheapest among {len(top_products)} matches: {best['name']} @ ₹{best['price']}")
    else:
        best = max(valid_products, key=score)
    clean_name = " ".join(best["name"].split())[:60]
    return {
        "name": clean_name,
        "price": best["price"],
        "url": best.get("url"),
        "image_url": best.get("image_url")
    }
