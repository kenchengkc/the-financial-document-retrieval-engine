import type {
  AnswerResponse,
  CompaniesResponse,
  CoverageResponse,
  OperationsQuality,
  SearchFilters,
  SearchResponse,
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
      "The FDRE backend is not reachable. Set NEXT_PUBLIC_API_URL to the deployed API URL.",
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
      "The FDRE backend is not reachable. Set NEXT_PUBLIC_API_URL to the deployed API URL.",
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
      "The FDRE backend is not reachable. Set NEXT_PUBLIC_API_URL to the deployed API URL.",
    );
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
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
