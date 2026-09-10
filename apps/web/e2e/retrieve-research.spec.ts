import { expect, test, type Page } from "@playwright/test";

async function mockBase(page: Page) {
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
        document_count: 3204,
        chunk_count: 3039403,
        indexed_tickers: ["AAPL", "MSFT"],
      }),
    }),
  );
  await page.route("**/companies**", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/operations/quality**", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
  );
}

async function openRetrieve(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await expect(page.getByRole("heading", { name: "Retrieve", exact: true })).toBeVisible();
}

test("compares filings with the exact point-in-time cutoff", async ({ page }) => {
  await mockBase(page);
  let requestUrl = "";

  await page.route(/\/research\/filing-differences\/[^?]+/, (route) => {
    requestUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        company_ticker: "AAPL",
        current_accession: "0000320193-26-000012",
        previous_accession: "0000320193-25-000079",
        current_available_at: "2026-01-30T21:03:00Z",
        previous_available_at: "2025-10-31T20:00:00Z",
        comparison_basis: "prior_period",
        changes: [
          {
            change_type: "added",
            section: "Risk Factors",
            before_text: null,
            after_text: "New supply-chain concentration language.",
            before_fingerprint: null,
            after_fingerprint: "after-fingerprint",
            similarity: null,
          },
          {
            change_type: "materially_changed",
            section: "MD&A",
            before_text: "Prior demand commentary.",
            after_text: "Updated demand commentary.",
            before_fingerprint: "before-fingerprint",
            after_fingerprint: "changed-fingerprint",
            similarity: 0.42,
          },
        ],
        added_count: 1,
        removed_count: 0,
        materially_changed_count: 1,
      }),
    });
  });

  await openRetrieve(page);
  await page.getByRole("tab", { name: "Compare filings" }).click();
  await page.getByLabel("Filing accession number").fill("0000320193-26-000012");
  await page.getByLabel("Comparison as-of date").fill("2026-01-31");
  await page.getByRole("button", { name: "Compare filing" }).click();

  await expect(page.locator(".delta-result")).toContainText("AAPL");
  await expect(page.locator(".delta-result")).toContainText("vs. prior comparable filing");
  await expect(page.locator(".delta-result")).toContainText("as-of date check passed");
  await expect(page.locator(".delta-stats")).toContainText("2");
  await expect(page.locator(".delta-change").first()).toContainText(
    "New supply-chain concentration language.",
  );

  expect(requestUrl).not.toBe("");
  const capturedRequest = new URL(requestUrl);
  expect(capturedRequest.pathname).toContain(
    "/research/filing-differences/0000320193-26-000012",
  );
  expect(capturedRequest.searchParams.get("as_of")).toBe("2026-01-31T23:59:59+00:00");
});

test("queries financial facts with ticker, metric, restatement, and as-of controls", async ({
  page,
}) => {
  await mockBase(page);
  let requestUrl = "";

  await page.route(/\/research\/facts(?:\?|$)/, (route) => {
    requestUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: {},
        facts: [
          {
            ticker: "AAPL",
            canonical_metric: "revenue",
            concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
            label: "Revenue",
            value: "124300000000",
            unit: "USD",
            period_start: "2025-09-28",
            period_end: "2025-12-27",
            period_type: "duration",
            fiscal_year: 2026,
            fiscal_period: "Q1",
            form_type: "10-Q",
            accession_number: "0000320193-26-000012",
            filed_at: "2026-01-30T21:03:00Z",
            available_at: "2026-01-30T21:03:00Z",
            is_amendment: false,
            is_restatement: true,
            source_url: "https://www.sec.gov/Archives/example",
            narrative_evidence: null,
          },
        ],
      }),
    });
  });

  await openRetrieve(page);
  await page.getByRole("tab", { name: "Financial facts" }).click();
  await page.getByLabel("Financial fact tickers").fill("aapl, msft");
  await page.getByLabel("Canonical metric").selectOption("revenue");
  await page.getByLabel("Restatement policy").selectOption("latest");
  await page.getByLabel("Financial fact as-of date").fill("2026-02-01");
  await page.getByRole("button", { name: "Query facts" }).click();

  const factRow = page.locator(".facts-table tbody tr");
  await expect(page.locator(".facts-result")).toContainText("1 reported facts");
  await expect(page.locator(".facts-result")).toContainText("latest");
  await expect(factRow).toContainText("AAPL");
  await expect(factRow).toContainText("revenue");
  await expect(factRow).toContainText("restated");
  await expect(factRow).toContainText("124.3B");
  await expect(factRow).toContainText("0000320193-26-000012");

  expect(requestUrl).not.toBe("");
  const capturedRequest = new URL(requestUrl);
  expect(capturedRequest.searchParams.getAll("tickers")).toEqual(["AAPL", "MSFT"]);
  expect(capturedRequest.searchParams.getAll("metrics")).toEqual(["revenue"]);
  expect(capturedRequest.searchParams.get("as_of")).toBe("2026-02-01T23:59:59+00:00");
  expect(capturedRequest.searchParams.get("restatement_policy")).toBe("latest");
  expect(capturedRequest.searchParams.get("limit")).toBe("100");
});

test("previews and exports a point-in-time research dataset without changing export limits", async ({
  page,
}) => {
  await mockBase(page);
  let previewUrl = "";
  let exportUrl = "";

  await page.route(/\/research\/panel(?:\?|$)/, (route) => {
    previewUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: {},
        feature_version: "fdre-panel-v1",
        corpus_snapshot_id: "0123456789abcdef0123456789abcdef",
        rows: [
          {
            ticker: "AAPL",
            cik: "0000320193",
            accession_number: "0000320193-26-000012",
            form_type: "10-Q",
            period_end: "2025-12-27",
            accepted_at: "2026-01-30T21:03:00Z",
            available_at: "2026-01-30T21:03:00Z",
            is_amendment: false,
            filing_length_tokens: 10000,
            disclosure_similarity: 0.812,
            risk_added_passages: 7,
            risk_removed_passages: 2,
            table_density: 0.2,
            numeric_density: 0.15,
            filing_delay_days: 34,
            revenue_growth: 0.08,
            operating_margin: 0.31,
            net_margin: 0.24,
            capex_to_revenue: 0.07,
            operating_cash_flow_to_revenue: 0.27,
            source_accessions: ["0000320193-26-000012"],
            feature_provenance: {},
            calculation_version: "v1",
            corpus_snapshot_id: "0123456789abcdef0123456789abcdef",
            max_source_available_at: "2026-01-30T21:03:00Z",
          },
        ],
      }),
    });
  });

  await page.route(/\/research\/panel\/export(?:\?|$)/, (route) => {
    exportUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "text/csv",
      headers: { "content-disposition": 'attachment; filename="fdre-test-panel.csv"' },
      body: "ticker,period_end\nAAPL,2025-12-27\n",
    });
  });

  await openRetrieve(page);
  await page.getByRole("tab", { name: "Build dataset" }).click();
  await page.getByLabel("Dataset tickers").fill("aapl msft");
  await page.getByLabel("Dataset fiscal period from").fill("2025-01-01");
  await page.getByLabel("Dataset fiscal period to").fill("2025-12-31");
  await page.getByLabel("Dataset as-of date").fill("2026-02-01");
  await page.getByLabel("Dataset row limit").fill("500");
  await page.getByRole("button", { name: "Preview dataset" }).click();

  await expect(page.locator(".panel-result")).toContainText("fdre-panel-v1");
  await expect(page.locator(".panel-table tbody tr")).toContainText("AAPL");
  await expect(page.locator(".panel-table tbody tr")).toContainText("0.812");
  await expect(page.locator(".panel-table tbody tr")).toContainText("31.0%");

  expect(previewUrl).not.toBe("");
  const capturedPreview = new URL(previewUrl);
  expect(capturedPreview.searchParams.getAll("tickers")).toEqual(["AAPL", "MSFT"]);
  expect(capturedPreview.searchParams.getAll("form_types")).toEqual(["10-K", "10-Q"]);
  expect(capturedPreview.searchParams.get("period_end_from")).toBe("2025-01-01");
  expect(capturedPreview.searchParams.get("period_end_to")).toBe("2025-12-31");
  expect(capturedPreview.searchParams.get("as_of")).toBe("2026-02-01T23:59:59+00:00");
  expect(capturedPreview.searchParams.get("include_amendments")).toBe("false");
  expect(capturedPreview.searchParams.get("limit")).toBe("25");

  await page.getByLabel("Dataset download format").selectOption("csv");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("fdre-test-panel.csv");

  expect(exportUrl).not.toBe("");
  const capturedExport = new URL(exportUrl);
  expect(capturedExport.searchParams.getAll("tickers")).toEqual(["AAPL", "MSFT"]);
  expect(capturedExport.searchParams.getAll("form_types")).toEqual(["10-K", "10-Q"]);
  expect(capturedExport.searchParams.get("as_of")).toBe("2026-02-01T23:59:59+00:00");
  expect(capturedExport.searchParams.get("output_format")).toBe("csv");
  expect(capturedExport.searchParams.get("limit")).toBe("500");
});
