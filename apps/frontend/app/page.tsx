"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

const PLACEHOLDER_QUERIES = [
  "2 kg onions, 1 Amul butter 500g, and 1 bread",
  "1L milk, 6 eggs, and 1 pack of rice",
  "Britannia bread, 500g Amul butter, 1kg tomatoes",
  "potatoes 2kg, onions 1kg, and 1 bread loaf",
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [placeholder, setPlaceholder] = useState("");
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [charIdx, setCharIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [location, setLocation] = useState<{ lat: number; lon: number } | null>(null);
  const router = useRouter();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Animated placeholder typewriter effect
  useEffect(() => {
    const target = PLACEHOLDER_QUERIES[placeholderIdx];
    if (charIdx < target.length) {
      const t = setTimeout(() => {
        setPlaceholder(target.slice(0, charIdx + 1));
        setCharIdx(charIdx + 1);
      }, 40);
      return () => clearTimeout(t);
    } else {
      const t = setTimeout(() => {
        setCharIdx(0);
        setPlaceholderIdx((placeholderIdx + 1) % PLACEHOLDER_QUERIES.length);
        setPlaceholder("");
      }, 2500);
      return () => clearTimeout(t);
    }
  }, [charIdx, placeholderIdx]);

  // Silently request location
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => setLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
        () => { } // fail silently, default location used on backend
      );
    }
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, lat: location?.lat, lon: location?.lon }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Something went wrong");
      }

      const { search_id } = await res.json();
      router.push(`/results/${search_id}?query=${encodeURIComponent(query)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unable to connect to the server. Make sure both services are running.");
      setLoading(false);
    }
  };

  return (
    <main className="gradient-mesh min-h-screen flex flex-col items-center justify-center px-4">
      {/* ── Animated background orbs ── */}
      <div className="bg-orb bg-orb-1" />
      <div className="bg-orb bg-orb-2" />
      <div className="bg-orb bg-orb-3" />
      <div className="bg-orb bg-orb-4" />
      <div className="bg-grid" />

      {/* All content sits above the orbs */}
      <div className="relative z-10 w-full flex flex-col items-center justify-center">
      {/* Logo / Header */}
      <div className="mb-10 text-center animate-slide-up">
        <div className="inline-flex items-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-500 via-purple-500 to-orange-400 p-0.5 shadow-xl shadow-purple-500/20">
            <div className="w-full h-full bg-white rounded-[14px] flex items-center justify-center text-2xl">
              🛒
            </div>
          </div>
          <h1
            className="text-4xl font-extrabold tracking-tight text-slate-800"
            style={{ fontFamily: "var(--font-outfit)" }}
          >
            Cart<span className="text-violet-600">IQ</span>
          </h1>
        </div>
        <p className="text-slate-500 text-lg max-w-md mx-auto leading-relaxed font-medium">
          Type your grocery list naturally. Find the{" "}
          <span className="text-emerald-600 font-bold">cheapest cart</span> across
          Zepto, Blinkit &amp; Bigbasket in seconds.
        </p>
      </div>

      {/* Search Box */}
      <form
        onSubmit={handleSearch}
        className="w-full max-w-2xl animate-slide-up"
        style={{ animationDelay: "0.1s" }}
      >
        <div className="search-glow relative rounded-3xl bg-white border border-slate-200 shadow-xl shadow-slate-200/50 overflow-hidden transition-all duration-300">
          <textarea
            ref={inputRef}
            id="search-input"
            rows={3}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSearch(e as unknown as React.FormEvent);
              }
            }}
            placeholder={placeholder || "What do you need today?"}
            className="w-full bg-transparent px-6 pt-6 pb-4 text-slate-800 font-medium text-lg placeholder-slate-400 resize-none focus:outline-none"
          />

          <div className="flex items-center justify-between px-6 pb-5 pt-2 border-t border-slate-100 bg-slate-50/50">
            <div className="flex gap-2">
              {["🟡 Blinkit", "🟣 Zepto", "🟢 Bigbasket"].map((p) => (
                <span
                  key={p}
                  className="text-xs font-semibold text-slate-500 bg-white border border-slate-200 shadow-sm rounded-full px-3 py-1.5"
                >
                  {p}
                </span>
              ))}
            </div>
            <button
              type="submit"
              disabled={loading || !query.trim()}
              id="search-btn"
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold px-6 py-2.5 rounded-2xl text-sm transition-all duration-200 active:scale-95 shadow-md shadow-violet-600/20"
            >
              {loading ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Searching...
                </>
              ) : (
                <>
                  <span>Compare Prices</span>
                  <span>→</span>
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 text-red-600 text-sm font-medium bg-red-50 border border-red-200 rounded-2xl px-5 py-3 shadow-sm">
            🚨 {error}
          </div>
        )}

        <p className="mt-4 text-center text-slate-400 text-sm font-medium">
          Press <kbd className="bg-slate-100 border border-slate-200 text-slate-500 text-xs px-2 py-0.5 rounded shadow-sm">Enter</kbd> to search · Location{" "}
          {location ? (
            <span className="text-emerald-500">detected ✓</span>
          ) : (
            <span className="text-slate-400">not set (using default)</span>
          )}
        </p>
      </form>

      {/* Example chips */}
      <div
        className="mt-8 flex flex-wrap justify-center gap-3 max-w-xl animate-slide-up"
        style={{ animationDelay: "0.2s" }}
      >
        {[
          "2kg onions + Amul butter 500g + bread",
          "1L milk + 6 eggs",
          "1kg tomatoes + potatoes 2kg",
        ].map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => setQuery(chip)}
            className="text-xs font-semibold text-slate-600 bg-white border border-slate-200 shadow-sm hover:border-violet-300 hover:text-violet-700 hover:shadow-md rounded-full px-4 py-2 transition-all duration-200"
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Feature badges */}
      <div
        className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6 max-w-3xl w-full animate-slide-up"
        style={{ animationDelay: "0.3s" }}
      >
        {[
          { icon: "📡", label: "Real-time prices", desc: "Live data from all platforms" },
          { icon: "🧾", label: "Exact cart total", desc: "Includes delivery & surge fees" },
          { icon: "🚀", label: "Instant checkout", desc: "One click to the cheapest app" },
        ].map((f) => (
          <div key={f.label} className="text-center p-6 rounded-3xl bg-white border border-slate-100 shadow-xl shadow-slate-200/40 hover:-translate-y-1 transition-transform duration-300">
            <div className="w-12 h-12 mx-auto mb-4 bg-slate-50 text-2xl flex items-center justify-center rounded-2xl shadow-inner border border-slate-100">{f.icon}</div>
            <div className="text-[15px] font-bold text-slate-800">{f.label}</div>
            <div className="text-[13px] font-medium text-slate-500 mt-1.5 leading-relaxed">{f.desc}</div>
          </div>
        ))}
      </div>
      </div> {/* end z-10 wrapper */}
    </main>
  );
}
