"""
Blinkit Real-Time Scraper — Uses Playwright to fetch live prices from blinkit.com
"""
import asyncio
import re
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright
from scrapers.stealth_helper import apply_stealth, stealth_async
from scrapers.utils import get_final_quantity, normalize_query_words

DEFAULT_LAT = 28.6139  # New Delhi default
DEFAULT_LON = 77.2090


async def scrape_blinkit(items, lat: Optional[float], lon: Optional[float], storage_state: Optional[Dict[str, Any]] = None):
    from routes.scrape import PlatformCart, PlatformItemResult

    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    result_items = []
    item_total = 0.0
    delivery_fee = 30.0
    handling_fee = 5.0
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
        try:
            await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[Blinkit] Homepage load timeout/warning (ignoring): {e}")

        for item in items:
            try:
                search_query = item.brand + " " + item.name if item.brand else item.name
                url = f"https://blinkit.com/s/?q={search_query.replace(' ', '+')}"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    print(f"[Blinkit] Search page load warning (ignoring): {e}")
                    
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
                        requested_quantity=item.quantity,
                        requested_weight=item.weight,
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
                        subtotal=0.0,
                        requested_quantity=item.quantity,
                        requested_weight=item.weight
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
                    subtotal=0.0,
                    requested_quantity=item.quantity,
                    requested_weight=item.weight
                ))

        await browser.close()

    # Small cart surcharge removed to align closer with actual app screenshots
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
    Extract product cards first, then read the visible selling price from that
    card. This avoids mixing Blinkit's offer badges, struck-through MRP, and
    adjacent cards into the displayed price.
    """
    search_query = item.brand + " " + item.name if item.brand else item.name
    query_words = normalize_query_words(search_query)
    
    products = await page.evaluate(r"""
        (queryWords) => {
            const results = [];
            const seenCards = new Set();

            const textOf = (el) => (el.innerText || el.textContent || '').trim();
            const directText = (el) => Array.from(el.childNodes || [])
                .filter(n => n.nodeType === 3)
                .map(n => (n.textContent || '').trim())
                .join(' ')
                .trim();
            const clean = (text) => (text || '').replace(/[\n\r]/g, ' ').replace(/\s+/g, ' ').trim();
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };
            const hasQueryWord = (text) => {
                const lower = text.toLowerCase();
                return queryWords.some(w => lower.includes(w));
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
                    ) {
                        return true;
                    }
                    if (current === stopAt) break;
                    current = current.parentElement;
                }
                return false;
            };

            const candidateCards = Array.from(document.querySelectorAll(
                'a[href*="/prn/"], a[href*="/pn/"], [role="button"][id], div[id="product_container"]'
            )).filter(visible);

            for (const card of candidateCards) {
                const cardText = textOf(card).toLowerCase();
                // Exclude Sponsored/Ad items which often have inflated prices
                if (cardText.includes('sponsored') || cardText.includes(' ad ') || cardText.includes('advertisement')) continue;
                
                if (!cardText.includes('₹') || !hasQueryWord(cardText)) continue;

                const cardKey = card.id || card.getAttribute('href') || clean(cardText).slice(0, 120);
                if (seenCards.has(cardKey)) continue;
                seenCards.add(cardKey);

                const textNodes = Array.from(card.querySelectorAll('div, span, p, h1, h2, h3, h4'))
                    .map(el => clean(directText(el) || textOf(el)))
                    .filter((t, idx, arr) => {
                        const lower = t.toLowerCase();
                        return t.length > 2 &&
                            t.length < 120 &&
                            arr.indexOf(t) === idx &&
                            !t.includes('₹') &&
                            !lower.includes('showing results') &&
                            !lower.includes('safari') &&
                            !lower.includes('mins') &&
                            !lower.includes('off') &&
                            !lower.includes('add') &&
                            !lower.includes('sponsored') &&
                            !/^\d+(?:\.\d+)?\s*%?$/.test(lower);
                    });

                let foundName = null;
                for (const cand of textNodes) {
                    if (hasQueryWord(cand)) {
                        foundName = cand;
                        break;
                    }
                }
                if (!foundName) continue;

                let foundWeight = null;
                const weightRegex = /(\d+(?:\.\d+)?\s*(?:g|kg|ml|l|gm|ltr|pcs|pc|pieces|units|pack))\b/i;
                for (const cand of textNodes) {
                    const match = cand.match(weightRegex);
                    if (match) {
                        foundWeight = match[1].trim();
                        break;
                    }
                }
                if (foundWeight) {
                    const nameNoSpace = foundName.toLowerCase().replace(/\s/g, '');
                    const weightNoSpace = foundWeight.toLowerCase().replace(/\s/g, '');
                    if (!nameNoSpace.includes(weightNoSpace)) {
                        foundName = `${foundName} ${foundWeight}`;
                    }
                }
                foundName = clean(foundName);

                const priceCandidates = [];
                const priceNodes = Array.from(card.querySelectorAll('div, span, p'))
                    .filter(el => /₹\s*\d+(?:\.\d+)?/.test(textOf(el) || directText(el)));

                for (const priceEl of priceNodes) {
                    const priceText = clean(directText(priceEl) || textOf(priceEl));
                    const lower = priceText.toLowerCase();
                    const matches = [...priceText.matchAll(/₹\s*(\d+(?:\.\d+)?)/g)];
                    for (const match of matches) {
                        const price = parseFloat(match[1]);
                        if (price < 1 || price > 10000) continue;
                        priceCandidates.push({
                            price,
                            struck: isStruck(priceEl, card),
                            promo: lower.includes('off') || lower.includes('save') || lower.includes('coupon') || lower.includes('discount'),
                        });
                    }
                }

                const selling = priceCandidates.find(p => !p.struck && !p.promo) ||
                    priceCandidates.find(p => !p.promo) ||
                    priceCandidates[0];
                if (!selling) continue;

                let url = null;
                const anchor = card.closest('a[href]') || card.querySelector('a[href]');
                if (anchor && anchor.href && anchor.href.includes('blinkit.com') && !anchor.href.endsWith('/')) {
                    url = anchor.href;
                } else if (card.id && /^\d+$/.test(card.id)) {
                    const slug = foundName.toLowerCase()
                        .replace(/[^a-z0-9]+/g, '-')
                        .replace(/^-+|-+$/g, '');
                    if (slug) {
                        url = `https://blinkit.com/prn/${slug}/prid/${card.id}`;
                    }
                }
                if (!url && foundName) {
                    const searchTerms = foundName.split(' ').slice(0, 4).join(' ');
                    url = 'https://blinkit.com/s/?q=' + encodeURIComponent(searchTerms);
                }

                let foundImage = null;
                const imgs = Array.from(card.querySelectorAll('img[src*="blinkit"], img[src*="grofers"]'))
                    .filter(img => img.src && !img.src.includes('data:image') && !img.src.includes('eta-icons') && !img.src.includes('ad_without_bg'));
                if (imgs.length > 0) {
                    imgs.sort((a, b) => {
                        const ar = a.getBoundingClientRect();
                        const br = b.getBoundingClientRect();
                        return (br.width * br.height) - (ar.width * ar.height);
                    });
                    foundImage = imgs[0].src;
                }

                results.push({
                    name: foundName,
                    price: selling.price,
                    url,
                    image_url: foundImage,
                    rank: results.length,
                });
            }

            // Fallback for layout changes where cards are not marked with a stable role/id.
            if (!results.length) {
                const priceElements = Array.from(document.querySelectorAll('div, span, p, h1, h2, h3, h4')).filter(el => {
                    const txt = textOf(el);
                    return txt.includes('₹') &&
                        /₹\s*\d+/.test(txt) &&
                        el.children.length === 0 &&
                        !isStruck(el, document.body);
                });

                for (const pEl of priceElements) {
                    const priceText = textOf(pEl);
                    const match = priceText.match(/₹\s*(\d+(?:\.\d+)?)/);
                    if (!match) continue;
                    const price = parseFloat(match[1]);
                    if (price < 1 || price > 10000) continue;

                    let current = pEl;
                    let foundName = null;
                    let searchSteps = 0;
                    while (current && searchSteps < 10) {
                        const candidates = Array.from(current.querySelectorAll('div, span, p, h1, h2, h3, h4'))
                            .map(el => clean(directText(el) || textOf(el)))
                            .filter(t => t.length > 3 && t.length < 100 && !t.includes('₹') && !t.toLowerCase().includes('showing results'));

                        for (const cand of candidates) {
                            if (hasQueryWord(cand) && !cand.toLowerCase().includes('safari')) {
                                foundName = cand;
                                break;
                            }
                        }
                        if (foundName) break;
                        current = current.parentElement;
                        searchSteps++;
                    }
                    if (!foundName) continue;

                    const searchTerms = foundName.split(' ').slice(0, 4).join(' ');
                    results.push({
                        name: clean(foundName),
                        price,
                        url: 'https://blinkit.com/s/?q=' + encodeURIComponent(searchTerms),
                        image_url: null,
                        rank: results.length,
                    });
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

        unit_tokens = {
            "g", "gm", "kg", "ml", "l", "ltr", "pc", "pcs", "piece", "pieces",
            "unit", "units", "pack", "packs", "fresh", "local"
        }
        DISTRACTORS = ["sweet", "spring", "baby", "red", "white", "pearl", "cherry", "grape", "frozen", "dehydrated", "flakes"]
        
        def price_per_gram(p):
            from scrapers.utils import parse_weight_to_grams
            grams = parse_weight_to_grams(p["name"])
            if grams <= 0: return p["price"]
            return p["price"] / grams

        # Prefer the exact grocery item over products that merely contain the
        # query word, then choose the cheapest equal match.
        def score(p):
            n = p["name"].lower()
            tokens = re.findall(r"[a-z0-9]+", n)
            match_count = sum(1 for w in query_words if w in n)
            
            # Distractor penalty
            distractor_penalty = 0
            for d in DISTRACTORS:
                if d in n and d not in " ".join(query_words):
                    distractor_penalty += 2.0
            
            all_words_bonus = 2.0 if query_words and all(w in n for w in query_words) else 0.0
            starts_with_bonus = 1.0 if first_query_word and n.startswith(first_query_word) else 0.0
            exact_token_bonus = 0.5 if all(w in tokens for w in query_words) else 0.0
            extra_tokens = [
                t for t in tokens
                if not t.isdigit() and t not in unit_tokens and all(t != w for w in query_words)
            ]
            extra_penalty = min(len(extra_tokens) * 0.25, 2.0)
            rank_penalty = float(p.get("rank") or 0) * 0.01
            
            return match_count + all_words_bonus + starts_with_bonus + exact_token_bonus - extra_penalty - rank_penalty - distractor_penalty
            
        first_query_word = query_words[0] if query_words else ""
        
        valid_products = [p for p in products if sum(1 for w in query_words if w in p["name"].lower()) > 0]
        
        if not valid_products:
            print(f"[Blinkit] No products found containing query keywords: {query_words}")
            return None
        
        # Tie-break by price-per-gram among top scoring matches
        top_score = score(max(valid_products, key=score))
        top_products = [p for p in valid_products if score(p) == top_score]
        best = min(top_products, key=price_per_gram)
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
