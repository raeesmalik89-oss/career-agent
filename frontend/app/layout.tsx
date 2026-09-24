import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Self-hosted at build time by Next (no request to Google from the browser, so the CSP stays 'self').
const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter" });

export const metadata: Metadata = {
  title: { default: "Career Agent", template: "%s · Career Agent" },
  description: "Job matches, profile evidence and applications",
  robots: { index: false, follow: false },
};

// Applies a saved light/dark choice before first paint (no flash). Storage can be unavailable; that is fine.
const THEME_INIT = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
