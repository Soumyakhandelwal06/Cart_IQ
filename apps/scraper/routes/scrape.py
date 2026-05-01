"""
Scrape route — dispatches parallel scraping tasks to Blinkit, Zepto, and Bigbasket,
then automatically adds items to the cart of each connected (logged-in) platform.
Returns aggregated results including cart status and cart URL per platform.
"""
import asyncio
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from scrapers.blinkit import scrape_blinkit
from scrapers.zepto import scrape_zepto
from scrapers.bigbasket import scrape_bigbasket

router = APIRouter()

# ── Models ─────────────────────────────────────────────────────────────────────

class ScrapeItem(BaseModel):
    name: str
    quantity: int
    weight: Optional[str] = None
    brand: Optional[str] = None

class ScrapeRequest(BaseModel):
    items: list[ScrapeItem]
    lat: Optional[float] = 12.9716  # default: Bengaluru
    lon: Optional[float] = 77.5946
    # Optional: per-platform saved login sessions from the user's linked accounts
    storage_states: Optional[Dict[str, Any]] = None  # { "zepto": {...}, "blinkit": {...}, "bigbasket": {...} }

class PlatformItemResult(BaseModel):
    platform: str
    item_name: str
    matched_product_name: str
    available: bool
    unit_price: float
    quantity: int
    subtotal: float
    image_url: Optional[str] = None
    product_url: Optional[str] = None

class PlatformCart(BaseModel):
    platform: str
    platform_display: str
    color: str
    items: list[PlatformItemResult]
    item_total: float
    delivery_fee: float
    handling_fee: float
    surge_fee: float
    total_payable: float
    estimated_delivery_min: int
    all_items_available: bool
    # New fields for the unified flow:
    cart_url: Optional[str] = None         # Direct link to the platform's cart page
    cart_status: Optional[str] = None      # "added" | "failed" | "not_connected" | "partial"

class ScrapeResponse(BaseModel):
    platforms: list[PlatformCart]
    winner: str  # platform key of cheapest
    search_id: str

# Cart URLs for each platform
CART_URLS = {
    "zepto": "https://www.zepto.com/?cart=open",
    "blinkit": "https://blinkit.com/cart",
    "bigbasket": "https://www.bigbasket.com/basket/?nc=nb",
}

# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ScrapeResponse)
async def scrape_all(request: ScrapeRequest, req: Request):
    """
    1. Scrapes all 3 platforms (with auth session if provided)
    2. Auto-adds items to cart for each connected platform
    3. Returns comparison results with cart_url and cart_status
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")

    storage_states = request.storage_states or {}

    # ── Step 1: Scrape all 3 platforms concurrently ───────────────────────────
    try:
        scrape_results = await asyncio.wait_for(
            asyncio.gather(
                scrape_blinkit(request.items, request.lat, request.lon,
                               storage_state=storage_states.get("blinkit")),
                scrape_zepto(request.items, request.lat, request.lon,
                             storage_state=storage_states.get("zepto")),
                scrape_bigbasket(request.items, request.lat, request.lon,
                                 storage_state=storage_states.get("bigbasket")),
                return_exceptions=True
            ),
            timeout=300.0
        )
    except asyncio.TimeoutError:
        print("[Scraper] Global timeout reached during scraping")
        raise HTTPException(status_code=504, detail="Scraping timed out across all platforms.")

    platforms: List[PlatformCart] = []
    for result in scrape_results:
        if isinstance(result, Exception):
            print(f"[Scraper] Platform failed: {result}")
            continue
        # Attach the cart URL to each platform result
        result.cart_url = CART_URLS.get(result.platform)
        # If no session provided → not connected
        if result.platform not in storage_states:
            result.cart_status = "not_connected"
        platforms.append(result)

    if not platforms:
        raise HTTPException(status_code=503, detail="All platforms unavailable. Try again later.")

    # ── Step 2: Auto-add to cart for each connected platform ──────────────────
    p = req.app.state.playwright  # Reuse the shared Playwright instance
    for platform in platforms:
        if platform.cart_status == "not_connected":
            continue
        storage_state = storage_states.get(platform.platform)
        if not storage_state:
            platform.cart_status = "not_connected"
            continue

        # Build list of CheckoutItem-like dicts from scraped results
        available_items = [
            item for item in platform.items
            if item.available and item.product_url
        ]
        if not available_items:
            platform.cart_status = "failed"
            continue

        try:
            print(f"[Scraper] Auto-adding {len(available_items)} items to {platform.platform} cart...")
            from routes.checkout import (
                CheckoutItem,
                add_items_to_zepto_cart,
                add_items_to_blinkit_cart,
                add_items_to_bigbasket_cart,
            )

            checkout_items = [
                CheckoutItem(
                    product_url=item.product_url,
                    quantity=item.quantity,
                    name=item.matched_product_name
                )
                for item in available_items
            ]

            if platform.platform == "zepto":
                results = await add_items_to_zepto_cart(p, storage_state, checkout_items)
            elif platform.platform == "blinkit":
                results = await add_items_to_blinkit_cart(p, storage_state, checkout_items)
            elif platform.platform == "bigbasket":
                results = await add_items_to_bigbasket_cart(p, storage_state, checkout_items)
            else:
                platform.cart_status = "failed"
                continue

            # Reconcile items: update comparison table to match exactly what was added to the cart
            successful_urls = {r.get("url"): r.get("added_qty", 0) for r in results if r.get("status") in ["success", "partial"]}
            
            final_items = []
            new_item_total = 0.0
            for item in platform.items:
                # If we successfully added some quantity of this product URL
                if item.product_url in successful_urls:
                    added_qty = successful_urls[item.product_url]
                    if added_qty > 0:
                        item.quantity = added_qty
                        item.subtotal = round(item.unit_price * added_qty, 2)
                        new_item_total += item.subtotal
                        final_items.append(item)
                else:
                    # Item failed to add
                    item.available = False
                    item.quantity = 0
                    item.subtotal = 0.0
                    final_items.append(item)

            platform.items = final_items
            platform.item_total = round(new_item_total, 2)
            
            if platform.platform == "bigbasket" and platform.item_total > 500:
                platform.delivery_fee = 0.0
                
            platform.total_payable = round(platform.item_total + platform.delivery_fee + platform.handling_fee + platform.surge_fee, 2)
            platform.all_items_available = all(i.available for i in final_items)

            # Determine cart_status from results
            statuses = [r.get("status", "error") for r in results]
            if all(s == "success" for s in statuses) and len(statuses) > 0:
                platform.cart_status = "added"
            elif any(s in ("success", "partial") for s in statuses):
                platform.cart_status = "partial"
            else:
                platform.cart_status = "failed"

            print(f"[Scraper] {platform.platform} cart → {platform.cart_status} (Total: ₹{platform.total_payable})")

        except Exception as e:
            print(f"[Scraper] Auto-checkout failed for {platform.platform}: {e}")
            platform.cart_status = "failed"

    # ── Step 3: Find the winner ───────────────────────────────────────────────
    platforms_with_items = [p for p in platforms if sum(1 for i in p.items if i.available) > 0]

    if not platforms_with_items:
        winner = platforms[0]
    else:
        def winner_score(p):
            available_count = sum(1 for i in p.items if i.available)
            return (available_count, -p.total_payable)
        winner = max(platforms_with_items, key=winner_score)

    return ScrapeResponse(
        platforms=platforms,
        winner=winner.platform,
        search_id=str(uuid.uuid4())
    )
