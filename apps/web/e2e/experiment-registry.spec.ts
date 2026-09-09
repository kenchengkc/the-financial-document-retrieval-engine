import { expect, test, type Page } from "@playwright/test";

const EXPERIMENT_ID = "a".repeat(64);

async function mockFoundation(page: Page) {
  await page.route("**/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
  );
  await page.route("**/coverage", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        catalog_count: 499,
        sp500_catalog_count: 499,
        indexed_count: 499,
        sp500_indexed_count: 499,
        document_count: 3204,
        chunk_count: 3039403,
        indexed_tickers: ["AAPL"],
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

function signalStudy() {
  return {
    experiment_id: 1,
    experiment_key: "published-study",
    code_sha: "deadbeef",
    created_at: "2026-09-01T12:00:00Z",
    report: {
      signal_name: "risk_churn_acceleration",
      outcome_name: "abnormal_return",
      n_quantiles: 5,
      event_count: 100,
      dataset_version: "dataset-v7",
      feature_version: "features-v4",
      config: {},
      results: [
        {
          window: "1:21",
          sample_size: 100,
          information_coefficient: 0.01,
          ic_t_stat: 0.2,
          quantiles: [],
          long_short_mean: 0,
          long_short_ci_low: -0.01,
          long_short_ci_high: 0.01,
          long_short_p_value: 0.7,
          long_short_adjusted_p_value: 0.7,
        },
      ],
    },
  };
}

function experimentSummary() {
  return {
    experiment_id: EXPERIMENT_ID,
    signal_name: "risk_churn_acceleration",
    outcome_name: "abnormal_return",
    dataset_version: "dataset-v7",
    feature_version: "features-v4",
    market_data_version: "market-v3",
    universe_snapshot_id: "u".repeat(64),
    feature_snapshot_id: "f".repeat(64),
    code_sha: "code-1234567890",
    feature_lineage_digest: "l".repeat(64),
    slice_snapshot_id: "s".repeat(64),
    artifact_count: 2,
    filing_lineage_count: 4812,
    final_decisions: [{ status: "REJECT" }],
    registered_at: "2026-09-08T12:00:00Z",
  };
}

function experimentManifest() {
  return {
    ...experimentSummary(),
    registry_version: "research-experiment-registry-v1",
    signal_definition: { formula: "change in risk-factor churn" },
    fold_schedule: [{ fold_id: "fold-1" }, { fold_id: "fold-2" }],
    filing_lineage: [{ ticker: "AAPL" }],
    implementation_assumptions: { cost_bps: [5, 10, 25, 50] },
    statistical_assumptions: { multiple_testing: "BH" },
    robustness_assumptions: { sector_checks: true },
    artifacts: [
      {
        kind: "walk_forward",
        experiment_key: "walk-forward-root",
        payload_sha256: "1".repeat(64),
      },
      {
        kind: "oos_promotion",
        experiment_key: "promotion-root",
        payload_sha256: "2".repeat(64),
      },
    ],
  };
}

async function mockStudies(page: Page) {
  await page.route("**/research/signal-studies", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ studies: [signalStudy()] }),
    }),
  );
  await page.route("**/research/signal-study", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(signalStudy()),
    }),
  );
}

async function openRegistry(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: /Signals/ }).click();
  await page.getByRole("tab", { name: "Registry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Experiment registry" })).toBeVisible();
}

test("inspects, verifies, and exports an immutable experiment root", async ({ page }) => {
  await mockFoundation(page);
  await mockStudies(page);
  await page.route("**/research/experiments**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith(`/${EXPERIMENT_ID}/verify`)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          experiment_id: EXPERIMENT_ID,
          verified: true,
          artifact_count: 2,
          final_decisions: [{ status: "REJECT" }],
        }),
      });
    }
    if (url.pathname.endsWith(`/${EXPERIMENT_ID}/bundle`)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          bundle_version: "research-experiment-bundle-v1",
          experiment_id: EXPERIMENT_ID,
          manifest: experimentManifest(),
          artifacts: [],
          bundle_sha256: "b".repeat(64),
        }),
      });
    }
    if (url.pathname.endsWith(`/${EXPERIMENT_ID}`)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(experimentManifest()),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ experiments: [experimentSummary()] }),
    });
  });

  await openRegistry(page);

  await expect(page.locator(".monitor-table")).toContainText("risk churn acceleration");
  await expect(page.locator(".monitor-table")).toContainText("REJECT");
  await expect(page.locator(".audit-manifest")).toContainText("research-experiment-registry-v1");
  await expect(page.locator(".audit-gates")).toContainText("walk forward");
  await expect(page.locator(".audit-gates")).toContainText("oos promotion");

  await page.getByTitle("Recompute hashes and replay terminal decisions").click();
  await expect(page.locator(".research-state.pass")).toContainText("Verified");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTitle("Download verified portable bundle").click(),
  ]);
  expect(download.suggestedFilename()).toBe("fdre-experiment-aaaaaaaaaaaa.json");
});

test("does not download a portable bundle when server verification fails", async ({ page }) => {
  await mockFoundation(page);
  await mockStudies(page);
  let downloads = 0;
  page.on("download", () => {
    downloads += 1;
  });
  await page.route("**/research/experiments**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith(`/${EXPERIMENT_ID}/bundle`)) {
      return route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "research experiment manifest digest mismatch" }),
      });
    }
    if (url.pathname.endsWith(`/${EXPERIMENT_ID}`)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(experimentManifest()),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ experiments: [experimentSummary()] }),
    });
  });

  await openRegistry(page);
  await page.getByTitle("Download verified portable bundle").click();

  await expect(page.getByTitle("research experiment manifest digest mismatch")).toBeVisible();
  expect(downloads).toBe(0);
});
