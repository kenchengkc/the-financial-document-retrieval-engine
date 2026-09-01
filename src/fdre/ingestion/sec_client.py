from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import date
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


def submissions_history_file_url(filename: str) -> str:
    """Return the canonical URL for one SEC submissions history file."""

    if Path(filename).name != filename or re.fullmatch(r"[A-Za-z0-9._-]+\.json", filename) is None:
        raise ValueError(f"Invalid SEC submissions history filename: {filename!r}")
    return f"{SEC_SUBMISSIONS_BASE_URL}/{filename}"


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
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 5.0,
        retry_sleep: Sleep = time.sleep,
    ) -> None:
        cleaned_user_agent = user_agent.strip()
        if not cleaned_user_agent:
            raise ValueError("SEC_USER_AGENT must identify the application and a contact")
        if "contact@example.com" in cleaned_user_agent.casefold():
            raise ValueError("Replace the placeholder SEC_USER_AGENT with a real contact")
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
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
        self._retry_attempts = retry_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._retry_sleep = retry_sleep

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

        response: httpx.Response | None = None
        for attempt in range(self._retry_attempts):
            self._rate_limiter.wait()
            response = self._http_client.get(url, headers=self._request_headers)
            if response.status_code not in {403, 429, 500, 502, 503, 504}:
                break
            if attempt + 1 < self._retry_attempts:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after is not None and retry_after.isdigit()
                    else self._retry_backoff_seconds * (2**attempt)
                )
                self._retry_sleep(min(delay, 60.0))
        if response is None:  # pragma: no cover - constructor rejects zero attempts
            raise RuntimeError("SEC request did not execute")
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

    def get_company_filing_history(self, cik: str) -> list[JSONDict]:
        """Load the recent and paginated historical SEC submission records for one issuer."""

        submissions = self.get_company_submissions(cik)
        payloads = [submissions]
        filings = submissions.get("filings")
        files = filings.get("files") if isinstance(filings, dict) else None
        if not isinstance(files, list):
            return payloads
        for entry in files:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            payloads.append(self.get_json(submissions_history_file_url(name)))
        return payloads

    def list_filings(
        self,
        cik: str,
        form_types: list[str],
        *,
        filed_from: date | None = None,
        filed_to: date | None = None,
        limit: int | Mapping[str, int] | None = None,
    ) -> list[JSONDict]:
        """Select filings across the issuer's complete SEC submissions history."""

        return extract_filings(
            self.get_company_filing_history(cik),
            form_types,
            filed_from=filed_from,
            filed_to=filed_to,
            limit=limit,
        )


def extract_recent_filings(
    submissions: JSONDict,
    form_types: Iterable[str],
    limit: int | Mapping[str, int],
) -> list[JSONDict]:
    """Select the latest filings, applying the limit independently per form."""

    return extract_filings([submissions], form_types, limit=limit)


def extract_filings(
    submissions_history: Iterable[JSONDict],
    form_types: Iterable[str],
    *,
    filed_from: date | None = None,
    filed_to: date | None = None,
    limit: int | Mapping[str, int] | None = None,
) -> list[JSONDict]:
    """Select deterministic filing rows from recent and paginated SEC submissions data."""

    requested_forms = {form_type.upper() for form_type in form_types}
    if not requested_forms:
        return []
    limits = _form_limits(requested_forms, limit) if limit is not None else None
    by_accession: dict[str, JSONDict] = {}
    for submissions in submissions_history:
        rows = _submission_rows(submissions)
        accessions = rows.get("accessionNumber", [])
        if not isinstance(accessions, list):
            continue
        for index, accession in enumerate(accessions):
            form_type = _value_at(rows, "form", index)
            if not isinstance(form_type, str):
                continue
            normalized_form = form_type.upper()
            primary_document = _value_at(rows, "primaryDocument", index)
            filing_date = _value_at(rows, "filingDate", index)
            if (
                normalized_form not in requested_forms
                or not isinstance(accession, str)
                or not isinstance(primary_document, str)
                or not isinstance(filing_date, str)
            ):
                continue
            try:
                parsed_filing_date = date.fromisoformat(filing_date)
            except ValueError:
                continue
            if filed_from is not None and parsed_filing_date < filed_from:
                continue
            if filed_to is not None and parsed_filing_date > filed_to:
                continue
            by_accession[accession] = {
                "accession_number": accession,
                "form_type": normalized_form,
                "filing_date": filing_date,
                "report_date": _value_at(rows, "reportDate", index),
                "acceptance_datetime": _value_at(rows, "acceptanceDateTime", index),
                "primary_document": primary_document,
                "primary_document_description": _value_at(
                    rows,
                    "primaryDocDescription",
                    index,
                ),
                "file_number": _value_at(rows, "fileNumber", index),
                "film_number": _value_at(rows, "filmNumber", index),
                "items": _value_at(rows, "items", index),
                "size": _value_at(rows, "size", index),
                "is_xbrl": _value_at(rows, "isXBRL", index),
                "is_inline_xbrl": _value_at(rows, "isInlineXBRL", index),
            }

    ordered = sorted(
        by_accession.values(),
        key=lambda filing: (
            str(filing["filing_date"]),
            str(filing.get("acceptance_datetime") or ""),
            str(filing["accession_number"]),
        ),
        reverse=True,
    )
    if limits is None:
        return ordered
    counts = dict.fromkeys(requested_forms, 0)
    selected: list[JSONDict] = []
    for filing in ordered:
        normalized_form = str(filing["form_type"])
        if counts[normalized_form] >= limits[normalized_form]:
            continue
        selected.append(filing)
        counts[normalized_form] += 1
    return selected


def _submission_rows(submissions: JSONDict) -> JSONDict:
    filings = submissions.get("filings")
    if isinstance(filings, dict):
        recent = filings.get("recent")
        if isinstance(recent, dict):
            return recent
    return submissions


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
