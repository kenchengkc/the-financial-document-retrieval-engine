import { expect, test, type Page } from "@playwright/test";

async function mockBase(page: Page) {
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
  );
  await page.route("**/coverage", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        catalog_count: 5794,
        sp500_catalog_count: 499,
        indexed_count: 495,
        sp500_indexed_count: 495,
        document_count: 997,
        chunk_count: 1065227,
        indexed_tickers: ["AAPL"],
      }),
    }),
  );
}

function candidate(date: string, form: string, chunkId: number) {
  return {
    chunk_id: chunkId,
    text: "Services revenue grew on the strength of the installed base.",
    metadata: { ticker: "AAPL", form_type: form, filing_date: date, section: "MD&A", element_type: "text" },
    dense_score: 0.51,
    sparse_score: 0.4,
    hybrid_score: 0.55,
    rerank_score: 0.69,
    rank: 1,
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth);
}

async function expectNoBoxOverlap(page: Page, leftSelector: string, rightSelector: string) {
  const overlap = await page.evaluate(
    ([left, right]) => {
      const first = document.querySelector(left);
      const second = document.querySelector(right);
      if (!first || !second) return true;
      const a = first.getBoundingClientRect();
      const b = second.getBoundingClientRect();
      return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
    },
    [leftSelector, rightSelector],
  );
  expect(overlap).toBe(false);
}

test("runs a point-in-time retrieval and forwards the as-of filter", async ({ page }) => {
  await mockBase(page);
  let sentBody: { filters?: { as_of?: string } } = {};
  await page.route("**/search", async (route) => {
    sentBody = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "services revenue growth",
        rewritten_queries: ["services revenue growth"],
        filters: {},
        results: [candidate("2025-10-31", "10-K", 1), candidate("2025-10-31", "10-K", 2)],
        latency_ms: 1100,
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await expect(page.getByRole("heading", { name: "Retrieve", exact: true })).toBeVisible();

  await page.getByLabel("Search query").fill("services revenue growth");
  await page.getByLabel("As-of date").fill("2026-01-01");
  await page.locator(".retrieve-form button[type=submit]").click();

  await expect(page.locator(".rr-summary")).toContainText("Knowable as of 2026-01-01");
  await expect(page.locator(".retrieve-results .evidence").first()).toBeVisible();
  expect(sentBody.filters?.as_of).toBe("2026-01-01T00:00:00+00:00");
});

test("keeps AAPL search controls from overlapping on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBase(page);
  await page.route("**/search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "What is AAPL's current product line",
        rewritten_queries: ["What is AAPL's current product line"],
        filters: {},
        results: [candidate("2025-10-31", "10-K", 1)],
        latency_ms: 900,
      }),
    }),
  );

  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Ask a financial filing question" })
    .fill("What is AAPL's current product line");
  await expectNoBoxOverlap(page, "#question", ".hd-search .go");
  await expectNoHorizontalOverflow(page);

  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await page.getByLabel("Search query").fill("What is AAPL's current product line");
  await expectNoBoxOverlap(page, ".rf-query input", ".rf-query button");
  await expectNoHorizontalOverflow(page);

  await page.locator(".retrieve-form button[type=submit]").click();
  await expect(page.locator(".retrieve-results .evidence").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("renders the coverage universe in the data foundation", async ({ page }) => {
  await mockBase(page);
  await page.route("**/companies**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 2,
        companies: [
          { ticker: "KKR", cik: "1", name: "KKR & Co. Inc.", exchange: "NYSE", document_count: 2, chunk_count: 14849, indexed: true },
          { ticker: "AAPL", cik: "2", name: "Apple Inc.", exchange: "Nasdaq", document_count: 2, chunk_count: 1053, indexed: true },
        ],
      }),
    }),
  );

  await page.goto("/");
  await expect(page.locator(".data-foundation")).toContainText("Data foundation");
  await expect(page.locator(".foundation-company").first()).toContainText("KKR");
});

test("renders the published signal study", async ({ page }) => {
  await mockBase(page);
  const disclosureStudy = {
    experiment_id: 1,
    experiment_key: "abc",
    code_sha: "deadbeef",
    created_at: "2026-06-20T06:12:36Z",
    report: {
      signal_name: "disclosure_similarity",
      outcome_name: "abnormal_return",
      n_quantiles: 5,
      event_count: 241,
      dataset_version: "dataset-a17f",
      feature_version: "fdre-panel-v1",
      config: {
        benchmark_ticker: "SPY",
        confidence_level: 0.95,
        bootstrap_iterations: 2000,
        random_seed: 17,
        market_timezone: "America/New_York",
        market_close: "16:00",
      },
      results: [
        {
          window: "0:1",
          sample_size: 241,
          information_coefficient: 0.0771,
          ic_t_stat: 1.2,
          quantiles: [
            { quantile: 1, sample_size: 48, mean_abnormal_return: -0.0005 },
            { quantile: 2, sample_size: 48, mean_abnormal_return: -0.0016 },
            { quantile: 3, sample_size: 48, mean_abnormal_return: -0.0051 },
            { quantile: 4, sample_size: 48, mean_abnormal_return: 0.0003 },
            { quantile: 5, sample_size: 49, mean_abnormal_return: 0.0016 },
          ],
          long_short_mean: 0.0021,
          long_short_ci_low: -0.0083,
          long_short_ci_high: 0.0121,
          long_short_p_value: 0.04,
          long_short_adjusted_p_value: 0.12,
        },
      ],
    },
  };
  const riskStudy = {
    ...disclosureStudy,
    experiment_id: 2,
    experiment_key: "risk",
    report: {
      ...disclosureStudy.report,
      signal_name: "risk_factor_expansion",
      outcome_name: "realized_volatility",
      event_count: 188,
    },
  };
  await page.route("**/research/signal-studies", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ studies: [disclosureStudy, riskStudy] }),
    }),
  );
  await page.route("**/research/signal-study", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(disclosureStudy),
    }),
  );

  await page.goto("/");
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.locator(".sig-stats")).toContainText("Filing events");
  await expect(page.locator(".sig-card").first()).toContainText("Filing day");
  // raw p=0.04 would read significant; the UI must use the BH-adjusted p=0.12 -> "No edge".
  await expect(page.locator(".sig-card").first()).toContainText("No edge");
  await expect(page.locator(".sig-summary")).toContainText("p = 0.12");
  await page.getByRole("tab", { name: /Risk expansion/ }).click();
  await expect(page.locator(".panel-intro")).toContainText("higher volatility");
  await expect(page.locator(".sig-stats")).toContainText("Volatility");

  await page.getByRole("tab", { name: "Monitor" }).click();
  await expect(page.locator(".monitor-table")).toContainText("Disclosure similarity");
  await expect(page.locator(".feature-library")).toContainText("Filing lateness");
  await expect(page.locator(".feature-library")).toContainText("Backtest-ready");

  await page.getByRole("tab", { name: "Audit" }).click();
  await expect(page.locator(".audit-manifest")).toContainText("dataset-a17f");
  await expect(page.locator(".audit-gates")).toContainText("Benjamini–Hochberg");
});

test("compares a filing to its point-in-time comparable", async ({ page }) => {
  await mockBase(page);
  let requestUrl = "";
  await page.route("**/research/filing-differences/**", (route) => {
    requestUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        company_ticker: "AAPL",
        current_accession: "0000320193-25-000079",
        previous_accession: "0000320193-24-000123",
        current_available_at: "2025-10-31T16:05:00Z",
        previous_available_at: "2024-11-01T16:05:00Z",
        comparison_basis: "prior_annual_period",
        added_count: 1,
        removed_count: 0,
        materially_changed_count: 1,
        changes: [
          {
            change_type: "materially_changed",
            section: "Item 1A · Risk Factors",
            before_text: "The company may experience supply constraints.",
            after_text: "The company experienced supply and capacity constraints.",
            before_fingerprint: "old",
            after_fingerprint: "new",
            similarity: 0.74,
          },
        ],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await page.getByRole("tab", { name: "Filing delta" }).click();
  await page.getByLabel("Filing accession number").fill("0000320193-25-000079");
  await page.getByLabel("Filing delta as-of date").fill("2025-12-31");
  await page.getByRole("button", { name: "Compare" }).click();

  await expect(page.locator(".delta-stats")).toContainText("Rewritten");
  await expect(page.locator(".delta-change")).toContainText("Item 1A · Risk Factors");
  await expect(page.locator(".delta-result")).toContainText("point-in-time gate passed");
  expect(requestUrl).toContain("as_of=2025-12-31T23%3A59%3A59%2B00%3A00");
});

test("queries original-vintage facts and builds a leakage-checked panel", async ({ page }) => {
  await mockBase(page);
  await page.route("**/research/facts**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: {},
        facts: [
          {
            ticker: "MSFT",
            canonical_metric: "revenue",
            concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
            label: "Revenue",
            value: "245122000000",
            unit: "USD",
            period_start: "2024-07-01",
            period_end: "2025-06-30",
            period_type: "duration",
            fiscal_year: 2025,
            fiscal_period: "FY",
            form_type: "10-K",
            accession_number: "0000950170-25-000001",
            filed_at: "2025-07-30",
            available_at: "2025-07-30T16:10:00Z",
            is_amendment: false,
            is_restatement: false,
            source_url: null,
            narrative_evidence: null,
          },
        ],
      }),
    }),
  );
  await page.route("**/research/panel?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: {},
        feature_version: "fdre-panel-v1",
        corpus_snapshot_id: "a17f4d8c9321b445",
        rows: [
          {
            ticker: "MSFT",
            cik: "789019",
            accession_number: "0000950170-25-000001",
            form_type: "10-K",
            period_end: "2025-06-30",
            accepted_at: "2025-07-30T16:10:00Z",
            available_at: "2025-07-30T16:10:00Z",
            is_amendment: false,
            filing_length_tokens: 45000,
            disclosure_similarity: 0.91,
            risk_added_passages: 4,
            risk_removed_passages: 2,
            table_density: 0.08,
            numeric_density: 0.12,
            filing_delay_days: 30,
            revenue_growth: 0.15,
            operating_margin: 0.44,
            net_margin: 0.36,
            capex_to_revenue: 0.26,
            operating_cash_flow_to_revenue: 0.56,
            source_accessions: ["0000950170-25-000001"],
            feature_provenance: {},
            calculation_version: "fdre-panel-v1",
            corpus_snapshot_id: "a17f4d8c9321b445",
            max_source_available_at: "2025-07-30T16:10:00Z",
          },
        ],
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await page.getByRole("tab", { name: "Fact tape" }).click();
  await page.getByLabel("Fact tape tickers").fill("MSFT");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.locator(".facts-table")).toContainText("245.12B");
  await expect(page.locator(".facts-result")).toContainText("original-vintage values");

  await page.getByRole("tab", { name: "Panel export" }).click();
  await page.getByLabel("Panel tickers").fill("MSFT");
  await page.getByRole("button", { name: "Build preview" }).click();
  await expect(page.locator(".panel-manifest")).toContainText("fdre-panel-v1");
  await expect(page.locator(".panel-manifest")).toContainText("Passed");
  await expect(page.locator(".panel-table")).toContainText("44.0%");
});

test("renders live data quality in the data foundation", async ({ page }) => {
  await mockBase(page);
  await page.route("**/operations/quality**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: "2026-06-14T18:50:29Z",
        company_count: 500,
        document_count: 997,
        chunk_count: 1072194,
        embedding_count: 1065227,
        stale_after_days: 150,
        stale_tickers: ["EXMPL"],
        missing_expected_filings: [],
        duplicate_accession_groups: 0,
        documents_without_chunks: 0,
        unchunked_documents: [],
        chunks_without_embeddings: 6967,
        facts_without_documents: 0,
        freshness_ratio: 0.996,
        document_chunk_coverage: 1.0,
        embedding_coverage: 0.9935,
        recent_ingestion_success_rate: 1.0,
        latest_ingestion_completed_at: "2026-06-14T10:12:55Z",
      }),
    }),
  );

  await page.goto("/");
  await expect(page.locator(".foundation-meters")).toContainText("Embedding coverage");
  await expect(page.locator(".foundation-ops")).toContainText("missing embeddings");
});
