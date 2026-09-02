"use client";

import { Code2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

type ActivePage = "home" | "about" | "contact";

const SOURCE_URL = "https://github.com/kenchengkc/the-financial-document-retrieval-engine";

export function SiteHeader({
  tone = "light",
  active,
  onResearch,
}: {
  tone?: "dark" | "light";
  active: ActivePage;
  onResearch?: () => void;
}) {
  const [researchActive, setResearchActive] = useState(false);
  const onHome = active === "home";

  useEffect(() => {
    if (!onHome || window.location.hash !== "#research") return;
    setResearchActive(true);
    window.requestAnimationFrame(() => {
      document.querySelector(".home-research")?.scrollIntoView({ block: "start" });
    });
  }, [onHome]);

  return (
    <header className={`hd-nav${tone === "light" ? " light" : ""}`}>
      <Link
        className="hd-brand"
        href={onHome ? "#top" : "/"}
        aria-label="FDRE home"
        onClick={() => setResearchActive(false)}
      >
        <Image
          className="hd-brand-img"
          src={tone === "dark" ? "/fdre-logo-white.png" : "/fdre-logo-color.png"}
          alt="FDRE"
          width={629}
          height={230}
          priority
        />
      </Link>

      <nav className="hd-links" aria-label="Site">
        <Link
          className={onHome && !researchActive ? "on" : undefined}
          href={onHome ? "#top" : "/"}
          onClick={() => setResearchActive(false)}
        >
          Home
        </Link>
        <a
          className={researchActive ? "on" : undefined}
          href={onHome ? "#research" : "/#research"}
          onClick={(event) => {
            if (!onResearch) return;
            event.preventDefault();
            setResearchActive(true);
            window.history.replaceState(null, "", "#research");
            onResearch();
          }}
        >
          Research
        </a>
        <Link className={active === "about" ? "on" : undefined} href="/about">
          About
        </Link>
        <Link className={active === "contact" ? "on" : undefined} href="/contact">
          Contact
        </Link>
      </nav>

      <div className="hd-right">
        <a
          className="hd-pill"
          href={SOURCE_URL}
          target="_blank"
          rel="noreferrer"
          aria-label="Source code on GitHub"
        >
          <Code2 size={16} aria-hidden="true" />
          <span className="hd-pill-label">Source</span>
        </a>
      </div>
    </header>
  );
}
