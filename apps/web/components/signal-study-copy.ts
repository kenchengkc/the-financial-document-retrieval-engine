import type { SignalStudyResponse } from "@/lib/types";

export type StudyCopy = {
  headlinePrefix: string;
  headlineAccent: string;
  headlineSuffix: string;
  lede: string;
  leftAxis: string;
  rightAxis: string;
  note: string;
  desk: string[];
};

export type ConstituentCopy = {
  description: string;
  longTitle: string;
  shortTitle: string;
  footer: string;
};

const CONSTITUENT_COPY: Record<string, ConstituentCopy> = {
  earnings_quality: {
    description:
      "The current highest- and lowest-quality names, ranked by operating cash flow minus net income over average assets on each issuer's most recent 10-K.",
    longTitle: "Cash-backed · top quality",
    shortTitle: "Accrual-heavy · watch quality",
    footer: "Cash conversion = (operating cash flow - net income) / average assets.",
  },
  operating_profitability: {
    description:
      "Operating income scaled by average assets, using annual XBRL facts available when each filing was accepted.",
    longTitle: "Efficient · high profitability",
    shortTitle: "Weak · low profitability",
    footer: "Operating profitability = operating income / average assets.",
  },
  operating_margin_momentum: {
    description:
      "The latest year-over-year change in operating margin, calculated from comparative annual facts in the same 10-K.",
    longTitle: "Improving · positive inflection",
    shortTitle: "Deteriorating · negative inflection",
    footer: "Margin momentum = current operating margin - prior operating margin.",
  },
  asset_growth: {
    description:
      "A higher score means more disciplined year-over-year asset growth from each issuer's most recent 10-K.",
    longTitle: "Shrinking · disciplined",
    shortTitle: "Expanding · watch integration",
    footer: "Score = negative year-over-year asset growth, using comparative facts from the same 10-K.",
  },
  net_share_issuance: {
    description:
      "A higher score means the issuer reduced its reported common share count. Common shares outstanding are preferred, with annual diluted weighted-average shares as fallback.",
    longTitle: "Net buybacks · shrinking count",
    shortTitle: "Net issuers · rising count",
    footer: "Score = negative year-over-year share-count growth from the same 10-K.",
  },
};

export function constituentCopy(signalName: string) {
  return CONSTITUENT_COPY[signalName];
}

export function outcomeName(study: SignalStudyResponse) {
  return study.report.outcome_name ?? "abnormal_return";
}

export function studyCopy(study: SignalStudyResponse): StudyCopy {
  if (study.report.signal_name === "composite") {
    return {
      headlinePrefix: "Can combining weak signals ",
      headlineAccent: "beat any single one",
      headlineSuffix: "?",
      lede:
        "Three point-in-time filing signals (disclosure similarity, net risk-factor expansion, and filing lateness) are each z-scored within their filing period and sector (cross-sectionally neutral, with a period fallback where a sector is thin), sign-aligned, and averaged into one composite. The Fundamental Law of Active Management (IR ≈ IC × √breadth) says uncorrelated signals combine into more information than any single one.",
      leftAxis: "← composite bearish",
      rightAxis: "composite bullish →",
      note:
        "The components are genuinely uncorrelated, which is the prerequisite for combination, but individually weak and sign-unstable across horizons, so naive equal-weighting does not beat the best single signal here. Sector-neutralizing the cross-section shrinks the raw ICs: part of a single signal's apparent edge was a sector tilt, not issuer-specific information. The realistic levers are breadth and IC-weighting the components out-of-sample, not a free lunch from averaging.",
      desk: [
        "IC-weight the sleeves, not equal-weight: weight each component by its out-of-sample rank skill so the weakest signal stops dragging the blend.",
        "Breadth over conviction: at ~500 names the Fundamental Law says many small tilts beat a few large bets. Apply the composite as basis-point overweights across the whole book.",
        "Keep it sector-neutral (as here), so the tilt expresses issuer-specific information instead of a hidden sector bet.",
      ],
    };
  }

  const definition = study.report.definition;
  if (definition) {
    const isVolatility = outcomeName(study) === "realized_volatility";
    const qualityReading =
      study.report.quality?.reason ??
      "This result is a versioned research hypothesis, not a production trading claim.";
    return {
      headlinePrefix: "Does ",
      headlineAccent: definition.label.toLowerCase(),
      headlineSuffix: isVolatility ? " rank forward risk?" : " rank forward returns?",
      lede: `${definition.thesis} The point-in-time feature is ${definition.formula.toLowerCase()}, computed from ${definition.source.toLowerCase()}.`,
      leftAxis: `← lower ${definition.label.toLowerCase()}`,
      rightAxis: `higher ${definition.label.toLowerCase()} →`,
      note: `${qualityReading} The universe follows indexed issuer coverage rather than a historical constituent file; return studies are gross of costs and borrow.`,
      desk: [
        "Evidence review: inspect the extreme constituents and trace every score to its source filing before assigning an economic interpretation.",
        "Portfolio research: use sector-period neutral ranks so an apparent effect is not a disguised industry or reporting-calendar exposure.",
        "Falsification: require stable direction, monotonic quantiles, and walk-forward replication before allocating risk.",
      ],
    };
  }

  if (study.report.signal_name === "earnings_quality") {
    return {
      headlinePrefix: "Are earnings backed by ",
      headlineAccent: "real cash",
      headlineSuffix: " rewarded?",
      lede:
        "A point-in-time replication of the accruals anomaly (Sloan, 1996). For each 10-K we compute balance-sheet accruals, defined as (net income − operating cash flow) ÷ total assets, straight from the reported XBRL facts. Low accruals mean profits are backed by cash rather than accounting estimates; high accruals have historically preceded weaker returns. Filings are sorted into 5 groups by accrual quality and tracked forward.",
      leftAxis: "← low-quality (high accruals)",
      rightAxis: "high-quality (low accruals) →",
      note:
        "Accruals is a real, published fundamental factor, but in this survivorship-biased S&P 500 large-cap sample it shows no standalone edge after winsorizing forward returns at the 2.5/97.5th percentile. The anomaly is historically strongest in smaller, less-liquid names. Two cautions on the current constituents: banks carry large working-capital swings that inflate accruals for non-quality reasons, and hyper-growth firms build inventory and receivables ahead of sales, so a high reading there reflects expansion, not distress.",
      desk: [
        "Negative screen, not a long engine: historically most of the accrual anomaly's payoff came from the short leg. Desks exclude or underweight the worst-accrual quintile rather than chase the best.",
        "Defensive overlay: quality factors earn most of their keep in drawdowns (Asness–Frazzini–Pedersen's Quality-Minus-Junk), so a cash-backed-earnings tilt is sized as downside insurance, not alpha.",
        "Sector-adjust before acting: financials and hyper-growth names read low-quality for structural reasons, so raw accruals get neutralized against sector peers first.",
      ],
    };
  }

  if (study.report.signal_name === "asset_growth") {
    return {
      headlinePrefix: "Does a ",
      headlineAccent: "growing balance sheet",
      headlineSuffix: " predict weaker returns?",
      lede:
        "A point-in-time test of the asset growth anomaly (Cooper, Gulen & Schill, 2008), one of the few anomalies documented to survive in large caps. Each 10-K reports the current and prior-year balance sheet, so year-over-year total-asset growth is computable the day the filing lands. Historically, aggressive balance-sheet expansion through acquisitions or capacity build-outs preceded weaker returns.",
      leftAxis: "← high growth (expanding)",
      rightAxis: "low growth (disciplined) →",
      note:
        "In this 2023–26 window the classic effect does not replicate. If anything, it leans the other way because the market paid up for balance-sheet expansion during the AI capex cycle (NVDA grew assets 85% and kept outperforming), and the extreme-growth tail is dominated by completed acquisitions (SNPS+Ansys, AMCR+Berry) rather than empire-building. A one-regime sample cannot reject a factor documented over 40 years; it can tell you the regime.",
      desk: [
        "Regime filter first: the anomaly's premise (expansion destroys value) held in normal regimes but inverted during the AI capex boom. Desks condition the tilt on the capex cycle before deploying.",
        "M&A integration flag: the extreme-growth tail is mostly closed deals. These names are more useful routed to event-driven coverage as integration risks than naively shorted.",
        "Condition on funding: expansion funded by operating cash flow behaves differently from expansion funded by issuance. Cross this signal with share issuance (next tab) before tilting.",
      ],
    };
  }

  if (study.report.signal_name === "net_share_issuance") {
    return {
      headlinePrefix: "Do ",
      headlineAccent: "buybacks beat issuers",
      headlineSuffix: "?",
      lede:
        "A point-in-time test of the net share issuance anomaly (Pontiff & Woodgate, 2008): firms shrinking their share count historically outperformed net issuers, an effect documented as robust even in large caps. Year-over-year change in weighted diluted shares comes straight from each 10-K's income statement, knowable at acceptance.",
      leftAxis: "← net issuers (dilution)",
      rightAxis: "net buybacks (shrinking) →",
      note:
        "This window produced the study's most interesting result: a statistically significant one-month effect (adjusted p ≈ 0.02) in the OPPOSITE direction of the literature. The biggest issuers outperformed buyback names. Look at who the issuers are: merger completions (Paramount–Skydance, Expand Energy, IP–DS Smith) and recovering turnarounds (Carvana issued 70% more shares and was one of the market's best performers). In 2023–26, big issuance marked corporate events the market rewarded, not value destruction. A significant inversion is information because it tells you the naive factor would have lost money this regime.",
      desk: [
        "Treat large issuance as an event flag, not a factor score: 40%+ share-count jumps are deal closes and recapitalizations. Route them to event-driven and merger-arb coverage.",
        "The buyback side still matters as carry: consistent net-buyback names compound per-share value slowly. Desks hold it as a small, long-horizon tilt rather than a timing signal.",
        "Inversion risk management: when a documented anomaly flips sign with significance, factor desks cut the sleeve's risk budget and investigate crowding/regime before re-arming it.",
      ],
    };
  }

  if (study.report.signal_name === "filing_lateness") {
    return {
      headlinePrefix: "Does filing later signal ",
      headlineAccent: "unresolved operating risk",
      headlineSuffix: "?",
      lede:
        "Each filing is scored by the elapsed days from fiscal period end to public acceptance, using only timestamps known when the filing arrived. The cross-section tests whether slower reporting is associated with weaker benchmark-adjusted returns or higher subsequent volatility.",
      leftAxis: "← faster reporters",
      rightAxis: "slower reporters →",
      note:
        "Reporting delay is a useful operational-risk feature, but raw delay also reflects filer status, form type, fiscal calendar, and transaction complexity. A production sleeve should neutralize those mechanical deadline effects and validate stability out of sample before assigning a directional interpretation.",
      desk: [
        "Exception queue: flag issuers whose delay widens versus their own history, then route them for accounting, control, or transaction review.",
        "Event-risk sizing: a late filing can raise uncertainty even without a return edge, supporting smaller pre-event exposure or wider risk limits.",
        "Composite input: combine standardized lateness with language change and risk-factor expansion so no single noisy disclosure feature dominates.",
      ],
    };
  }

  if (
    study.report.signal_name === "risk_factor_expansion" &&
    outcomeName(study) === "realized_volatility"
  ) {
    return {
      headlinePrefix: "Do expanded risk factors predict ",
      headlineAccent: "higher volatility",
      headlineSuffix: "?",
      lede:
        "Each filing is scored by net risk-factor expansion versus the prior comparable filing: added risk passages minus removed passages, knowable at acceptance. Quantiles are then tested against forward realized daily-return volatility.",
      leftAxis: "← fewer added risks",
      rightAxis: "more added risks →",
      note:
        "This is a reproducible risk-monitoring signal, not a trading claim. The outcome is raw realized volatility over each window; inference is bootstrap-based and remains sample-size sensitive.",
      desk: [
        "Position sizing input: forward volatility is the denominator of inverse-vol weighting, so names with big net risk-factor expansions get mechanically smaller weights at the next rebalance.",
        "Hedging trigger: predicted volatility without a return edge argues for buying protection (puts, collars) on affected names rather than selling the position.",
        "Vol relative value: a filing-implied vol signal knowable at acceptance is exactly the kind of input options desks compare against implied vol to find rich/cheap protection.",
      ],
    };
  }

  if (study.report.signal_name === "risk_factor_expansion") {
    return {
      headlinePrefix: "Do newly disclosed risks predict ",
      headlineAccent: "future underperformance",
      headlineSuffix: "?",
      lede:
        "Each filing is compared with its prior point-in-time comparable. The signal is net added Item 1A passages (additions minus removals), measured when the filing became public, then tested against benchmark-adjusted forward returns.",
      leftAxis: "← fewer added risks",
      rightAxis: "more added risks →",
      note:
        "Risk-factor expansion is partly disclosure behavior and partly real operating change. Boilerplate refreshes, acquisitions, and new regulation can all widen Item 1A without the same economic meaning, so passage-level attribution matters before this becomes a directional sleeve.",
      desk: [
        "Change triage: route the largest net additions into the filing comparison workspace and identify the exact new risk language before acting.",
        "Catalyst map: connect newly disclosed risks with upcoming earnings, litigation, refinancing, or regulatory dates for scenario analysis.",
        "Risk overlay: use expansion as a sizing or hedge input when it agrees with volatility and fundamental deterioration signals.",
      ],
    };
  }

  return {
    headlinePrefix: "Do filings that ",
    headlineAccent: "change their language",
    headlineSuffix: " underperform?",
    lede:
      "A no-lookahead replication of the Lazy Prices anomaly (Cohen, Malloy & Nguyen, 2020). Each filing is scored by its disclosure similarity to the prior comparable filing, knowable only at acceptance, then sorted into quantiles.",
    leftAxis: "← revised filings underperform",
    rightAxis: "unchanged outperform →",
    note:
      "The signal is directionally consistent with Lazy Prices at short horizons but remains sample-size sensitive. Returns are market-adjusted gross of transaction costs and ignore borrow; the universe is survivorship-biased.",
    desk: [
      "Analyst triage: bottom-decile similarity (heavily revised filings) is a same-day reading list. The language changed for a reason, and someone should know why before the market does.",
      "Composite ingredient: too weak alone, but uncorrelated with risk-expansion and lateness. That is exactly the profile worth z-scoring into a multi-signal blend (see Composite tab).",
      "Event-risk sizing: a heavily revised filing marks elevated idiosyncratic risk. Trim size or widen risk limits into the next print rather than taking a directional view.",
    ],
  };
}
