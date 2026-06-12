import type { Metadata } from "next";
import { Libre_Franklin, Newsreader, Public_Sans } from "next/font/google";
import "./globals.css";

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
  title: "FDRE — Financial RAG for SEC Filings",
  description:
    "Hybrid RAG over SEC filings: pgvector embeddings, PostgreSQL full-text search, LangGraph retrieval agent, reranking, verified citations, and abstention. Built for research teams, not generic chat.",
  openGraph: {
    title: "FDRE — Financial RAG for SEC Filings",
    description:
      "Vector + keyword RAG, bounded retrieval agent, and citation verification over SEC filings.",
    url: "https://thefdre.com",
    siteName: "FDRE",
    type: "website",
  },
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='9' fill='%233a8a70'/><text x='16' y='23' font-family='Georgia,serif' font-size='20' font-weight='600' fill='white' text-anchor='middle'>F</text></svg>",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        className={`${newsreader.variable} ${libreFranklin.variable} ${publicSans.variable}`}
      >
        {children}
      </body>
    </html>
  );
}
