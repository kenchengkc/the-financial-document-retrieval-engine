import type { Metadata } from "next";
import { Libre_Franklin, Newsreader } from "next/font/google";
import Script from "next/script";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
import "./research-console.css";
import "./ask-ui-fixes.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-display",
});

const libreFranklin = Libre_Franklin({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://thefdre.com"),
  title: "FDRE | SEC Research Infrastructure",
  description:
    "SEC filing search, financial data, filing comparisons, and historical research exports with cited sources.",
  openGraph: {
    title: "FDRE | SEC Research Infrastructure",
    description:
      "SEC filing search, reported financial data, filing changes, and historical research data.",
    url: "https://thefdre.com",
    siteName: "FDRE",
    type: "website",
  },
};

const FOUNDATION_CACHE_MIGRATION = `
try {
  const migrationKey = "fdre.foundation.cache-migration";
  const migrationVersion = "sp500-primary-universe-v2";
  if (window.localStorage.getItem(migrationKey) !== migrationVersion) {
    window.localStorage.removeItem("fdre.foundation.v1");
    window.localStorage.setItem(migrationKey, migrationVersion);
  }
} catch {}
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${libreFranklin.variable}`}
    >
      <body>
        <Script id="foundation-cache-migration" strategy="beforeInteractive">
          {FOUNDATION_CACHE_MIGRATION}
        </Script>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
