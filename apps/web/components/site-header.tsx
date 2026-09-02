"use client";

import { Code2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

import styles from "./site-header.module.css";

type ActivePage = "home" | "about" | "contact";

const SOURCE_URL = "https://github.com/kenchengkc/the-financial-document-retrieval-engine";
const HOME_VISIBLE_RATIO = 0.15;

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
    if (!onHome) return;

    const hero = document.getElementById("top");
    const research = document.querySelector<HTMLElement>(".home-research");
    if (!hero || !research) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setResearchActive(entry.intersectionRatio < HOME_VISIBLE_RATIO);
      },
      { threshold: [HOME_VISIBLE_RATIO] },
    );
    observer.observe(hero);

    let frame: number | null = null;
    if (window.location.hash === "#research") {
      frame = window.requestAnimationFrame(() => {
        setResearchActive(true);
        research.scrollIntoView({ block: "start" });
      });
    }

    return () => {
      observer.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [onHome]);

  return (
    <header className={`hd-nav${tone === "light" ? " light" : ""} ${styles.header}`}>
      <Link
        className={`hd-brand ${styles.brand}`}
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

      <nav className={`hd-links ${styles.links}`} aria-label="Site">
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

      <div className={`hd-right ${styles.right}`}>
        <a
          className={`hd-pill ${styles.source}`}
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
