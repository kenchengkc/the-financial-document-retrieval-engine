from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx

from apps.api.app.config import get_settings

SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_COMPANY_FACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
DEFAULT_TIMEOUT_SECONDS = 30.0

JSONDict = dict[str, Any]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


def normalize_cik(cik: str) -> str:
    """Return a SEC CIK as a zero-padded 10-digit string."""

    digits = re.sub(r"\D", "", cik)
    if not digits or len(digits) > 10:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)


def normalize_accession(accession: str) -> str:
    """Return an accession number without separators for SEC archive paths."""

    digits = re.sub(r"\D", "", accession)
    if not digits:
        raise ValueError(f"Invalid accession number: {accession!r}")
    return digits


def build_primary_document_url(cik: str, accession: str, primary_document: str) -> str:
    """Build the canonical SEC archive URL for a filing's primary document."""

    filename = Path(primary_document).name
    if not filename or filename != primary_document or filename in {".", ".."}:
        raise ValueError(f"Invalid primary document filename: {primary_document!r}")

    cik_path = str(int(normalize_cik(cik)))
    accession_path = normalize_accession(accession)
    return f"{SEC_ARCHIVES_BASE_URL}/{cik_path}/{accession_path}/{filename}"


def company_submissions_url(cik: str) -> str:
    return f"{SEC_SUBMISSIONS_BASE_URL}/CIK{normalize_cik(cik)}.json"


def company_facts_url(cik: str) -> str:
    return f"{SEC_COMPANY_FACTS_BASE_URL}/CIK{normalize_cik(cik)}.json"


class RateLimiter:
    """Thread-safe fixed-interval limiter suitable for SEC's request policy."""

    def __init__(
        self,
        requests_per_second: int,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._minimum_interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last_request_at = now


class SECClient:
    """Small cached HTTP client for SEC submissions and filing documents."""

    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: str | Path = "data/cache/sec",
        requests_per_second: int = 5,
        http_client: httpx.Client | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        cleaned_user_agent = user_agent.strip()
        if not cleaned_user_agent:
            raise ValueError("SEC_USER_AGENT must identify the application and a contact")
        if "contact@example.com" in cleaned_user_agent.casefold():
            raise ValueError("Replace the placeholder SEC_USER_AGENT with a real contact")
        self.cache_dir = Path(cache_dir)
        self._request_headers = {
            "User-Agent": cleaned_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        self._rate_limiter = rate_limiter or RateLimiter(requests_per_second)

    @classmethod
    def from_settings(cls) -> SECClient:
        settings = get_settings()
        if settings.sec_user_agent is None:
            raise ValueError("SEC_USER_AGENT is required for live SEC requests")
        return cls(
            user_agent=settings.sec_user_agent,
            cache_dir=settings.sec_cache_dir,
            requests_per_second=settings.sec_rate_limit_requests_per_second,
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> SECClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        suffix = Path(httpx.URL(url).path).suffix or ".bin"
        return self.cache_dir / f"{digest}{suffix}"

    def get_bytes(self, url: str, *, use_cache: bool = True) -> bytes:
        cache_path = self._cache_path(url)
        if use_cache and cache_path.is_file():
            return cache_path.read_bytes()

        self._rate_limiter.wait()
        response = self._http_client.get(url, headers=self._request_headers)
        response.raise_for_status()
        content = response.content

        if use_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
            temporary_path.write_bytes(content)
            temporary_path.replace(cache_path)
        return content

    def get_json(self, url: str, *, use_cache: bool = True) -> JSONDict:
        payload = json.loads(self.get_bytes(url, use_cache=use_cache))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected an object response from {url}")
        return payload

    def get_company_submissions(self, cik: str) -> JSONDict:
        return self.get_json(company_submissions_url(cik))

    def get_company_facts(self, cik: str) -> JSONDict:
        return self.get_json(company_facts_url(cik))

    def list_recent_filings(
        self,
        cik: str,
        form_types: list[str],
        limit: int | Mapping[str, int],
    ) -> list[JSONDict]:
        submissions = self.get_company_submissions(cik)
        return extract_recent_filings(submissions, form_types, limit)


def extract_recent_filings(
    submissions: JSONDict,
    form_types: Iterable[str],
    limit: int | Mapping[str, int],
) -> list[JSONDict]:
    """Select the latest filings, applying the limit independently per form."""

    requested_forms = {form_type.upper() for form_type in form_types}
    limits = _form_limits(requested_forms, limit)
    filings = submissions.get("filings")
    if not isinstance(filings, dict):
        return []
    recent = filings.get("recent", {})
    if not isinstance(recent, dict):
        return []

    accessions = recent.get("accessionNumber", [])
    if not isinstance(accessions, list):
        return []

    counts = dict.fromkeys(requested_forms, 0)
    selected: list[JSONDict] = []
    for index, accession in enumerate(accessions):
        form_type = _value_at(recent, "form", index)
        if not isinstance(form_type, str):
            continue
        normalized_form = form_type.upper()
        if (
            normalized_form not in requested_forms
            or counts[normalized_form] >= limits[normalized_form]
        ):
            continue

        primary_document = _value_at(recent, "primaryDocument", index)
        if not isinstance(accession, str) or not isinstance(primary_document, str):
            continue

        selected.append(
            {
                "accession_number": accession,
                "form_type": normalized_form,
                "filing_date": _value_at(recent, "filingDate", index),
                "report_date": _value_at(recent, "reportDate", index),
                "acceptance_datetime": _value_at(recent, "acceptanceDateTime", index),
                "primary_document": primary_document,
                "primary_document_description": _value_at(
                    recent,
                    "primaryDocDescription",
                    index,
                ),
                "file_number": _value_at(recent, "fileNumber", index),
                "film_number": _value_at(recent, "filmNumber", index),
                "items": _value_at(recent, "items", index),
                "size": _value_at(recent, "size", index),
                "is_xbrl": _value_at(recent, "isXBRL", index),
                "is_inline_xbrl": _value_at(recent, "isInlineXBRL", index),
            }
        )
        counts[normalized_form] += 1

        if counts and all(count >= limits[form] for form, count in counts.items()):
            break

    return selected


def _value_at(payload: JSONDict, key: str, index: int) -> Any:
    values = payload.get(key, [])
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _form_limits(
    requested_forms: set[str],
    limit: int | Mapping[str, int],
) -> dict[str, int]:
    if isinstance(limit, int):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return dict.fromkeys(requested_forms, limit)
    normalized = {form.upper(): value for form, value in limit.items()}
    missing = requested_forms - normalized.keys()
    if missing:
        raise ValueError(f"missing limits for forms: {', '.join(sorted(missing))}")
    if any(value < 1 for value in normalized.values()):
        raise ValueError("form limits must be at least 1")
    return {form: normalized[form] for form in requested_forms}


def get_company_submissions(cik: str) -> JSONDict:
    with SECClient.from_settings() as client:
        return client.get_company_submissions(cik)


def list_recent_filings(
    cik: str,
    form_types: list[str],
    limit: int | Mapping[str, int],
) -> list[JSONDict]:
    with SECClient.from_settings() as client:
        return client.list_recent_filings(cik, form_types, limit)
