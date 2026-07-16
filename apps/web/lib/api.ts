import type {
  AnswerResponse,
  CanonicalMetric,
  CompaniesResponse,
  CoverageResponse,
  FilingDifference,
  FinancialFactsResponse,
  OperationsQuality,
  ResearchPanel,
  SearchFilters,
  SearchResponse,
  SignalStudiesResponse,
  SignalStudyResponse,
  ThematicScanResponse,
} from "@/lib/types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

async function parseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? `API request failed with status ${response.status}.`;
  } catch {
    return `API request failed with status ${response.status}.`;
  }
}

export async function checkHealth() {
  try {
    const response = await fetch(`${API_URL}/health`, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchCoverage(): Promise<CoverageResponse | null> {
  try {
    const response = await fetch(`${API_URL}/coverage`, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as CoverageResponse;
  } catch {
    return null;
  }
}

export async function askQuestion(question: string): Promise<AnswerResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "The data service is temporarily unavailable. Please try again in a moment.",
    );
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as AnswerResponse;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "The data service is temporarily unavailable. Please try again in a moment.",
    );
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
}

async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new Error(
      "The data service is temporarily unavailable. Please try again in a moment.",
    );
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
}

function withQuery(path: string, values: Record<string, string | number | boolean | string[] | null | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, item);
    } else {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function runSearch(
  query: string,
  filters: SearchFilters,
  topK = 8,
): Promise<SearchResponse> {
  return postJson<SearchResponse>("/search", { query, filters, top_k: topK });
}

export function runThematicScan(
  query: string,
  issuers: number,
  resultsPerIssuer: number,
): Promise<ThematicScanResponse> {
  return postJson<ThematicScanResponse>("/research/thematic-scan", {
    query,
    issuers,
    results_per_issuer: resultsPerIssuer,
  });
}

export function fetchCompanies(): Promise<CompaniesResponse> {
  return getJson<CompaniesResponse>("/companies?indexed_only=true&limit=500");
}

export function fetchOperationsQuality(): Promise<OperationsQuality> {
  return getJson<OperationsQuality>("/operations/quality");
}

export function fetchFilingDifference(
  accessionNumber: string,
  asOf?: string,
): Promise<FilingDifference> {
  const path = withQuery(
    `/research/filing-differences/${encodeURIComponent(accessionNumber)}`,
    { as_of: asOf ? `${asOf}T23:59:59+00:00` : undefined },
  );
  return getJson<FilingDifference>(path);
}

export function fetchFinancialFacts(options: {
  tickers: string[];
  metrics: CanonicalMetric[];
  asOf?: string;
  restatementPolicy: "latest" | "as_reported" | "all";
  limit?: number;
}): Promise<FinancialFactsResponse> {
  return getJson<FinancialFactsResponse>(
    withQuery("/research/facts", {
      tickers: options.tickers,
      metrics: options.metrics,
      as_of: options.asOf ? `${options.asOf}T23:59:59+00:00` : undefined,
      restatement_policy: options.restatementPolicy,
      limit: options.limit ?? 100,
    }),
  );
}

export type ResearchPanelOptions = {
  tickers: string[];
  formTypes: string[];
  periodEndFrom?: string;
  periodEndTo?: string;
  asOf?: string;
  includeAmendments?: boolean;
  limit?: number;
};

function panelPath(path: string, options: ResearchPanelOptions, outputFormat?: string) {
  return withQuery(path, {
    tickers: options.tickers,
    form_types: options.formTypes,
    period_end_from: options.periodEndFrom,
    period_end_to: options.periodEndTo,
    as_of: options.asOf ? `${options.asOf}T23:59:59+00:00` : undefined,
    include_amendments: options.includeAmendments ?? false,
    output_format: outputFormat,
    limit: options.limit ?? 250,
  });
}

export function fetchResearchPanel(options: ResearchPanelOptions): Promise<ResearchPanel> {
  return getJson<ResearchPanel>(panelPath("/research/panel", options));
}

export async function downloadResearchPanel(
  options: ResearchPanelOptions,
  outputFormat: "csv" | "json" | "parquet",
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${panelPath("/research/panel/export", options, outputFormat)}`);
  } catch {
    throw new Error(
      "The data service is temporarily unavailable. Please try again in a moment.",
    );
  }
  if (!response.ok) throw new Error(await parseError(response));
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? `fdre-panel.${outputFormat}`;
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

export async function fetchSignalStudy(): Promise<SignalStudyResponse | null> {
  try {
    const response = await fetch(`${API_URL}/research/signal-study`, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as SignalStudyResponse;
  } catch {
    return null;
  }
}

export async function fetchSignalStudies(): Promise<SignalStudyResponse[]> {
  try {
    const response = await fetch(`${API_URL}/research/signal-studies`, { cache: "no-store" });
    if (response.ok) {
      return ((await response.json()) as SignalStudiesResponse).studies;
    }
  } catch {
    // Fall back to the legacy single-study endpoint below.
  }
  const study = await fetchSignalStudy();
  return study ? [study] : [];
}
