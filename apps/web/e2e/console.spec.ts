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
  await expect(page.getByRole("heading", { name: /knowable-as-of boundary/i })).toBeVisible();

  await page.getByLabel("Search query").fill("services revenue growth");
  await page.getByLabel("As-of date").fill("2026-01-01");
  await page.locator(".retrieve-form button[type=submit]").click();

  await expect(page.locator(".rr-summary")).toContainText("Knowable as of 2026-01-01");
  await expect(page.locator(".retrieve-results .evidence").first()).toBeVisible();
  expect(sentBody.filters?.as_of).toBe("2026-01-01T00:00:00+00:00");
});

test("renders the coverage universe", async ({ page }) => {
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
  await page.getByRole("tab", { name: /Universe/ }).click();
  await expect(page.locator(".universe-stats")).toContainText("Indexed issuers");
  await expect(page.locator(".ut-row").first()).toContainText("KKR");
});

test("renders the published signal study", async ({ page }) => {
  await mockBase(page);
  await page.route("**/research/signal-study**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        experiment_id: 1,
        experiment_key: "abc",
        code_sha: "deadbeef",
        created_at: "2026-06-20T06:12:36Z",
        report: {
          signal_name: "disclosure_similarity",
          n_quantiles: 5,
          event_count: 241,
          config: { benchmark_ticker: "SPY", confidence_level: 0.95 },
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
              long_short_p_value: 0.686,
            },
          ],
        },
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.locator(".sig-stats")).toContainText("Filing events");
  await expect(page.locator(".sig-card").first()).toContainText("Filing day");
  await expect(page.locator(".sig-card").first()).toContainText("not significant");
});

test("renders the live data-quality dashboard", async ({ page }) => {
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
  await page.getByRole("tab", { name: /Operations/ }).click();
  await expect(page.locator(".ops-counts")).toContainText("Embeddings");
  await expect(page.locator(".cov-bar").first()).toContainText("coverage");
});
