import { expect, test } from "@playwright/test";

test("shows indexed coverage badge when API is online", async ({ page }) => {
  await page.route("**/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    });
  });
  await page.route("**/coverage", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        catalog_count: 5794,
        sp500_catalog_count: 499,
        indexed_count: 5,
        sp500_indexed_count: 5,
        document_count: 11,
        chunk_count: 8259,
        indexed_tickers: ["AAPL", "AMZN", "GOOG", "MSFT", "NVDA"],
      }),
    });
  });

  await page.goto("/");

  await expect(page.getByText("5 / 5,794 indexed")).toBeVisible();
  await expect(page.getByText("S&P 500: 5 / 499")).toBeVisible();
  await expect(page.getByText("API online")).toBeVisible();
});
