import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://thefdre.com"),
  title: "FDRE — Financial Document Retrieval Engine",
  description:
    "FDRE searches, ranks, and verifies evidence across SEC filings, financial tables, and structured company facts. Not a chatbot over documents — a retrieval engine with citations, evals, and abstention.",
  openGraph: {
    title: "FDRE — Financial Document Retrieval Engine",
    description:
      "Layout-aware search, hybrid retrieval, citation verification, and abstention over SEC filings.",
    url: "https://thefdre.com",
    siteName: "FDRE",
    type: "website",
  },
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%233ddc97'/><text x='16' y='23' font-family='monospace' font-size='20' font-weight='700' fill='%2304140d' text-anchor='middle'>F</text></svg>",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
