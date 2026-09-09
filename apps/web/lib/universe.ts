export type UniverseConstituent = {
  security_id: number;
  cik: string;
  symbol: string;
  name: string | null;
  exchange: string | null;
  membership_effective_from: string;
  identity_effective_from: string;
  membership_source_hash: string;
  identity_source_hash: string;
  verification_status: "verified" | "provisional" | "rejected";
};

export type UniverseConstituentChange = {
  security_id: number;
  changed_fields: string[];
  before: UniverseConstituent;
  after: UniverseConstituent;
};

export type UniverseDiff = {
  schema_version: string;
  universe_code: string;
  from_snapshot_id: string;
  to_snapshot_id: string;
  from_as_of: string;
  to_as_of: string;
  includes_provisional: boolean;
  summary: {
    from_count: number;
    to_count: number;
    added_count: number;
    removed_count: number;
    changed_count: number;
    retained_count: number;
  };
  added: UniverseConstituent[];
  removed: UniverseConstituent[];
  changed: UniverseConstituentChange[];
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/fdre-api").replace(/\/$/, "");

async function responseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? `Universe request failed with status ${response.status}.`;
  } catch {
    return `Universe request failed with status ${response.status}.`;
  }
}

export async function fetchUniverseDiff(
  fromAsOf: string,
  toAsOf: string,
): Promise<UniverseDiff> {
  const params = new URLSearchParams({ from: fromAsOf, to: toAsOf });
  let response: Response;
  try {
    response = await fetch(`${API_URL}/research/universe/sp500/diff?${params.toString()}`, {
      cache: "no-store",
    });
  } catch {
    throw new Error("The universe service is temporarily unavailable.");
  }
  if (!response.ok) throw new Error(await responseError(response));
  return (await response.json()) as UniverseDiff;
}
