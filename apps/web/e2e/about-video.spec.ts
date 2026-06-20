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
