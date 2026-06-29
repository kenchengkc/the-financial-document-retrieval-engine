import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight, Code2, Globe, Mail } from "lucide-react";

export const metadata: Metadata = {
  title: "Contact | FDRE",
  description: "Get in touch with Ken Cheng, the author of FDRE.",
};

// lucide-react dropped brand icons, so embed the GitHub / LinkedIn marks directly.
function GithubIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58 0-.29-.01-1.04-.02-2.05-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.95 0-1.31.47-2.39 1.24-3.23-.12-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.24 2.87.12 3.18.77.84 1.24 1.92 1.24 3.23 0 4.62-2.81 5.64-5.49 5.94.43.37.81 1.1.81 2.22 0 1.6-.01 2.89-.01 3.29 0 .32.22.7.83.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z" />
    </svg>
  );
}

function LinkedinIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.07 2.07 0 1 1 0-4.14 2.07 2.07 0 0 1 0 4.14zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

const LINKS = [
  {
    icon: Mail,
    label: "Email",
    value: "kencheng.kc8@gmail.com",
    href: "mailto:kencheng.kc8@gmail.com",
    external: false,
  },
  {
    icon: GithubIcon,
    label: "GitHub",
    value: "github.com/kenchengkc",
    href: "https://github.com/kenchengkc",
    external: true,
  },
  {
    icon: LinkedinIcon,
    label: "LinkedIn",
    value: "linkedin.com/in/kenchengkc",
    href: "https://www.linkedin.com/in/kenchengkc",
    external: true,
  },
  {
    icon: Globe,
    label: "Personal site",
    value: "kencheng.me",
    href: "https://kencheng.me",
    external: true,
  },
];

export default function Contact() {
  return (
    <div className="site-shell">
      <header className="hd-nav light">
        <Link className="hd-brand" href="/" aria-label="FDRE home">
          <Image
            className="hd-brand-img"
            src="/fdre-logo-color.png"
            alt="FDRE"
            width={629}
            height={230}
            priority
          />
        </Link>
        <nav className="hd-links" aria-label="Site">
          <Link href="/">Console</Link>
          <Link href="/about">About</Link>
          <Link className="on" href="/contact">
            Contact
          </Link>
        </nav>
        <div className="hd-right">
          <a
            className="hd-pill"
            href="https://github.com/kenchengkc/the-financial-document-retrieval-engine"
            target="_blank"
            rel="noreferrer"
          >
            <Code2 size={16} aria-hidden="true" />
            <span className="hd-pill-label">View source</span>
          </a>
        </div>
      </header>

      <main className="contact-main">
        <div className="contact-intro">
          <p className="eyebrow">Contact</p>
          <h1>Let&rsquo;s talk.</h1>
          <p className="contact-lede">
            FDRE is designed and built by <strong>Ken Cheng</strong>. Reach out about the
            project, the research, or quant/engineering roles — I&rsquo;m happy to walk through the
            architecture or the data.
          </p>
        </div>

        <div className="contact-grid">
          {LINKS.map(({ icon: Icon, label, value, href, external }) => (
            <a
              key={label}
              className="contact-card"
              href={href}
              target={external ? "_blank" : undefined}
              rel={external ? "noreferrer" : undefined}
            >
              <span className="contact-icon" aria-hidden="true">
                <Icon size={20} />
              </span>
              <span className="contact-meta">
                <span className="contact-label">{label}</span>
                <span className="contact-value">{value}</span>
              </span>
              <ArrowUpRight className="contact-arrow" size={16} aria-hidden="true" />
            </a>
          ))}
        </div>
      </main>
    </div>
  );
}
