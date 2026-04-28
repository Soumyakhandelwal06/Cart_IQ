"use client";
import { useState } from "react";
import { PlatformCart } from "@/app/results/[searchId]/page";
import { useTheme } from "@/hooks/useTheme";
import { useAuth } from "@/context/AuthContext";

const PLATFORM_ICONS: Record<string, string> = {
  blinkit: "🟡",
  zepto: "🟣",
  bigbasket: "🟢",
};

// Platform checkout deep links — these open the search page on each platform
// Users can then select items manually or use the platform's cart
const PLATFORM_CHECKOUT_BASE: Record<string, string> = {
  blinkit: "https://blinkit.com/s/?q=",
  zepto: "https://www.zeptonow.com/search?q=",
  bigbasket: "https://www.bigbasket.com/custompage/sysgen/?type=pc&slug=",
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
  const { token } = useAuth();
  const [syncing, setSyncing] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  // Build a search query from all item names for the platform URL
  const searchQuery = platform.items
    .filter((i) => i.available)
    .map((i) => i.item_name)
    .join(" ");
  // Use first available item's product_url for direct checkout if possible
  const firstAvailableItem = platform.items.find((i) => i.available && i.product_url);
  const checkoutUrl = firstAvailableItem?.product_url ||
    ((PLATFORM_CHECKOUT_BASE[platform.platform] || "#") + encodeURIComponent(searchQuery));

  const handleCheckout = () => {
    window.open(checkoutUrl, "_blank", "noopener,noreferrer");
  };

  const handleSyncCart = async () => {
    if (!token) return alert("Please login first to sync your cart.");
    setSyncing(true);
    setSyncSuccess(false);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001'}/api/v1/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ platform: platform.platform, search_id: searchId }),
      });
      const data = await res.json();
      if (!res.ok) alert(data.error || "Failed to sync cart");
      else {
        setSyncSuccess(true);
        setTimeout(() => setSyncSuccess(false), 5000);
      }
    } catch (err) {
      alert("Network error occurred while syncing cart.");
    } finally {
      setSyncing(false);
    }
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
                  if (platform.platform === "zepto") return `https://www.zeptonow.com/search?query=${q}`;
                  return `https://www.bigbasket.com/ps/?q=${q}`;
                })()}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-slate-700 truncate block hover:text-violet-600 transition-colors cursor-pointer font-bold leading-tight"
              >
                {item.matched_product_name}
              </a>
              <p className="text-[13px] text-slate-500 mt-1 font-medium">
                {item.quantity} unit{item.quantity > 1 ? "s" : ""} · {item.available ? `₹${item.unit_price}` : ""}
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
        {(platform.handling_fee > 0 || platform.surge_fee > 0) && (
          <FeeRow label="Other Fees" value={platform.handling_fee + platform.surge_fee} warn={platform.surge_fee > 0} />
        )}
        <div className="border-t border-slate-200 pt-3 mt-2 flex items-center justify-between">
          <span className="font-extrabold tracking-wider text-slate-400 text-xs">TOTAL</span>
          <span className={`font-black text-2xl ${isWinner ? "text-emerald-600" : "text-slate-800"}`}>
            ₹{platform.total_payable.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Checkout Button */}
      <div className="px-6 py-5">
        {["zepto", "blinkit", "bigbasket"].includes(platform.platform) ? (
          <button
            onClick={handleSyncCart}
            id={`sync-${platform.platform}`}
            disabled={(!platform.all_items_available && platform.item_total === 0) || syncing}
            className={`w-full flex items-center justify-center gap-2 font-bold py-3.5 px-4 rounded-xl text-sm transition-all duration-200 active:scale-95 shadow-lg ${isWinner
              ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30"
              : theme === "light"
                ? "bg-violet-600 hover:bg-violet-500 text-[#ffffff]"
                : "bg-gray-800 hover:bg-gray-700 text-gray-200"
              } ${(!platform.all_items_available && platform.item_total === 0) || syncing ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            style={!isWinner && theme === "light" ? { background: "#7c3aed", color: "#ffffff" } : undefined}
          >
            {syncing ? `Syncing...` : syncSuccess ? "✅ Synced!" : `Sync to ${platform.platform_display}`}
          </button>
        ) : (
          <button
            onClick={handleCheckout}
            id={`checkout-${platform.platform}`}
            disabled={!platform.all_items_available && platform.item_total === 0}
            className={`w-full flex items-center justify-center gap-2 font-bold py-3.5 px-4 rounded-xl text-sm transition-all duration-200 active:scale-95 shadow-lg ${isWinner
              ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30"
              : theme === "light"
                ? "text-[#ffffff]"
                : "bg-gray-800 hover:bg-gray-700 text-gray-200"
              } ${(!platform.all_items_available && platform.item_total === 0) ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            style={!isWinner && theme === "light" ? { background: "#1e293b", color: "#ffffff" } : undefined}
          >
            {isWinner ? "Order Now" : `Shop on ${platform.platform_display}`} →
          </button>
        )}
      </div>
    </div>
  );
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
