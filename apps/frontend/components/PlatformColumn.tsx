"use client";
import { PlatformCart } from "@/app/results/[searchId]/page";
import { useTheme } from "@/hooks/useTheme";

const PLATFORM_ICONS: Record<string, string> = {
  blinkit: "🟡",
  zepto: "🟣",
  bigbasket: "🟢",
};

// Cart URLs per platform (fallback if not returned by API)
const PLATFORM_CART_URLS: Record<string, string> = {
  blinkit: "https://blinkit.com/cart",
  zepto: "https://www.zepto.com/?cart=open",
  bigbasket: "https://www.bigbasket.com/basket/?nc=nb",
};

// Human-readable cart status labels + colours
const CART_STATUS_CONFIG: Record<string, { label: string; icon: string; cls: string }> = {
  added:         { label: "Added to cart",   icon: "✅", cls: "text-emerald-600 bg-emerald-50 border-emerald-200" },
  partial:       { label: "Partially added", icon: "⚠️", cls: "text-amber-600 bg-amber-50 border-amber-200" },
  failed:        { label: "Cart add failed", icon: "❌", cls: "text-red-500 bg-red-50 border-red-200" },
  not_connected: { label: "Not connected",   icon: "🔗", cls: "text-slate-500 bg-slate-100 border-slate-200" },
};

export default function PlatformColumn({
  platform,
  isWinner,
  animationDelay,
}: {
  platform: PlatformCart;
  isWinner: boolean;
  animationDelay: number;
  searchId: string;
}) {
  const theme = useTheme();

  const cartUrl = platform.cart_url || PLATFORM_CART_URLS[platform.platform] || "#";
  const cartStatus = platform.cart_status;
  const statusCfg = cartStatus ? CART_STATUS_CONFIG[cartStatus] : null;

  const handleGoToCart = () => {
    window.open(cartUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <div
      className={`platform-card rounded-3xl overflow-hidden animate-slide-up transition-all duration-300 ${isWinner
        ? "border-2 border-emerald-400 winner-glow bg-white scale-[1.03] shadow-2xl shadow-emerald-500/20 z-10"
        : "border border-slate-200 bg-white shadow-xl shadow-slate-200/50"
        }`}
      style={{ animationDelay: `${animationDelay}s` }}
    >
      {/* Platform Header */}
      <div
        className={`px-6 py-5 flex items-center justify-between border-b ${isWinner ? "border-emerald-100 bg-emerald-50/50" : "border-slate-100 bg-slate-50/50"
          }`}
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl drop-shadow-sm">{PLATFORM_ICONS[platform.platform] || "🛒"}</span>
          <span className="font-extrabold text-slate-800 text-xl tracking-tight" style={{ fontFamily: "var(--font-outfit)" }}>
            {platform.platform_display}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isWinner && (
            <span className="text-[10px] font-black tracking-widest text-emerald-600 bg-emerald-100 border border-emerald-200 rounded-full px-3 py-1 shadow-sm">
              BEST PRICE
            </span>
          )}
          <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-2 py-1 rounded-md">~{platform.estimated_delivery_min}m</span>
        </div>
      </div>

      {/* Cart Status Badge */}
      {statusCfg && (
        <div className={`mx-6 mt-4 flex items-center gap-2 text-xs font-semibold border rounded-xl px-3 py-2 ${statusCfg.cls}`}>
          <span>{statusCfg.icon}</span>
          <span>{statusCfg.label}</span>
        </div>
      )}

      {/* Item List */}
      <div className="px-6 py-4 space-y-2 max-h-[350px] overflow-y-auto custom-scrollbar">
        {platform.items.map((item) => (
          <div key={item.item_name} className="flex items-center justify-between gap-4 py-3 border-b border-slate-100/80 last:border-0 hover:bg-slate-50/50 transition-colors rounded-xl px-2 -mx-2">
            {/* Image */}
            <div className="w-14 h-14 rounded-xl bg-white flex-shrink-0 overflow-hidden border border-slate-200 shadow-sm flex items-center justify-center p-1">
              {item.image_url ? (
                <img src={item.image_url} alt={item.matched_product_name} className="w-full h-full object-contain" />
              ) : (
                <span className="text-2xl opacity-50">📦</span>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <a
                href={(() => {
                  const isUsableUrl = (u?: string) => {
                    if (!u || u === "#") return false;
                    try {
                      const parsed = new URL(u);
                      return parsed.pathname.length > 1 || parsed.search.length > 0;
                    } catch { return false; }
                  };
                  if (isUsableUrl(item.product_url)) return item.product_url!;
                  const q = encodeURIComponent(item.matched_product_name);
                  if (platform.platform === "blinkit") return `https://blinkit.com/s/?q=${q}`;
                  if (platform.platform === "zepto") return `https://www.zepto.com/search?query=${q}`;
                  return `https://www.bigbasket.com/ps/?q=${q}`;
                })()}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-slate-700 truncate block hover:text-violet-600 transition-colors cursor-pointer font-bold leading-tight"
              >
                {item.matched_product_name}
              </a>
              <p className="text-[13px] text-slate-500 mt-1 font-medium">
                {formatRequestedItem(item)}
                {item.available ? ` · Added ${item.quantity} unit${item.quantity > 1 ? "s" : ""} · ₹${item.unit_price}` : ""}
              </p>
            </div>

            <div className="text-right flex-shrink-0">
              {item.available ? (
                <p className="text-[15px] font-black text-slate-800 bg-slate-100 px-2 py-1 rounded-lg">₹{item.subtotal.toFixed(0)}</p>
              ) : (
                <span className="text-xs font-bold text-red-600 bg-red-50 border border-red-100 rounded-md px-2 py-1 shadow-sm">
                  N/A
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Fee Breakdown */}
      <div className="px-6 py-5 bg-slate-50 space-y-2 border-t border-slate-100">
        <FeeRow label="Items Total" value={platform.item_total} />
        <FeeRow label="Delivery" value={platform.delivery_fee} />
        {platform.handling_fee > 0 && (
          <FeeRow label="Handling Fee" value={platform.handling_fee} />
        )}
        <div className="border-t border-slate-200 pt-3 mt-2 flex items-center justify-between">
          <span className="font-extrabold tracking-wider text-slate-400 text-xs">TOTAL</span>
          <span className={`font-black text-2xl ${isWinner ? "text-emerald-600" : "text-slate-800"}`}>
            ₹{platform.total_payable.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Go to Cart Button */}
      <div className="px-6 py-5">
        <button
          onClick={handleGoToCart}
          id={`go-to-cart-${platform.platform}`}
          disabled={!platform.all_items_available && platform.item_total === 0}
          className={`w-full flex items-center justify-center gap-2 font-bold py-3.5 px-4 rounded-xl text-sm transition-all duration-200 active:scale-95 shadow-lg ${
            isWinner
              ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30"
              : theme === "light"
                ? "bg-violet-600 hover:bg-violet-500 text-white"
                : "bg-gray-800 hover:bg-gray-700 text-gray-200"
          } ${(!platform.all_items_available && platform.item_total === 0) ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
          style={!isWinner && theme === "light" ? { background: "#7c3aed", color: "#ffffff" } : undefined}
        >
          🛒 Go to {platform.platform_display} Cart →
        </button>
      </div>
    </div>
  );
}

function formatRequestedItem(item: PlatformCart["items"][number]) {
  const requestedQty = item.requested_quantity ?? item.quantity;
  if (item.requested_weight) {
    return requestedQty > 1
      ? `Requested ${requestedQty} x ${item.requested_weight}`
      : `Requested ${item.requested_weight}`;
  }
  return `Requested ${requestedQty} unit${requestedQty > 1 ? "s" : ""}`;
}

function FeeRow({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={`text-[11px] font-bold uppercase tracking-wider ${warn ? "text-orange-500" : "text-slate-500"}`}>{label}</span>
      <span className={`text-[13px] font-bold ${warn ? "text-orange-500" : "text-slate-600"}`}>
        ₹{value.toFixed(0)}
      </span>
    </div>
  );
}
