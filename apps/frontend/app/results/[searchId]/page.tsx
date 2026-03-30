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

export default function ResultsPage() {
  const { searchId } = useParams() as { searchId: string };
  const searchParams = useSearchParams();
  const router = useRouter();
  const query = searchParams.get("query") || "";
  const [state, setState] = useState<ProgressState>({ status: "connecting" });
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!searchId) return;
    let retryCount = 0;
    const maxRetries = 5;
    let es: EventSource;

    const connect = () => {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      es = new EventSource(`${apiUrl}/api/v1/stream/${searchId}`);
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

  return (
    <main className="gradient-mesh min-h-screen px-4 py-8">
      {/* Header */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-2 text-slate-500 hover:text-slate-900 font-medium transition-colors text-sm bg-white border border-slate-200 shadow-sm rounded-full px-4 py-2"
          >
            ← Back
          </button>
          <div className="flex items-center gap-2">
            <span className="text-3xl font-extrabold text-slate-800 tracking-tight" style={{ fontFamily: "var(--font-outfit)" }}>
              Cart<span className="text-violet-600">IQ</span>
            </span>
          </div>
          <div className="w-24" />
        </div>

        {query && (
          <div className="mt-8 text-center animate-slide-up">
            <p className="text-slate-500 text-sm font-semibold mb-1 uppercase tracking-wider">Results for</p>
            <p className="text-slate-800 text-xl font-bold">&quot;{query}&quot;</p>
          </div>
        )}
      </div>

      {/* Status Banner (connecting / parsing / scraping) */}
      {state.status !== "complete" && state.status !== "error" && (
        <div className="max-w-6xl mx-auto mb-8">
          <div className="flex items-center gap-4 bg-white border border-slate-200 shadow-sm rounded-2xl px-6 py-5 w-full max-w-2xl mx-auto">
            <span className="w-5 h-5 border-2 border-violet-200 border-t-violet-600 rounded-full animate-spin flex-shrink-0" />
            <span className="text-slate-700 font-semibold text-lg">
              {state.message || STATUS_MESSAGES[state.status]}
            </span>
          </div>

          {/* Parsed items preview */}
          {state.items && (
            <div className="mt-6 flex flex-wrap gap-2 justify-center max-w-3xl mx-auto">
              {state.items.map((item) => (
                <span
                  key={item.name}
                  className="text-sm font-medium bg-slate-100 border border-slate-200 rounded-full px-4 py-1.5 text-slate-700 shadow-sm"
                >
                  <span className="text-violet-600 font-bold mr-1">{item.quantity}×</span> {item.brand ? `${item.brand} ` : ""}{item.name}
                  {item.weight ? <span className="text-slate-400 ml-1">({item.weight})</span> : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error State */}
      {state.status === "error" && (
        <div className="max-w-lg mx-auto text-center py-24 bg-white border border-slate-200 rounded-3xl shadow-xl shadow-slate-200/50 mt-10">
          <div className="text-6xl mb-6">😕</div>
          <h2 className="text-2xl font-bold text-slate-800 mb-3">Something went wrong</h2>
          <p className="text-slate-500 mb-8 max-w-sm mx-auto">{state.error}</p>
          <button
            onClick={() => router.push("/")}
            className="bg-violet-600 hover:bg-violet-700 text-white font-bold px-8 py-3.5 rounded-2xl shadow-md transition-all active:scale-95"
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
            <p className="text-center text-slate-400 font-medium text-xs mt-8 pb-8">
              ⚡ Served from cache · Prices refreshed in the last 5 minutes
            </p>
          )}
        </div>
      )}
    </main>
  );
}
