import { expect, test } from "@playwright/test";

test("keeps about hero posters visible until both videos are playing", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  let releaseVideos!: () => void;
  const videosReleased = new Promise<void>((resolve) => {
    releaseVideos = resolve;
  });
  await page.route("**/about/*.mp4", async (route) => {
    await videosReleased;
    await route.continue();
  });

  // Vercel Analytics requests its insights script, which 404s off-Vercel (local/CI);
  // stub it so that environment noise doesn't fail the console-error assertion below.
  await page.route("**/_vercel/insights/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }),
  );

  await page.goto("/about", { waitUntil: "domcontentloaded" });

  const leftPanel = page.locator(".ih-panel.left");
  const rightPanel = page.locator(".ih-panel.right");

  await expect(leftPanel).not.toHaveClass(/video-live/);
  await expect(rightPanel).not.toHaveClass(/video-live/);
  await expect(leftPanel.locator(".ih-poster")).toHaveCSS("opacity", "1");
  await expect(rightPanel.locator(".ih-poster")).toHaveCSS("opacity", "1");
  await expect(leftPanel.locator(".ih-video")).toHaveCSS("opacity", "0");
  await expect(rightPanel.locator(".ih-video")).toHaveCSS("opacity", "0");

  releaseVideos();

  await page.waitForFunction(
    () =>
      [".ih-stage > .ih-panel.left", ".ih-stage > .ih-panel.right"].every((selector) =>
        document.querySelector(selector)?.classList.contains("video-live"),
      ),
    undefined,
    { timeout: 15_000 },
  );

  await expect(leftPanel.locator(".ih-poster")).toHaveCSS("opacity", "0");
  await expect(rightPanel.locator(".ih-poster")).toHaveCSS("opacity", "0");
  await expect(leftPanel.locator(".ih-video")).toHaveCSS("opacity", "1");
  await expect(rightPanel.locator(".ih-video")).toHaveCSS("opacity", "1");
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
