import { expect, test } from "@playwright/test";

test("plays visible stages and lets the reader pause and select a stage", async ({ page }) => {
  await page.clock.install();
  await page.goto("/");
  const pipeline = page.getByLabel("Retrieval pipeline illustration");
  await pipeline.scrollIntoViewIfNeeded();
  await expect(pipeline).toHaveAttribute("data-playing", "true");
  await page.clock.runFor(3300);
  await expect(pipeline.getByRole("button", { name: "Show Search stage" })).toHaveAttribute("aria-current", "step");
  await pipeline.getByRole("button", { name: "Pause pipeline animation" }).click();
  await page.clock.runFor(6500);
  await expect(pipeline.getByRole("button", { name: "Show Search stage" })).toHaveAttribute("aria-current", "step");
  await pipeline.getByRole("button", { name: "Show Answer stage" }).click();
  await expect(pipeline.getByRole("heading", { name: "Return evidence, or abstain" })).toBeVisible();
  await pipeline.getByRole("button", { name: "Play pipeline animation" }).click();
  await page.clock.runFor(3300);
  await expect(pipeline.getByRole("button", { name: "Show Identify stage" })).toHaveAttribute("aria-current", "step");
});

test("reduced-motion readers can inspect every stage without autoplay or mobile overflow", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const pipeline = page.getByLabel("Retrieval pipeline illustration");
  await pipeline.scrollIntoViewIfNeeded();
  await expect(pipeline).toHaveAttribute("data-playing", "false");
  await expect(pipeline.getByRole("button", { name: /pipeline animation/ })).toHaveCount(0);
  await pipeline.getByRole("button", { name: "Show Validate stage" }).click();
  await expect(pipeline.getByRole("heading", { name: "Check the citation trail" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
