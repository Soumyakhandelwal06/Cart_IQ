"use client";
import { useState } from "react";
import { PlatformCart } from "@/app/results/[searchId]/page";
import { useTheme } from "@/hooks/useTheme";
import { useAuth } from "@/context/AuthContext";

const PLATFORM_COLORS: Record<string, { bg: string; text: string }> = {
  blinkit: { bg: "from-yellow-500/20 to-yellow-900/10", text: "text-yellow-400" },
  zepto: { bg: "from-purple-500/20 to-purple-900/10", text: "text-purple-400" },
  bigbasket: { bg: "from-green-500/20 to-green-900/10", text: "text-green-400" },
};

const PLATFORM_COLORS_LIGHT: Record<string, { gradient: string; text: string; border: string }> = {
  blinkit: {
    gradient: "linear-gradient(135deg, #f59e0b 0%, #fb923c 100%)",
    text: "#ffffff",
    border: "#f59e0b",
  },
  zepto: {
    gradient: "linear-gradient(135deg, #7c3aed 0%, #a855f7 100%)",
    text: "#ffffff",
    border: "#7c3aed",
  },
  bigbasket: {
    gradient: "linear-gradient(135deg, #16a34a 0%, #22c55e 100%)",
    text: "#ffffff",
    border: "#16a34a",
  },
};

const PLATFORM_CHECKOUT_BASE: Record<string, string> = {
  blinkit: "https://blinkit.com/",
  zepto: "https://www.zeptonow.com/",
  bigbasket: "https://www.bigbasket.com/",
};

export default function WinnerBanner({
  winner,
  platforms,
  searchId,
}: {
  winner: string;
  platforms: PlatformCart[];
  searchId: string;
}) {
  const theme = useTheme();
  const { token } = useAuth();
  const [syncing, setSyncing] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const winnerPlatform = platforms.find((p) => p.platform === winner);
  if (!winnerPlatform) return null;

  const sorted = [...platforms].sort((a, b) => a.total_payable - b.total_payable);
  const colors = PLATFORM_COLORS[winner] || { bg: "from-emerald-500/20", text: "text-emerald-400" };
  const savings = sorted.length > 1 ? sorted[sorted.length - 1].total_payable - sorted[0].total_payable : 0;

  const firstAvailableItem = winnerPlatform.items.find((i) => i.available && i.product_url);
  const checkoutUrl = firstAvailableItem?.product_url || PLATFORM_CHECKOUT_BASE[winner] || "#";

  return (
    <div
      className={`rounded-3xl bg-gradient-to-br ${colors.bg} border-2 border-emerald-500/40 p-8 animate-slide-up shadow-2xl shadow-emerald-500/10 backdrop-blur-md relative overflow-hidden`}
    >
      {/* Decorative background element */}
      <div className="absolute -right-10 -top-10 w-40 h-40 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 relative z-10">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-3xl animate-bounce">🏆</span>
            <span className="text-xs uppercase tracking-[0.2em] text-emerald-400 font-extrabold bg-emerald-950/50 px-3 py-1 rounded-full border border-emerald-500/30">
              Optimal Choice Found
            </span>
          </div>

          <div>
            <h2 className="text-3xl md:text-4xl font-black text-white leading-tight" style={{ fontFamily: "var(--font-outfit)" }}>
              <span className={colors.text}>{winnerPlatform.platform_display}</span> is your best bet
            </h2>
            <p className="text-gray-300 text-lg mt-2 font-medium">
              Total Payable: <span className="text-white font-black text-2xl">₹{winnerPlatform.total_payable.toFixed(0)}</span>
              {savings > 0 && (
                <span className="ml-3 inline-flex items-center gap-1.5 text-emerald-400 font-bold bg-emerald-500/10 px-3 py-1 rounded-lg">
                  <span className="text-sm">⚡</span> Save ₹{savings.toFixed(0)}
                </span>
              )}
            </p>
          </div>

          {/* Comparison mini-table */}
          <div className="flex flex-wrap items-center gap-6 mt-6 pt-6 border-t border-white/10">
            {sorted.map((p, i) => (
              <div key={p.platform} className={`flex items-center gap-2 px-3 py-1.5 rounded-xl transition-all ${i === 0 ? "bg-white/10 scale-105" : "opacity-60"} `}>
                <span className="text-lg">
                  {i === 0 ? "🥇" : i === 1 ? "🥈" : "🥉"}
                </span>
                <div>
                  <p className="text-white text-xs font-bold leading-none">{p.platform_display}</p>
                  <p className="text-gray-400 text-[10px] mt-1">₹{p.total_payable.toFixed(0)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {["zepto", "blinkit", "bigbasket"].includes(winner) ? (
            <button
              onClick={async () => {
                if (!token) return alert("Please login first to sync your cart.");
                setSyncing(true);
                setSyncSuccess(false);
                try {
                  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001'}/api/v1/checkout`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                    body: JSON.stringify({ platform: winner, search_id: searchId }),
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
              }}
              disabled={syncing}
              className="group relative flex-shrink-0 flex items-center justify-center gap-3 bg-white text-black hover:bg-emerald-50 transition-all duration-300 active:scale-95 shadow-xl shadow-white/10 px-8 py-4 rounded-2xl font-black text-lg overflow-hidden disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="relative z-10 flex items-center gap-2">
                {syncing ? `Syncing to ${winnerPlatform.platform_display}...` : syncSuccess ? "✅ Items Synced!" : `Sync to my ${winnerPlatform.platform_display} Cart`} 
              </span>
            </button>
          ) : (
            <a
              href={checkoutUrl}
              target="_blank"
              rel="noopener noreferrer"
              id="winner-checkout-btn"
              className="group relative flex-shrink-0 flex items-center justify-center gap-3 bg-white text-black hover:bg-emerald-50 transition-all duration-300 active:scale-95 shadow-xl shadow-white/10 px-10 py-5 rounded-2xl font-black text-lg overflow-hidden"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-emerald-400/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <span className="relative z-10 flex items-center gap-2">
                Instant Purchase <span className="text-2xl transition-transform group-hover:translate-x-1">→</span>
              </span>
            </a>
          )}
          <p className="text-center text-[10px] text-gray-500 font-medium uppercase tracking-widest">
            {["zepto", "blinkit", "bigbasket"].includes(winner) ? "Automated Sync via CartIQ" : `Secure Transaction on ${winnerPlatform.platform_display}`}
          </p>
        </div>
      </div>
    </div>
  );
}
