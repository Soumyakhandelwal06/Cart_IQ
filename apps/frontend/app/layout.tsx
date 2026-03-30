import type { Metadata } from "next";
import { Inter, Outfit } from "next/font/google";
import "./globals.css";
import ThemeToggle from "@/components/ThemeToggle";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit" });

export const metadata: Metadata = {
  title: "CartIQ — Find the Cheapest Grocery Delivery Instantly",
  description:
    "Compare grocery prices across Zepto, Blinkit and Bigbasket in seconds. AI-powered search, real-time cart comparison, and one-tap checkout.",
  keywords: ["quick commerce", "grocery comparison", "Zepto", "Blinkit", "Bigbasket", "cheapest delivery"],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${outfit.variable}`} suppressHydrationWarning>
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
        {/* Global theme toggle — fixed top-right on every page */}
        <div className="fixed top-4 right-4 z-[200]">
          <ThemeToggle />
        </div>
        {children}
      </body>
    </html>
  );
}
