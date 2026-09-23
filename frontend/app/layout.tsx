import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Career Agent",
  description: "Job matches, profile evidence and applications",
  robots: { index: false, follow: false },
};

// Applies a saved light/dark choice before first paint (no flash). Storage can be unavailable; that is fine.
const THEME_INIT = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
