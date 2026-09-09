import { expect, test, type Page } from "@playwright/test";

async function mockFoundation(page: Page) {
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
        document_count: 3000,
        chunk_count: 3000000,
        indexed_tickers: ["AAPL"],
      }),
    }),
  );
  await page.route("**/companies**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total: 0, companies: [] }),
    }),
  );
  await page.route("**/operations/quality**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: "2026-09-09T12:00:00Z",
        company_count: 499,
        document_count: 3000,
        chunk_count: 3000000,
        embedding_count: 3000000,
        stale_after_days: 150,
        stale_tickers: [],
        missing_expected_filings: [],
        duplicate_accession_groups: 0,
        documents_without_chunks: 0,
        unchunked_documents: [],
        chunks_without_embeddings: 0,
        facts_without_documents: 0,
        freshness_ratio: 1,
        document_chunk_coverage: 1,
        embedding_coverage: 1,
        recent_ingestion_success_rate: 1,
        latest_ingestion_completed_at: "2026-09-09T11:30:00Z",
      }),
    }),
  );
}

test("loads the PIT universe diff only after an explicit comparison", async ({ page }) => {
  await mockFoundation(page);
  let universeRequests = 0;
  await page.route("**/research/universe/sp500/diff**", (route) => {
    universeRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "fdre-hu3-universe-diff-v1",
        universe_code: "sp500",
        from_snapshot_id: "a".repeat(64),
        to_snapshot_id: "b".repeat(64),
        from_as_of: "2020-01-15",
        to_as_of: "2021-01-01",
        includes_provisional: false,
        summary: {
          from_count: 2,
          to_count: 2,
          added_count: 1,
          removed_count: 1,
          changed_count: 1,
          retained_count: 1,
        },
        added: [
          {
            security_id: 3,
            cik: "0000000003",
            symbol: "GHI",
            name: "GHI Corp",
            exchange: "NASDAQ",
            membership_effective_from: "2020-07-01",
            identity_effective_from: "2020-01-01",
            membership_source_hash: "c".repeat(64),
            identity_source_hash: "d".repeat(64),
            verification_status: "verified",
          },
        ],
        removed: [
          {
            security_id: 2,
            cik: "0000000002",
            symbol: "DEF",
            name: "DEF Corp",
            exchange: "NYSE",
            membership_effective_from: "2020-01-01",
            identity_effective_from: "2020-01-01",
            membership_source_hash: "e".repeat(64),
            identity_source_hash: "f".repeat(64),
            verification_status: "verified",
          },
        ],
        changed: [
          {
            security_id: 1,
            changed_fields: ["symbol", "identity_source_hash"],
            before: {
              security_id: 1,
              cik: "0000000001",
              symbol: "ABC",
              name: "ABC Corp",
              exchange: "NYSE",
              membership_effective_from: "2020-01-01",
              identity_effective_from: "2020-01-01",
              membership_source_hash: "1".repeat(64),
              identity_source_hash: "2".repeat(64),
              verification_status: "verified",
            },
            after: {
              security_id: 1,
              cik: "0000000001",
              symbol: "ABX",
              name: "ABC Corp",
              exchange: "NYSE",
              membership_effective_from: "2020-01-01",
              identity_effective_from: "2020-06-01",
              membership_source_hash: "1".repeat(64),
              identity_source_hash: "3".repeat(64),
              verification_status: "verified",
            },
          },
        ],
      }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Point-in-time universe audit" })).toBeVisible();
  await expect.poll(() => universeRequests).toBe(0);

  await page.getByLabel("From snapshot").fill("2020-01-15");
  await page.getByLabel("To snapshot").fill("2021-01-01");
  await page.getByRole("button", { name: "Compare snapshots" }).click();

  await expect.poll(() => universeRequests).toBe(1);
  await expect(page.getByText("GHI Corp")).toBeVisible();
  await expect(page.getByText("DEF Corp")).toBeVisible();
  await expect(page.getByText("ABC → ABX")).toBeVisible();
  await expect(page.getByText("symbol · identity source hash")).toBeVisible();
});
