import type { Metadata } from "next";
import { Libre_Franklin, Newsreader, Public_Sans } from "next/font/google";
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

const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-lede",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://thefdre.com"),
  title: "FDRE | SEC Research Infrastructure",
  description:
    "Point-in-time SEC filing retrieval, structured financial facts, filing comparisons, and reproducible research exports with verified evidence.",
  openGraph: {
    title: "FDRE | SEC Research Infrastructure",
    description:
      "Auditable SEC retrieval, typed facts, filing changes, and point-in-time research data.",
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
      className={`${newsreader.variable} ${libreFranklin.variable} ${publicSans.variable}`}
    >
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
