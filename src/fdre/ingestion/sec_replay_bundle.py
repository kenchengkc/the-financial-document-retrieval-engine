"""Deterministic offline bundles for exact SEC source-byte/parser replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, cast
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Document, DocumentElement
from fdre.parsing.base import ElementType, ParsedElement
from fdre.parsing.sec_provenance import (
    SECParseProvenance,
    parse_provenance_from_metadata,
    parsed_elements_sha256,
    verify_sec_filing_replay,
)

SEC_REPLAY_BUNDLE_VERSION = "sec-raw-parser-replay-bundle-v1"
_MANIFEST_MEMBER = "manifest.json"
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class SECReplayBundleEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    accession_number: str
    source_url: str | None = None
    raw_member: str
    raw_sha256: str = Field(min_length=64, max_length=64)
    raw_size_bytes: int = Field(ge=0)
    parser_name: str
    parser_version: str
    parsed_elements_sha256: str = Field(min_length=64, max_length=64)
    parsed_element_count: int = Field(ge=0)

    def provenance(self) -> SECParseProvenance:
        return SECParseProvenance(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            raw_sha256=self.raw_sha256,
            raw_size_bytes=self.raw_size_bytes,
            parsed_elements_sha256=self.parsed_elements_sha256,
            parsed_element_count=self.parsed_element_count,
            source_url=self.source_url,
        )


class SECReplayBundleManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundle_version: Literal["sec-raw-parser-replay-bundle-v1"] = SEC_REPLAY_BUNDLE_VERSION
    bundle_id: str = Field(min_length=64, max_length=64)
    entries: list[SECReplayBundleEntry]


def build_sec_replay_bundle(
    session: Session,
    *,
    accession_numbers: list[str],
    destination: str | Path,
) -> SECReplayBundleManifest:
    """Freeze exact retained raw bytes after proving they reproduce the persisted corpus."""

    requested = sorted(set(accession_numbers))
    if not requested:
        raise ValueError("SEC replay bundle requires at least one accession")
    if len(requested) != len(accession_numbers):
        raise ValueError("SEC replay bundle accession scope contains duplicates")

    documents = list(
        session.scalars(
            select(Document)
            .where(Document.accession_number.in_(requested))
            .order_by(Document.accession_number)
        )
    )
    found = [document.accession_number for document in documents]
    missing = sorted(set(requested) - set(found))
    if missing:
        raise ValueError("SEC replay bundle is missing documents: " + ", ".join(missing))

    entries: list[SECReplayBundleEntry] = []
    raw_members: dict[str, bytes] = {}
    for document in documents:
        provenance = parse_provenance_from_metadata(document.metadata_json)
        if provenance is None:
            raise ValueError(
                f"Document {document.accession_number} has no exact SEC parse provenance; "
                "legacy parsed rows cannot be upgraded by redownloading"
            )
        if document.sha256_hash != provenance.raw_sha256:
            raise ValueError(
                f"Document {document.accession_number} raw hash disagrees with parse provenance"
            )
        if not document.local_path:
            raise ValueError(
                f"Document {document.accession_number} has no retained raw filing path"
            )
        raw_path = Path(document.local_path)
        if not raw_path.is_file():
            raise ValueError(
                f"Document {document.accession_number} raw filing is not retained at "
                f"{raw_path}"
            )
        raw_bytes = raw_path.read_bytes()
        verify_sec_filing_replay(raw_bytes, provenance)

        persisted_elements = _load_persisted_elements(session, document.id)
        if len(persisted_elements) != provenance.parsed_element_count:
            raise ValueError(
                f"Document {document.accession_number} persisted element count differs "
                "from parse provenance"
            )
        if parsed_elements_sha256(persisted_elements) != provenance.parsed_elements_sha256:
            raise ValueError(
                f"Document {document.accession_number} persisted elements differ "
                "from parse provenance"
            )

        raw_member = f"raw/{provenance.raw_sha256}.bin"
        existing_bytes = raw_members.get(raw_member)
        if existing_bytes is not None and existing_bytes != raw_bytes:
            raise ValueError("SEC replay bundle raw-member SHA collision")
        raw_members[raw_member] = raw_bytes
        entries.append(
            SECReplayBundleEntry(
                accession_number=document.accession_number,
                source_url=provenance.source_url,
                raw_member=raw_member,
                raw_sha256=provenance.raw_sha256,
                raw_size_bytes=provenance.raw_size_bytes,
                parser_name=provenance.parser_name,
                parser_version=provenance.parser_version,
                parsed_elements_sha256=provenance.parsed_elements_sha256,
                parsed_element_count=provenance.parsed_element_count,
            )
        )

    manifest_payload = {
        "bundle_version": SEC_REPLAY_BUNDLE_VERSION,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    manifest = SECReplayBundleManifest(
        bundle_id=_stable_digest(manifest_payload),
        **manifest_payload,
    )
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination_path, "w") as archive:
        _write_member(archive, _MANIFEST_MEMBER, _manifest_bytes(manifest))
        for member, content in sorted(raw_members.items()):
            _write_member(archive, member, content)
    verify_sec_replay_bundle(destination_path)
    return manifest


def verify_sec_replay_bundle(path: str | Path) -> SECReplayBundleManifest:
    """Verify a portable bundle and re-run every parser from its embedded exact bytes."""

    with ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("SEC replay bundle contains duplicate archive members")
        if _MANIFEST_MEMBER not in names:
            raise ValueError("SEC replay bundle is missing manifest.json")
        manifest = SECReplayBundleManifest.model_validate_json(
            archive.read(_MANIFEST_MEMBER)
        )
        _validate_manifest_identity(manifest)
        expected_members = {_MANIFEST_MEMBER, *(entry.raw_member for entry in manifest.entries)}
        if set(names) != expected_members:
            raise ValueError("SEC replay bundle archive members do not match its manifest")

        for entry in manifest.entries:
            raw_bytes = archive.read(entry.raw_member)
            if len(raw_bytes) != entry.raw_size_bytes:
                raise ValueError(
                    f"SEC replay raw size mismatch for {entry.accession_number}"
                )
            actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            if actual_sha256 != entry.raw_sha256:
                raise ValueError(
                    f"SEC replay raw hash mismatch for {entry.accession_number}"
                )
            verify_sec_filing_replay(raw_bytes, entry.provenance())
    return manifest


def sec_replay_bundle_sha256(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_persisted_elements(session: Session, document_id: int) -> list[ParsedElement]:
    rows = session.scalars(
        select(DocumentElement)
        .where(DocumentElement.document_id == document_id)
        .order_by(DocumentElement.reading_order, DocumentElement.id)
    )
    elements: list[ParsedElement] = []
    for row in rows:
        if row.reading_order is None:
            raise ValueError(f"Document element {row.id} has no reading order")
        elements.append(
            ParsedElement(
                element_type=cast(ElementType, row.element_type),
                text=row.text,
                markdown=row.markdown,
                page_number=row.page_number,
                section=row.section,
                bbox=row.bbox,
                reading_order=row.reading_order,
                metadata=dict(row.json_payload or {}),
            )
        )
    return elements


def _validate_manifest_identity(manifest: SECReplayBundleManifest) -> None:
    if manifest.bundle_version != SEC_REPLAY_BUNDLE_VERSION:
        raise ValueError(f"unsupported SEC replay bundle version {manifest.bundle_version!r}")
    accessions = [entry.accession_number for entry in manifest.entries]
    if (
        not accessions
        or accessions != sorted(accessions)
        or len(accessions) != len(set(accessions))
    ):
        raise ValueError("SEC replay bundle accessions are not canonical")
    payload = {
        "bundle_version": manifest.bundle_version,
        "entries": [entry.model_dump(mode="json") for entry in manifest.entries],
    }
    if _stable_digest(payload) != manifest.bundle_id:
        raise ValueError("SEC replay bundle manifest digest mismatch")


def _manifest_bytes(manifest: SECReplayBundleManifest) -> bytes:
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_member(archive: ZipFile, name: str, content: bytes) -> None:
    info = ZipInfo(filename=name, date_time=_ZIP_EPOCH)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, content)


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
