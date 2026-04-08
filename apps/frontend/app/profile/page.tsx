"use client";
import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

type PlatformStatus = {
  zepto: boolean;
  blinkit: boolean;
  bigbasket: boolean;
  phone: string;
};

export default function ProfilePage() {
  const { user, token, loading: authLoading } = useAuth();
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState<"init" | "otp">("init");
  const [isVerifying, setIsVerifying] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const setError = (platform: string, msg: string) =>
    setErrors((prev) => ({ ...prev, [platform]: msg }));
  const clearError = (platform: string) =>
    setErrors((prev) => { const n = { ...prev }; delete n[platform]; return n; });
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth/login");
    if (user) fetchStatus();
  }, [user, authLoading]);

  const fetchStatus = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/platforms/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setStatus(data);
      if (data.phone) setPhone(data.phone);
    } catch (err) {
      console.error("Failed to fetch platform status");
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerOtp = async (platform: string) => {
    setConnecting(platform);
    clearError(platform);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/platforms/trigger-otp`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({ platform, phone }),
      });
      if (!res.ok) throw new Error("Failed to trigger OTP");
      setStep("otp");
    } catch (err: any) {
      setError(platform, err.message);
      setConnecting(null);
    }
  };

  const handleVerifyOtp = async () => {
    if (!connecting || isVerifying) return;
    setIsVerifying(true);
    clearError(connecting);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/platforms/verify-otp`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({ platform: connecting, phone, otp }),
      });
      if (!res.ok) throw new Error("Verification failed");

      // Success!
      setStep("init");
      setConnecting(null);
      setOtp("");
      await fetchStatus();
    } catch (err: any) {
      setError(connecting, err.message);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleDisconnect = async (platform: string) => {
    setDisconnecting(platform);
    clearError(platform);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/platforms/disconnect`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ platform }),
      });
      if (!res.ok) throw new Error("Failed to disconnect");
      await fetchStatus();
    } catch (err: any) {
      setError(platform, err.message);
    } finally {
      setDisconnecting(null);
    }
  };

  if (authLoading || loading || !user) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-10 h-10 border-4 border-violet-500/20 border-t-violet-500 rounded-full animate-spin" />
      </div>
    );
  }

  const platforms = [
    { id: "zepto", name: "Zepto", color: "from-violet-500 to-purple-600", icon: "🟣" },
    { id: "blinkit", name: "Blinkit", color: "from-yellow-400 to-yellow-600", icon: "🟡" },
    { id: "bigbasket", name: "Bigbasket", color: "from-green-500 to-emerald-600", icon: "🟢" },
  ];

  return (
    <main className="gradient-mesh min-h-screen pt-24 px-4 pb-12">
      <div className="max-w-2xl mx-auto">
        <button
          onClick={() => router.push("/")}
          className="mb-8 flex items-center gap-2 text-gray-400 hover:text-white transition-colors"
        >
          ← Back to Search
        </button>

        <header className="mb-12">
          <h1 className="text-4xl font-bold text-white mb-2" style={{ fontFamily: "var(--font-outfit)" }}>
            Linked Accounts
          </h1>
          <p className="text-gray-400">
            Connect your grocery accounts to get personalized pricing, loyalty discounts, and one-tap checkout.
          </p>
        </header>

        <div className="space-y-4">
          {platforms.map((p) => {
            const isConnected = (status as any)[p.id];
            const isActive = connecting === p.id;

            return (
              <div 
                key={p.id}
                className={`relative overflow-hidden rounded-[2rem] border transition-all duration-300 ${
                  isConnected ? "bg-gray-900/40 border-emerald-500/30" : "bg-gray-900/60 border-white/10"
                }`}
              >
                <div className="p-6 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${p.color} flex items-center justify-center text-2xl shadow-lg shadow-black/20`}>
                      {p.icon}
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-white">{p.name}</h3>
                      <p className="text-xs text-gray-500">
                        {isConnected ? "✅ Connected & Verified" : "Not Linked"}
                      </p>
                    </div>
                  </div>

                  {isConnected ? (
                    <div className="flex flex-col items-end">
                      <span className="text-xs text-emerald-400 font-semibold bg-emerald-500/10 px-3 py-1 rounded-full mb-2">Connected</span>
                      <button
                        onClick={() => handleDisconnect(p.id)}
                        disabled={!!disconnecting}
                        className="text-xs text-gray-600 hover:text-red-400 disabled:opacity-50 transition-colors"
                      >
                        {disconnecting === p.id ? "Disconnecting..." : "Disconnect"}
                      </button>
                    </div>
                  ) : (
                    <button 
                      onClick={() => handleTriggerOtp(p.id)}
                      disabled={!!connecting}
                      className="bg-white text-gray-950 font-bold px-6 py-2 rounded-xl text-sm hover:bg-gray-200 transition-all disabled:opacity-50"
                    >
                      {isActive ? "Connecting..." : "Connect"}
                    </button>
                  )}
                </div>
                {errors[p.id] && !isActive && <div className="px-6 pb-4 text-red-400 text-xs flex items-center gap-2">⚠️ {errors[p.id]}</div>}

                {/* OTP Overlay */}
                {isActive && step === "otp" && (
                  <div className="p-6 border-t border-white/5 bg-black/20 animate-slide-up">
                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-widest mb-3">
                      Enter OTP sent to +91 {phone}
                    </label>
                    <div className="flex flex-col sm:flex-row gap-3">
                      <input
                        type="text"
                        maxLength={6}
                        value={otp}
                        onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                        className="flex-1 bg-gray-800/60 border border-gray-700/50 rounded-xl px-4 py-3 text-white font-mono tracking-[0.5em] text-center text-xl focus:border-violet-500 outline-none"
                        placeholder="000000"
                        autoFocus
                      />
                      <button 
                        onClick={handleVerifyOtp}
                        disabled={isVerifying}
                        className="bg-violet-600 text-white font-bold px-8 py-3 rounded-xl hover:bg-violet-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {isVerifying ? "Verifying..." : "Verify"}
                      </button>
                    </div>
                    {errors[p.id] && <p className="mt-3 text-red-400 text-sm">⚠️ {errors[p.id]}</p>}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <footer className="mt-12 p-6 rounded-2xl bg-violet-500/5 border border-violet-500/20">
          <p className="text-xs text-gray-500 leading-relaxed">
            🛡️ Your privacy is our priority. CartIQ stores platform sessions securely only to perform automated searches and checkouts. We never share your personal data with third parties.
          </p>
        </footer>
      </div>
    </main>
  );
}
