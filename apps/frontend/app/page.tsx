"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

const PLACEHOLDER_QUERIES = [
  "2 kg onions, 1 Amul butter 500g, and 1 bread",
  "1L milk, 6 eggs, and 1 pack of rice",
  "Britannia bread, 500g Amul butter, 1kg tomatoes",
  "potatoes 2kg, onions 1kg, and 1 bread loaf",
];

import { useAuth } from "@/context/AuthContext";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const { user, token, logout, loading: authLoading } = useAuth();
  const [placeholder, setPlaceholder] = useState("");
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [charIdx, setCharIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [location, setLocation] = useState<{ lat: number; lon: number } | null>(null);
  const router = useRouter();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/auth/login");
    }
  }, [user, authLoading, router]);

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

  if (authLoading || !user) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-10 h-10 border-4 border-violet-500/20 border-t-violet-500 rounded-full animate-spin" />
      </div>
    );
  }

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/query`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ query, lat: location?.lat, lon: location?.lon }),
      });
      // ...

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
      <div className="absolute top-6 right-20 z-20 flex items-center gap-4 animate-fade-in">
        <div className="flex flex-col items-end">
          <span className="text-white text-sm font-semibold">{user.name || user.phone}</span>
          <div className="flex gap-3 items-center">
            <button 
              onClick={() => router.push("/profile")}
              className="text-xs text-gray-500 hover:text-violet-400 transition-colors"
            >
              Linked Accounts
            </button>
            <button 
              onClick={logout}
              className="text-xs text-gray-500 hover:text-red-400 transition-colors"
            >
              Logout
            </button>
          </div>
        </div>
        <div className="w-10 h-10 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center text-lg">
          👤
        </div>
      </div>

      <div className="relative z-10 w-full flex flex-col items-center justify-center">
        {/* Logo / Header */}
        <div className="mb-10 text-center animate-slide-up">
        <div className="inline-flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-orange-400 flex items-center justify-center text-xl">
            🛒
          </div>
          <h1
            className="text-3xl font-bold tracking-tight text-white dark:text-white"
            style={{ fontFamily: "var(--font-outfit)" }}
          >
            Quick<span className="text-violet-400">Cart</span>
          </h1>
        </div>
        <p className="text-gray-400 text-lg max-w-md mx-auto leading-relaxed">
          Type your grocery list naturally. Find the{" "}
          <span className="text-emerald-400 font-semibold">cheapest cart</span> across
          Zepto, Blinkit &amp; Bigbasket in seconds.
        </p>
      </div>

      {/* Search Box */}
      <form
        onSubmit={handleSearch}
        className="w-full max-w-2xl animate-slide-up"
        style={{ animationDelay: "0.1s" }}
      >
        <div className="search-glow relative rounded-2xl bg-gray-900 border border-gray-700/60 overflow-hidden">
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
            placeholder={placeholder || "Type your grocery list..."}
            className="w-full bg-transparent px-5 pt-5 pb-3 text-white text-lg placeholder-gray-600 resize-none focus:outline-none"
          />

          <div className="flex items-center justify-between px-5 pb-4 pt-1">
            <div className="flex gap-2">
              {["🟡 Blinkit", "🟣 Zepto", "🟠 Bigbasket"].map((p) => (
                <span
                  key={p}
                  className="text-xs text-gray-500 bg-gray-800 rounded-full px-2 py-1"
                >
                  {p}
                </span>
              ))}
            </div>
            <button
              type="submit"
              disabled={loading || !query.trim()}
              id="search-btn"
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold px-5 py-2 rounded-xl text-sm transition-all duration-200 active:scale-95"
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
          <div className="mt-3 text-red-400 text-sm bg-red-950/40 border border-red-800/50 rounded-xl px-4 py-3">
            ⚠️ {error}
          </div>
        )}

        <p className="mt-3 text-center text-gray-600 text-sm">
          Press <kbd className="bg-gray-800 text-gray-400 text-xs px-2 py-0.5 rounded">Enter</kbd> to search · Location{" "}
          {location ? (
            <span className="text-emerald-600">detected ✓</span>
          ) : (
            <span className="text-gray-600">not set (using default)</span>
          )}
        </p>
      </form>

      {/* Example chips */}
      <div
        className="mt-8 flex flex-wrap justify-center gap-2 max-w-xl animate-slide-up"
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
            className="text-xs text-gray-400 bg-gray-900/70 border border-gray-700/50 hover:border-violet-500/50 hover:text-violet-300 rounded-full px-3 py-1.5 transition-all duration-150"
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Feature badges */}
      <div
        className="mt-16 grid grid-cols-3 gap-4 max-w-lg w-full animate-slide-up"
        style={{ animationDelay: "0.3s" }}
      >
        {[
          { icon: "📡", label: "Real-time prices", desc: "Live data from all platforms" },
          { icon: "🧾", label: "Exact cart total", desc: "Includes delivery & surge fees" },
          { icon: "🚀", label: "Instant checkout", desc: "One click to the cheapest app" },
        ].map((f) => (
          <div key={f.label} className="text-center p-4 rounded-2xl bg-gray-900/60 border border-gray-800/50">
            <div className="text-2xl mb-2">{f.icon}</div>
            <div className="text-sm font-semibold text-gray-200">{f.label}</div>
            <div className="text-xs text-gray-500 mt-1">{f.desc}</div>
          </div>
        ))}
      </div>
      </div> {/* end z-10 wrapper */}
    </main>
  );
}
