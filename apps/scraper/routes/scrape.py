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
    requested_quantity: int = 1
    requested_weight: Optional[str] = None
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

SUCCESSFUL_CART_STATUSES = {"success", "partial"}


def _as_positive_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _checkout_rows_by_url(results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not url:
            continue
        rows.setdefault(url, []).append(result)
    return rows


def _cart_summary(results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next(
        (
            result.get("totals")
            for result in results
            if isinstance(result, dict)
            and result.get("type") == "cart_summary"
            and isinstance(result.get("totals"), dict)
        ),
        None
    )


def _apply_cart_analysis(platform: PlatformCart, results: List[Dict[str, Any]]) -> None:
    """
    Rebuild the platform comparison rows from the cart-add result, not from the
    pre-cart scrape estimate. This keeps displayed quantities and totals aligned
    with what actually landed in the user's cart.
    """
    rows_by_url = _checkout_rows_by_url(results)
    final_items: List[PlatformItemResult] = []
    new_item_total = 0.0
    any_added = False
    all_requested_rows_fulfilled = True

    for item in platform.items:
        required_qty = _as_positive_int(item.quantity)
        row = rows_by_url.get(item.product_url or "", [])
        checkout_row = row.pop(0) if row else None
        status = checkout_row.get("status") if checkout_row else None
        added_qty = _as_positive_int(checkout_row.get("added_qty")) if checkout_row else 0

        if status in SUCCESSFUL_CART_STATUSES and added_qty > 0:
            if checkout_row.get("unit_price") is not None:
                item.unit_price = round(float(checkout_row["unit_price"]), 2)
            item.quantity = added_qty
            if checkout_row.get("subtotal") is not None:
                item.subtotal = round(float(checkout_row["subtotal"]), 2)
            else:
                item.subtotal = round(item.unit_price * added_qty, 2)
            item.available = True
            new_item_total += item.subtotal
            any_added = True
            if added_qty < required_qty or status != "success":
                all_requested_rows_fulfilled = False
        else:
            item.available = False
            item.quantity = 0
            item.subtotal = 0.0
            all_requested_rows_fulfilled = False

        final_items.append(item)

    platform.items = final_items
    platform.item_total = round(new_item_total, 2)

    summary_obj = _cart_summary(results)
    if summary_obj:
        print(f"[Scraper] Applying actual cart fees for {platform.platform}: {summary_obj}")
        # Blinkit can show a different final selling price after cart sync than
        # the pre-cart scrape. When the cart count matches the rows we just
        # added, trust Blinkit's cart item total for the comparison display.
        actual_item_total = summary_obj.get("item_total")
        summary_item_count = _as_positive_int(summary_obj.get("item_count"))
        added_item_count = sum(_as_positive_int(item.quantity) for item in platform.items if item.available)
        if (
            (platform.platform == "blinkit" or platform.platform == "zepto")
            and actual_item_total is not None
            and (summary_item_count == 0 or summary_item_count == added_item_count)
        ):
            actual_item_total = round(float(actual_item_total), 2)
            available_items = [item for item in platform.items if item.available]
            if len(available_items) == 1 and available_items[0].quantity > 0:
                available_items[0].subtotal = actual_item_total
                available_items[0].unit_price = round(actual_item_total / available_items[0].quantity, 2)
            platform.item_total = actual_item_total

        # Apply fees separately; for non-Blinkit platforms the item total stays
        # rebuilt from requested cart rows so stale cart entries cannot pollute
        # the comparison table.
        if summary_obj.get("delivery_fee") is not None:
            platform.delivery_fee = summary_obj["delivery_fee"]
        if summary_obj.get("handling_fee") is not None:
            platform.handling_fee = summary_obj["handling_fee"]
        if summary_obj.get("surge_fee") is not None:
            platform.surge_fee = summary_obj["surge_fee"]
    elif platform.platform == "bigbasket" and platform.item_total > 500:
        platform.delivery_fee = 0.0

    platform.total_payable = round(
        platform.item_total + platform.delivery_fee + platform.handling_fee + platform.surge_fee,
        2
    )
    platform.all_items_available = bool(final_items) and all_requested_rows_fulfilled

    if platform.all_items_available:
        platform.cart_status = "added"
    elif any_added:
        platform.cart_status = "partial"
    else:
        platform.cart_status = "failed"


def _clear_platform_cart_result(platform: PlatformCart) -> None:
    for item in platform.items:
        item.available = False
        item.quantity = 0
        item.subtotal = 0.0
    platform.item_total = 0.0
    platform.delivery_fee = 0.0
    platform.handling_fee = 0.0
    platform.surge_fee = 0.0
    platform.total_payable = 0.0
    platform.all_items_available = False
    platform.cart_status = "failed"

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
        from scrapers.blinkit import scrape_blinkit
        from scrapers.zepto import scrape_zepto
        from scrapers.bigbasket import scrape_bigbasket

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
                    name=item.matched_product_name,
                    unit_price=item.unit_price
                )
                for item in available_items
            ]

            if platform.platform == "zepto":
                results = await add_items_to_zepto_cart(p, storage_state, checkout_items, request.lat, request.lon)
            elif platform.platform == "blinkit":
                results = await add_items_to_blinkit_cart(p, storage_state, checkout_items)
            elif platform.platform == "bigbasket":
                results = await add_items_to_bigbasket_cart(p, storage_state, checkout_items)
            else:
                platform.cart_status = "failed"
                continue

            _apply_cart_analysis(platform, results)

            print(f"[Scraper] {platform.platform} cart → {platform.cart_status} (Total: ₹{platform.total_payable})")

        except Exception as e:
            print(f"[Scraper] Auto-checkout failed for {platform.platform}: {e}")
            _clear_platform_cart_result(platform)

    # ── Step 3: Find the winner ───────────────────────────────────────────────
    platforms_with_items = [
        p for p in platforms
        if p.cart_status != "failed" and sum(1 for i in p.items if i.available) > 0
    ]

    if not platforms_with_items:
        winner = platforms[0]
    else:
        def winner_score(p):
            available_count = sum(1 for i in p.items if i.available)
            return (1 if p.all_items_available else 0, available_count, -p.total_payable)
        winner = max(platforms_with_items, key=winner_score)

    return ScrapeResponse(
        platforms=platforms,
        winner=winner.platform,
        search_id=str(uuid.uuid4())
    )
