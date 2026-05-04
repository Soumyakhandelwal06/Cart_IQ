import type { Metadata } from "next";
import "./globals.css";
import ThemeToggle from "@/components/ThemeToggle";
import { AuthProvider } from "@/context/AuthContext";

export const metadata: Metadata = {
  title: "CartIQ — Find the Cheapest Grocery Delivery Instantly",
  description:
    "Compare grocery prices across Zepto, Blinkit and Bigbasket in seconds. AI-powered search, real-time cart comparison, and one-tap checkout.",
  keywords: ["quick commerce", "grocery comparison", "Zepto", "Blinkit", "Bigbasket", "cheapest delivery"],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* Prevent theme flash — runs before React hydrates */}
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                var t = localStorage.getItem('qc-theme') || 'dark';
                document.documentElement.setAttribute('data-theme', t);
              } catch(e) {
                document.documentElement.setAttribute('data-theme', 'dark');
              }
            `,
          }}
        />
      </head>
      <body className="antialiased" suppressHydrationWarning>
        <AuthProvider>
          {/* Global theme toggle — fixed top-right on every page */}
          <div className="fixed top-6 right-6 z-[200]">
            <ThemeToggle />
          </div>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
