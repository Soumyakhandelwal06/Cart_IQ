"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SignupPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/auth/login");
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="w-10 h-10 border-4 border-violet-500/20 border-t-violet-500 rounded-full animate-spin" />
    </div>
  );
}
