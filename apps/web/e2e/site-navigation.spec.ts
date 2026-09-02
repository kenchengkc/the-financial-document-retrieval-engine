import { expect, test } from "@playwright/test";

const sourceUrl = "https://github.com/kenchengkc/the-financial-document-retrieval-engine";
const navLabels = ["Home", "Research", "About", "Contact"];

async function expectSharedNavigation(page: import("@playwright/test").Page) {
  const nav = page.getByRole("navigation", { name: "Site" });
  await expect(nav.getByRole("link")).toHaveText(navLabels);
  await expect(page.getByRole("link", { name: "Source code on GitHub" })).toHaveAttribute(
    "href",
    sourceUrl,
  );
}

test("keeps navigation and source actions consistent across pages", async ({ page }) => {
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
  );
  await page.route("**/coverage", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        sp500_catalog_count: 499,
        sp500_indexed_count: 499,
        document_count: 3204,
        chunk_count: 3039403,
      }),
    }),
  );

  await page.goto("/");
  await expectSharedNavigation(page);

  await page.goto("/about");
  await expectSharedNavigation(page);
  const researchLink = page.getByRole("navigation", { name: "Site" }).getByRole("link", {
    name: "Research",
  });
  await expect(researchLink).toHaveAttribute("href", "/#research");
  await researchLink.click();
  await expect(page).toHaveURL(/\/#research$/);
  await expect(page.locator(".home-research")).toBeInViewport();

  await page.goto("/contact");
  await expectSharedNavigation(page);
});
