"use client";
import { useEffect, useState, useRef } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import PlatformColumn from "@/components/PlatformColumn";
import WinnerBanner from "@/components/WinnerBanner";
import SearchSkeleton from "@/components/SearchSkeleton";

type ProgressState = {
  status: "connecting" | "parsing" | "scraping" | "complete" | "error";
  message?: string;
  items?: Array<{ name: string; quantity: number; weight?: string; brand?: string }>;
  data?: {
    platforms: PlatformCart[];
    winner: string;
    from_cache?: boolean;
  };
  error?: string;
};

export type PlatformCart = {
  platform: string;
  platform_display: string;
  color: string;
  items: PlatformItem[];
  item_total: number;
  delivery_fee: number;
  handling_fee: number;
  surge_fee: number;
  total_payable: number;
  estimated_delivery_min: number;
  all_items_available: boolean;
};

export type PlatformItem = {
  platform: string;
  item_name: string;
  matched_product_name: string;
  available: boolean;
  unit_price: number;
  quantity: number;
  subtotal: number;
  image_url?: string;
  product_url?: string;
};

const STATUS_MESSAGES: Record<string, string> = {
  connecting: "Connecting to search engine...",
  parsing: "🧠 AI is parsing your grocery list...",
  scraping: "🔍 Checking prices across all platforms...",
};

import { useAuth } from "@/context/AuthContext";

export default function ResultsPage() {
  const { searchId } = useParams() as { searchId: string };
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user, token, loading: authLoading } = useAuth();
  const query = searchParams.get("query") || "";
  const [state, setState] = useState<ProgressState>({ status: "connecting" });
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/auth/login");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!searchId || authLoading || !user) return;
    let retryCount = 0;
    const maxRetries = 5;
    let es: EventSource;

    const connect = () => {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      // EventSource doesn't support headers, so we pass token in query param
      es = new EventSource(`${apiUrl}/api/v1/stream/${searchId}?token=${token}`);
      esRef.current = es;

      es.addEventListener("progress", (e) => {
        const data = JSON.parse(e.data);
        setState({ status: data.status, message: data.message, items: data.items });
      });

      es.addEventListener("result", (e) => {
        const data = JSON.parse(e.data);
        setState({ status: "complete", data: data.data });
        es.close();
      });

      es.addEventListener("error", (e) => {
        // If we finished successfully, ignore errors
        if (state.status === "complete") return;

        const data = JSON.parse((e as MessageEvent).data || '{"error":"Connection lost"}');

        if (retryCount < maxRetries) {
          retryCount++;
          console.log(`SSE connection lost. Retrying (${retryCount}/${maxRetries})...`);
          es.close();
          setTimeout(connect, 1500); // Retry after 1.5s
        } else {
          setState({ status: "error", error: data.error || "Connection to server lost after multiple retries." });
          es.close();
        }
      });

      es.onerror = (e) => {
        // EventSource.onerror is often broader than the 'error' event
        if (es.readyState === EventSource.CLOSED && state.status !== "complete") {
          // Handled by the 'error' event listener above or custom logic
        }
      };
    };

    connect();

    return () => es?.close();
  }, [searchId, state.status]);

  if (authLoading || !user) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-10 h-10 border-4 border-violet-500/20 border-t-violet-500 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <main className="gradient-mesh min-h-screen px-4 py-8">
      {/* Header */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors text-sm"
          >
            ← Back
          </button>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-white" style={{ fontFamily: "var(--font-outfit)" }}>
              Quick<span className="text-violet-400">Cart</span>
            </span>
          </div>

          <div className="flex items-center gap-4 animate-fade-in">
            <div className="flex flex-col items-end">
              <span className="text-white text-sm font-semibold">{user.name || user.phone}</span>
              <button 
                onClick={() => {
                  const { logout } = require("@/context/AuthContext").useAuth();
                  logout();
                }}
                className="text-xs text-gray-500 hover:text-red-400 transition-colors"
              >
                Logout
              </button>
            </div>
            <div className="w-10 h-10 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-lg">
              👤
            </div>
          </div>
        </div>

        {query && (
          <div className="mt-6 text-center">
            <p className="text-gray-400 text-sm mb-1">Results for</p>
            <p className="text-white text-lg font-medium">&quot;{query}&quot;</p>
          </div>
        )}
      </div>

      {/* Status Banner (connecting / parsing / scraping) */}
      {state.status !== "complete" && state.status !== "error" && (
        <div className="max-w-6xl mx-auto mb-6">
          <div className="flex items-center gap-3 bg-gray-900/80 border border-gray-700/50 rounded-2xl px-5 py-4">
            <span className="w-5 h-5 border-2 border-violet-400/30 border-t-violet-400 rounded-full animate-spin flex-shrink-0" />
            <span className="text-gray-300">
              {state.message || STATUS_MESSAGES[state.status]}
            </span>
          </div>

          {/* Parsed items preview */}
          {state.items && (
            <div className="mt-4 flex flex-wrap gap-2 justify-center">
              {state.items.map((item) => (
                <span
                  key={item.name}
                  className="text-sm bg-gray-800/70 border border-gray-700/40 rounded-full px-3 py-1 text-gray-300"
                >
                  {item.quantity}× {item.brand ? `${item.brand} ` : ""}{item.name}
                  {item.weight ? ` (${item.weight})` : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error State */}
      {state.status === "error" && (
        <div className="max-w-lg mx-auto text-center py-20">
          <div className="text-5xl mb-4">😕</div>
          <h2 className="text-xl font-semibold text-white mb-2">Something went wrong</h2>
          <p className="text-gray-400 mb-6">{state.error}</p>
          <button
            onClick={() => router.push("/")}
            className="bg-violet-600 hover:bg-violet-500 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Skeleton Loaders */}
      {(state.status === "parsing" || state.status === "scraping" || state.status === "connecting") && (
        <SearchSkeleton scraping={state.status === "scraping"} />
      )}

      {/* Results */}
      {state.status === "complete" && state.data && (
        <div className="max-w-6xl mx-auto">
          {/* Winner Banner */}
          <WinnerBanner
            winner={state.data.winner}
            platforms={state.data.platforms}
          />

          {/* Platform Columns */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mt-6">
            {state.data.platforms.map((platform, i) => (
              <PlatformColumn
                key={platform.platform}
                platform={platform}
                isWinner={platform.platform === state.data!.winner}
                animationDelay={i * 0.1}
              />
            ))}
          </div>

          {state.data.from_cache && (
            <p className="text-center text-gray-600 text-xs mt-6">
              ⚡ Served from cache · Prices refreshed in the last 5 minutes
            </p>
          )}
        </div>
      )}
    </main>
  );
}
