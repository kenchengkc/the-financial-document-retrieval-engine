import type { Metadata } from "next";
import { Libre_Franklin, Newsreader } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
import "./research-console.css";

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
        {children}
        <Analytics />
      </body>
    </html>
  );
}
