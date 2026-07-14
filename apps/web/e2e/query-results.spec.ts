import { expect, test } from "@playwright/test";

const question = "What did META report for earnings last quarter?";

async function mockHealthAndCoverage(page: import("@playwright/test").Page) {
  await page.route("**/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    }),
  );
  await page.route("**/coverage", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        catalog_count: 5794,
        sp500_catalog_count: 499,
        indexed_count: 499,
        sp500_indexed_count: 499,
        document_count: 997,
        chunk_count: 1072194,
        indexed_tickers: ["META"],
      }),
    }),
  );
}

async function mockApi(page: import("@playwright/test").Page) {
  await mockHealthAndCoverage(page);
  await page.route("**/answer", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer_run_id: 42,
        question,
        rewritten_queries: [question],
        route: ["text", "tables", "financial_facts"],
        answer:
          "Net income was $26.77 billion, with diluted earnings per share of $10.44 for the quarter.",
        confidence: 0.82,
        abstained: false,
        abstention_reason: null,
        evidence: [
          {
            chunk_id: 659326,
            text:
              "A securities class action referenced historical earnings disclosures and was dismissed.",
            metadata: {
              ticker: "META",
              form_type: "10-Q",
              filing_date: "2026-04-30",
              section: "Legal Proceedings",
              element_type: "text",
            },
            dense_score: 0.74,
            sparse_score: 0.66,
            hybrid_score: 0.79,
            rerank_score: 0.84,
            rank: 1,
          },
          {
            chunk_id: 659396,
            text:
              "Net income was $26.77 billion, with diluted earnings per share (EPS) of $10.44 for the three months ended March 31, 2026.",
            metadata: {
              ticker: "META",
              form_type: "10-Q",
              filing_date: "2026-04-30",
              section: "MD&A",
              element_type: "text",
            },
            dense_score: 0.71,
            sparse_score: 0.64,
            hybrid_score: 0.77,
            rerank_score: 0.82,
            rank: 1,
          },
          {
            chunk_id: 659187,
            text:
              "| Revenue | $56,311 million |\\n| Net income | $26,773 million |\\n| Diluted EPS | $10.44 |",
            metadata: {
              ticker: "META",
              form_type: "10-Q",
              filing_date: "2026-04-30",
              section: "Financial Statements",
              element_type: "table",
            },
            dense_score: 0.68,
            sparse_score: 0.61,
            hybrid_score: 0.72,
            rerank_score: 0.78,
            rank: 2,
          },
        ],
        citations: [
          {
            chunk_id: 659396,
            claim_text:
              "Net income was $26.77 billion, with diluted earnings per share of $10.44 for the quarter.",
            citation_text:
              "Net income was $26.77 billion, with diluted earnings per share (EPS) of $10.44 for the three months ended March 31, 2026.",
            metadata: {
              ticker: "META",
              form_type: "10-Q",
              filing_date: "2026-04-30",
            },
            confidence: 1,
          },
        ],
        financial_facts: [],
        retrieval_gate: { evidence_count: 2, max_score: 0.82, passed: true },
        trace: [
          {
            node: "preprocess_query",
            details: { filters: { tickers: ["META"], form_types: ["10-Q"], as_of: null } },
          },
          { node: "merge_candidates", details: { count: 3 } },
          { node: "rerank", details: { count: 2 } },
          { node: "verify_citations", details: { valid: true } },
        ],
        latency_ms: 1840,
      }),
    });
  });
}

test("presents a compact evidence-first result for an earnings query", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");

  await page.getByRole("textbox", { name: "Ask a financial filing question" }).fill(question);
  await page.getByRole("button", { name: "Search", exact: true }).click();

  await expect(page.getByText("Searching indexed SEC filings")).toBeVisible();
  await expect(page.getByRole("heading", { name: question })).toBeVisible();
  await expect(page.locator(".answer").getByText("$26.77 billion", { exact: false })).toBeVisible();
  await expect(page.getByText("META · 10-Q · 2026-04-30")).toBeVisible();

  const evidence = page.locator("details.evidence");
  await expect(evidence.first()).toHaveAttribute("open", "");
  await expect(evidence.first()).toContainText("$26.77 billion");
  await expect(evidence.nth(1)).not.toHaveAttribute("open", "");
  await expect(page.getByText("preprocess query")).not.toBeVisible();

  // Instrument panel: retrieval funnel, resolved scope, and session telemetry.
  await expect(page.getByText("Session telemetry")).toBeVisible();
  await expect(page.locator(".funnel")).toContainText("Retrieved");
  await expect(page.locator(".funnel")).toContainText("Cited");
  await expect(page.locator(".scope-list")).toContainText("10-Q");

  await page.getByText("Workflow trace").click();
  await expect(page.getByText("preprocess query")).toBeVisible();
});

test("labels unsupported forecast requests as no verified answer", async ({ page }) => {
  const forecastQuestion = "What will NVIDIA's stock price be next quarter?";
  await mockHealthAndCoverage(page);
  await page.route("**/answer", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer_run_id: 43,
        question: forecastQuestion,
        rewritten_queries: [forecastQuestion],
        route: ["text"],
        answer: null,
        confidence: null,
        abstained: true,
        abstention_reason:
          "FDRE does not forecast securities prices or provide trading recommendations.",
        evidence: [],
        citations: [],
        financial_facts: [],
        retrieval_gate: { evidence_count: 0, max_score: 0, passed: false },
        trace: [
          { node: "preprocess_query", details: { filters: { tickers: ["NVDA"] } } },
          {
            node: "evaluate_retrieval_gate",
            details: {
              passed: false,
              reason: "FDRE does not forecast securities prices or provide trading recommendations.",
            },
          },
        ],
        latency_ms: 320,
      }),
    }),
  );

  await page.goto("/");
  await expect(page.getByRole("button", { name: /no forecasts Unsupported request/i }))
    .toBeVisible();
  await page
    .getByRole("textbox", { name: "Ask a financial filing question" })
    .fill(forecastQuestion);
  await page.getByRole("button", { name: "Search", exact: true }).click();

  await expect(page.getByText("No verified answer")).toBeVisible();
  await expect(page.locator(".notice.abstain")).toContainText(
    "FDRE does not forecast securities prices",
  );
  await expect(page.getByText("FDRE abstained")).not.toBeVisible();
  await expect(page.getByText("No answer")).toBeVisible();
});

test("keeps the earnings result within a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("textbox", { name: "Ask a financial filing question" }).fill(question);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: question })).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
});

test("shows measured research artifacts on the About page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/about");

  await expect(page.getByRole("heading", { name: "Research infrastructure that shows its work" }))
    .toBeVisible();
  // The corpus counts are read live (ISR), so assert the stable labels, not values.
  await expect(page.getByText("S&P 500 primary tickers indexed")).toBeVisible();
  await expect(page.getByText("Six public demonstrations")).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
});
