"use client";
import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [name, setName] = useState("");
  const [isNew, setIsNew] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone || phone.length < 10) {
      setError("Please enter a valid phone number");
      return;
    }
    setIsLoading(true);
    setError("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/auth/send-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to send OTP");

      setIsNew(data.isNew);
      setStep("otp");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length !== 6) {
      setError("Please enter a 6-digit OTP");
      return;
    }
    setIsLoading(true);
    setError("");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";
      const res = await fetch(`${apiUrl}/api/v1/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, otp, name }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Verification failed");

      login(data.user, data.token);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="gradient-mesh min-h-screen flex items-center justify-center px-4 relative overflow-hidden">
      <div className="bg-orb bg-orb-1" />
      <div className="bg-orb bg-orb-2" />
      <div className="bg-grid" />

      <div className="relative z-10 w-full max-w-sm animate-slide-up">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-500 to-orange-400 flex items-center justify-center text-2xl shadow-lg shadow-violet-500/20">
              🛒
            </div>
            <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400">
              QuickCart
            </h1>
          </div>
          <h2 className="text-xl font-semibold text-white">
            {step === "phone" ? "Sign in or Signup" : "Verify Number"}
          </h2>
          <p className="text-gray-400 text-sm mt-1">
            {step === "phone" 
              ? "We'll send a 6-digit code to verify your phone" 
              : `Code sent to +91 ${phone}`}
          </p>
        </div>

        {/* Card */}
        <div className="bg-gray-900/60 backdrop-blur-2xl border border-white/10 rounded-[2rem] p-8 shadow-2xl relative overflow-hidden group">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-violet-500/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          
          <form onSubmit={step === "phone" ? handleSendOtp : handleVerifyOtp} className="space-y-6">
            {step === "phone" ? (
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase tracking-widest mb-2 ml-1">Phone Number</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500 font-medium">+91</span>
                  <input
                    type="tel"
                    required
                    maxLength={10}
                    value={phone}
                    onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
                    className="w-full bg-gray-800/40 border border-gray-700/50 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 rounded-2xl pl-14 pr-4 py-4 text-white text-lg transition-all outline-none placeholder:text-gray-600"
                    placeholder="98765 43210"
                    autoFocus
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {isNew && (
                  <div className="animate-fade-in">
                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-widest mb-2 ml-1">Full Name</label>
                    <input
                      type="text"
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full bg-gray-800/40 border border-gray-700/50 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 rounded-2xl px-4 py-4 text-white text-lg transition-all outline-none"
                      placeholder="Enter your name"
                      autoFocus={isNew}
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase tracking-widest mb-2 ml-1">6-Digit Code</label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                    className="w-full bg-gray-800/40 border border-gray-700/50 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 rounded-2xl px-4 py-4 text-white text-center text-3xl tracking-[0.5em] transition-all outline-none font-mono"
                    placeholder="000000"
                    autoFocus={!isNew}
                  />
                </div>
                <button 
                  type="button"
                  onClick={() => setStep("phone")}
                  className="mt-3 text-xs text-violet-400 hover:text-violet-300 font-medium transition-colors"
                >
                  ← Change number
                </button>
              </div>
            )}

            {error && (
              <div className="text-red-400 text-sm bg-red-950/30 border border-red-900/30 rounded-xl px-4 py-3 animate-shake flex items-center gap-2">
                <span>⚠️</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-bold py-4 rounded-2xl transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed shadow-xl shadow-violet-500/20 text-lg flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  {step === "phone" ? "Sending..." : "Verifying..."}
                </>
              ) : (
                <>
                  {step === "phone" ? "Send Code" : "Get Started"}
                  <span className="text-xl">→</span>
                </>
              )}
            </button>
          </form>
        </div>

        <p className="mt-8 text-center text-gray-500 text-xs px-6">
          By continuing, you agree to CartIQ's Terms of Service and Privacy Policy. Secure OTP verification.
        </p>
      </div>
    </main>
  );
}
