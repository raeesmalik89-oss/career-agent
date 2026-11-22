import type { NextConfig } from "next";

// The browser only ever talks to this origin. /api/* is proxied to FastAPI, so the httpOnly,
// SameSite=strict session cookies work and no token is ever readable by page JavaScript.
// Some hosts (e.g. Render internal networking) expose the API as a bare "host:port" with no scheme;
// default such values to http:// so the rewrite destination below is always a valid absolute URL.
const RAW_BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const BACKEND_URL = /^https?:\/\//.test(RAW_BACKEND_URL) ? RAW_BACKEND_URL : `http://${RAW_BACKEND_URL}`;
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const config: NextConfig = {
  poweredByHeader: false,
  // Self-contained server for the Docker image (frontend/Dockerfile); `npm run dev` is unaffected.
  output: "standalone",
  // the dev-only Next.js badge would sit on top of the sidebar account card (bottom-left)
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
