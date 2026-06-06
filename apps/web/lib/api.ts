import type { AnswerResponse } from "@/lib/types";

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
