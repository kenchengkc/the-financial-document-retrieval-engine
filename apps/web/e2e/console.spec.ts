import { expect, test, type Page, type Route } from "@playwright/test";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const FOUNDATION_MIGRATION_KEY = "fdre.foundation.cache-migration";
const FOUNDATION_MIGRATION_VERSION = "sp500-primary-universe-v2";

async function mockBase(page: Page) {
  await page.route(`${API_URL}/health`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    }),
  );
  await page.route(`${API_URL}/coverage`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        catalog_count: 5794,
        sp500_catalog_count: 499,
        indexed_count: 495,
        sp500_indexed_count: 495,
        document_count: 2750,
        chunk_count: 2_710_000,
        indexed_tickers: ["AAPL", "MSFT", "NVDA"],
      }),
    }),
  );
  await page.route(`${API_URL}/companies**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 2,
        companies: [
          {
            ticker: "AAPL",
            cik: "0000320193",
            name: "Apple Inc.",
            exchange: "Nasdaq",
            document_count: 12,
            chunk_count: 4000,
            indexed: true,
          },
          {
            ticker: "KKR",
            cik: "0001404912",
            name: "KKR & Co. Inc.",
            exchange: "NYSE",
            document_count: 10,
            chunk_count: 3800,
            indexed: true,
          },
        ],
      }),
    }),
  );
  await page.route(`${API_URL}/operations/quality**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: "2026-07-17T04:53:23Z",
        company_count: 499,
        document_count: 2750,
        chunk_count: 2_710_000,
        embedding_count: 2_710_000,
        stale_after_days: 150,
        stale_tickers: [],
        missing_expected_filings: [],
        duplicate_accession_groups: 0,
        documents_without_chunks: 0,
        unchunked_documents: [],
        chunks_without_embeddings: 0,
        facts_without_documents: 0,
        freshness_ratio: 0.998,
        document_chunk_coverage: 1,
        embedding_coverage: 1,
        recent_ingestion_success_rate: 1,
        latest_ingestion_completed_at: "2026-07-16T11:30:33Z",
      }),
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockBase(page);
});

test("shows the research console and mode switcher", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Research SEC filings without look-ahead bias." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Research SEC filings four ways" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Ask/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: /Retrieve/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Screen/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Signals/ })).toBeVisible();
});

test("switches between research modes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: /Retrieve/ }).click();
  await expect(page.getByRole("heading", { name: "Retrieve" })).toBeVisible();
  await page.getByRole("tab", { name: /Screen/ }).click();
  await expect(page.getByRole("heading", { name: "Screen" })).toBeVisible();
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.getByRole("heading", { name: "Signals" })).toBeVisible();
});

test("renders data foundation metrics", async ({ page }) => {
  await page.goto("/");
  const foundation = page.locator(".data-foundation");
  await expect(foundation).toContainText("Data status");
  await expect(page.locator(".foundation-stat").first()).toContainText("495");
  await expect(page.locator(".foundation-company").first()).toContainText("KKR");
  await expect(foundation).toContainText("100.0%");
  await expect(foundation).not.toContainText("N/A");
});

test("renders foundation coverage before a slower operations response", async ({ page }) => {
  let releaseOperations = () => {};
  const operationsPending = new Promise<void>((resolve) => {
    releaseOperations = resolve;
  });
  await page.route(`${API_URL}/operations/quality**`, async (route) => {
    await operationsPending;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: "2026-07-17T04:53:23Z",
        company_count: 499,
        document_count: 2750,
        chunk_count: 2_710_000,
        embedding_count: 2_710_000,
        stale_after_days: 150,
        stale_tickers: [],
        missing_expected_filings: [],
        duplicate_accession_groups: 0,
        documents_without_chunks: 0,
        unchunked_documents: [],
        chunks_without_embeddings: 0,
        facts_without_documents: 0,
        freshness_ratio: 0.998,
        document_chunk_coverage: 1,
        embedding_coverage: 1,
        recent_ingestion_success_rate: 1,
        latest_ingestion_completed_at: "2026-07-16T11:30:33Z",
      }),
    });
  });

  await page.goto("/");
  const foundation = page.locator(".data-foundation");
  await expect(foundation).toContainText("Data status");
  await expect(page.locator(".foundation-stat").first()).toContainText("495");
  await expect(page.locator(".foundation-company").first()).toContainText("KKR");
  await expect(
    page.locator(".foundation-stat").filter({ hasText: "vector coverage" }).locator("strong"),
  ).toHaveText("Loading");
  await expect(foundation).not.toContainText("N/A");
  releaseOperations();
});

test("uses a fresh foundation snapshot without waking the data service", async ({ page }) => {
  const cachedAt = Date.now();
  await page.addInitScript(
    ({ savedAt, migrationKey, migrationVersion }) => {
      window.localStorage.setItem(migrationKey, migrationVersion);
      window.localStorage.setItem(
        "fdre.foundation.v1",
        JSON.stringify({
          savedAt,
          data: {
            coverage: {
              catalog_count: 5794,
              sp500_catalog_count: 499,
              indexed_count: 498,
              sp500_indexed_count: 498,
              document_count: 2766,
              chunk_count: 2715610,
              indexed_tickers: ["AAPL", "MSFT"],
            },
            companies: [
              { ticker: "ARE", cik: "1", name: "Alexandria", exchange: "NYSE", document_count: 13, chunk_count: 42236, indexed: true },
              { ticker: "AAPL", cik: "2", name: "Apple", exchange: "Nasdaq", document_count: 13, chunk_count: 6056, indexed: true },
            ],
            operations: {
              generated_at: "2026-07-17T04:53:23Z",
              company_count: 499,
              document_count: 2766,
              chunk_count: 2715610,
              embedding_count: 2715610,
              stale_after_days: 150,
              stale_tickers: [],
              missing_expected_filings: [],
              duplicate_accession_groups: 0,
              documents_without_chunks: 0,
              unchunked_documents: [],
              chunks_without_embeddings: 0,
              facts_without_documents: 0,
              freshness_ratio: 0.998,
              document_chunk_coverage: 1,
              embedding_coverage: 1,
              recent_ingestion_success_rate: 1,
              latest_ingestion_completed_at: "2026-07-16T11:30:33Z",
            },
          },
        }),
      );
    },
    {
      savedAt: cachedAt,
      migrationKey: FOUNDATION_MIGRATION_KEY,
      migrationVersion: FOUNDATION_MIGRATION_VERSION,
    },
  );

  let releaseRequests = () => {};
  const requestsPending = new Promise<void>((resolve) => {
    releaseRequests = resolve;
  });
  let foundationRequests = 0;
  const holdRequest = async (route: Route) => {
    foundationRequests += 1;
    await requestsPending;
    await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
  };
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
  );
  await page.route("**/coverage", holdRequest);
  await page.route("**/companies**", holdRequest);
  await page.route("**/operations/quality**", holdRequest);

  await page.goto("/");
  const foundation = page.locator(".data-foundation");
  await expect(page.locator(".foundation-stat").first()).toContainText("498");
  await expect(foundation).toContainText("100.0%");
  await expect(foundation).toContainText("42,236 passages");
  await expect(foundation).not.toContainText("N/A");
  await expect.poll(() => foundationRequests).toBe(0);
  releaseRequests();
});

test.describe("ingestion timestamp", () => {
  test.use({ timezoneId: "America/New_York" });

  test("shows timestamps in the viewer's local time zone", async ({ page }) => {
    await mockBase(page);
    await page.route("**/operations/quality**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ latest_ingestion_completed_at: "2026-07-16T11:30:33Z" }),
      }),
    );
    await page.goto("/");
    await expect(page.locator(".data-foundation")).toContainText("7:30 AM");
  });
});
