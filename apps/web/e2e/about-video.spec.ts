import { expect, test } from "@playwright/test";

test("frames the About hero with evidence panels instead of decorative media", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  // Vercel Analytics requests its insights script, which 404s off-Vercel (local/CI);
  // stub it so that environment noise doesn't fail the console-error assertion below.
  await page.route("**/_vercel/insights/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }),
  );

  await page.goto("/about", { waitUntil: "domcontentloaded" });

  const corpusPanel = page.getByRole("complementary", { name: "Corpus scope" });
  const contractPanel = page.getByRole("complementary", { name: "Answer contract" });
  await expect(corpusPanel).toContainText("499 / 500");
  await expect(corpusPanel).toContainText("survivorship-biased");
  await expect(contractPanel).toContainText("Evidence first");
  await expect(contractPanel).toContainText("Verify citation or abstain");
  await expect(page.locator(".ih-stage video, .ih-stage img")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test("replays the current four-mode research console", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/_vercel/insights/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }),
  );

  await page.goto("/about");

  const demo = page.locator(".bdemo");
  const tabs = demo.getByRole("tab");
  await expect(tabs).toHaveCount(4);
  await expect(tabs.nth(0)).toContainText("Ask");
  await expect(tabs.nth(1)).toContainText("Retrieve");
  await expect(tabs.nth(2)).toContainText("Screen");
  await expect(tabs.nth(3)).toContainText("Signals");

  await expect(demo.getByRole("heading", { name: "Run summary" })).toBeVisible();
  await expect(demo).toContainText("Citation verified");
  await expect(demo).toContainText("Primary sources");

  await tabs.nth(1).click();
  await expect(demo.getByRole("heading", { name: "Query reported financials" })).toBeVisible();
  await expect(demo).toContainText("Financial facts");
  await expect(demo).toContainText("$26.77B");

  await tabs.nth(2).click();
  await expect(demo.getByRole("heading", { name: "Screen" })).toBeVisible();
  await expect(demo).toContainText("Ranked issuers");
  await expect(demo).toContainText("Digital Realty");

  await tabs.nth(3).click();
  await expect(demo.getByRole("heading", { name: "Signals" })).toBeVisible();
  await expect(demo).toContainText("-5.01%");
  await expect(demo).toContainText("Significant inversion");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(demo).toBeVisible();
  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBe(false);
});
