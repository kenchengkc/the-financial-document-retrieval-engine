from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from fdre.ingestion.sec_client import SECClient, build_primary_document_url, normalize_cik


@dataclass(frozen=True, slots=True)
class DownloadResult:
    local_path: Path
    sha256_hash: str
    source_url: str
    size_bytes: int
    downloaded: bool


class SECFilingDownloader:
    """Download SEC filing HTML into the deterministic raw data layout."""

    def __init__(
        self,
        client: SECClient,
        *,
        raw_data_dir: str | Path = "data/raw/sec",
    ) -> None:
        self.client = client
        self.raw_data_dir = Path(raw_data_dir)

    def download(
        self,
        *,
        cik: str,
        accession_number: str,
        primary_document: str,
        expected_sha256: str | None = None,
    ) -> DownloadResult:
        destination = self.local_path(cik, accession_number, primary_document)
        source_url = build_primary_document_url(cik, accession_number, primary_document)

        if destination.is_file() and expected_sha256:
            local_hash = sha256_file(destination)
            if local_hash == expected_sha256:
                return DownloadResult(
                    local_path=destination,
                    sha256_hash=local_hash,
                    source_url=source_url,
                    size_bytes=destination.stat().st_size,
                    downloaded=False,
                )

        content = self.client.get_bytes(source_url)
        remote_hash = sha256_bytes(content)
        if destination.is_file() and sha256_file(destination) == remote_hash:
            return DownloadResult(
                local_path=destination,
                sha256_hash=remote_hash,
                source_url=source_url,
                size_bytes=len(content),
                downloaded=False,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary_path.write_bytes(content)
        temporary_path.replace(destination)
        return DownloadResult(
            local_path=destination,
            sha256_hash=remote_hash,
            source_url=source_url,
            size_bytes=len(content),
            downloaded=True,
        )

    def local_path(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> Path:
        filename = Path(primary_document).name
        if filename != primary_document or not filename:
            raise ValueError(f"Invalid primary document filename: {primary_document!r}")
        if re.fullmatch(r"[0-9-]+", accession_number) is None:
            raise ValueError(f"Invalid accession number: {accession_number!r}")
        return self.raw_data_dir / normalize_cik(cik) / accession_number / filename


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as filing:
        for block in iter(lambda: filing.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
