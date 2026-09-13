"""Crash-recoverable CLI for HU-2 production materialization.

A successful apply persists an operation receipt in the same database transaction as the
historical-universe mutation. Report export happens only after commit, so a filesystem or process
failure can be recovered by operation ID without replaying the mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.operation_receipts import OperationReceipt
from fdre.research.historical_universe import promotion

_OPERATION_TYPE = "hu2_production_materialization_v1"
_REQUEST_SCHEMA_VERSION = "fdre-hu2-promotion-operation-v1"
_REQUIRED_SOURCE_ARGS = (
    "component_history",
    "component_history_ref",
    "current_components",
    "ticker_lineages",
    "ticker_lineages_ref",
    "anchor",
    "boundary_audit",
)


def _hash_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_operation_id(value: str) -> str:
    operation_id = value.strip()
    if not operation_id:
        raise ValueError("operation ID must not be empty")
    if len(operation_id) > 128:
        raise ValueError("operation ID must be at most 128 characters")
    return operation_id


def _request_payload(args: argparse.Namespace) -> dict[str, object]:
    component_history = cast(Path, args.component_history)
    current_components = cast(Path, args.current_components)
    ticker_lineages = cast(Path, args.ticker_lineages)
    anchor = cast(Path, args.anchor)
    boundary_audit = cast(Path, args.boundary_audit)
    return {
        "schema_version": _REQUEST_SCHEMA_VERSION,
        "operation_type": _OPERATION_TYPE,
        "component_history_sha256": _hash_file(component_history),
        "component_history_ref": cast(str, args.component_history_ref),
        "current_components_sha256": _hash_file(current_components),
        "ticker_lineages_sha256": _hash_file(ticker_lineages),
        "ticker_lineages_ref": cast(str, args.ticker_lineages_ref),
        "anchor_sha256": _hash_file(anchor),
        "boundary_audit_sha256": _hash_file(boundary_audit),
        # Preserve the caller's request rather than a generated wall-clock timestamp. If an apply
        # dies before commit, retrying the same request remains the same operation. If it dies after
        # commit, the durable receipt short-circuits the mutation entirely.
        "observed_at": args.observed_at,
    }


def _validated_receipt_payload(
    receipt: OperationReceipt,
    *,
    expected_request_sha256: str | None = None,
) -> dict[str, object]:
    if receipt.operation_type != _OPERATION_TYPE:
        raise RuntimeError(
            f"operation ID {receipt.operation_id!r} belongs to {receipt.operation_type!r}, "
            f"not {_OPERATION_TYPE!r}"
        )
    if (
        expected_request_sha256 is not None
        and receipt.request_sha256 != expected_request_sha256
    ):
        raise RuntimeError(
            f"operation ID {receipt.operation_id!r} was already used for a different request"
        )
    payload = dict(receipt.payload_json)
    actual_payload_sha256 = _hash_json(payload)
    if actual_payload_sha256 != receipt.payload_sha256:
        raise RuntimeError(
            f"operation receipt {receipt.operation_id!r} failed payload integrity validation"
        )
    return payload


def _load_receipt(
    session: Session,
    operation_id: str,
    *,
    expected_request_sha256: str | None = None,
) -> dict[str, object] | None:
    receipt = session.get(OperationReceipt, operation_id)
    if receipt is None:
        return None
    return _validated_receipt_payload(
        receipt,
        expected_request_sha256=expected_request_sha256,
    )


def _stage_receipt(
    session: Session,
    *,
    operation_id: str,
    request_sha256: str,
    payload: dict[str, object],
) -> OperationReceipt:
    receipt = OperationReceipt(
        operation_id=operation_id,
        operation_type=_OPERATION_TYPE,
        request_sha256=request_sha256,
        payload_sha256=_hash_json(payload),
        payload_json=payload,
    )
    session.add(receipt)
    # Force uniqueness/integrity failures to happen before commit returns. The receipt and all HU
    # rows remain in the same transaction either way.
    session.flush()
    return receipt


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_report(
    *,
    plan: promotion.MaterializationPlan,
    apply_requested: bool,
    applied: bool,
    validation_payload: dict[str, object],
    operation_id: str | None = None,
    request_sha256: str | None = None,
) -> dict[str, object]:
    payload = plan.as_dict()
    payload["apply_requested"] = apply_requested
    payload["applied"] = applied
    payload["validation"] = validation_payload
    if operation_id is not None:
        payload["operation_id"] = operation_id
    if request_sha256 is not None:
        payload["operation_request_sha256"] = request_sha256
    payload["interpretation"] = (
        "Historical-only issuers use ticker=null. Membership is verified only on exact interval "
        "agreement or the pinned cross-source boundary adjudication; other source-backed "
        "intervals remain provisional. lawcal created_at is used only when no independent exact "
        "ticker-start evidence exists. Dry-run planning performs no writes. An explicit apply is "
        "committed only when its strict and provisional anchor snapshots, interval audit, identity "
        "coverage, and deterministic replay all pass. Successful applies persist an operation "
        "receipt atomically with the mutation so post-commit report failures can be recovered "
        "without replaying the mutation."
    )
    return payload


def _load_inputs(
    args: argparse.Namespace,
) -> tuple[
    tuple[promotion.HistoricalComponentRecord, ...],
    dict[str, promotion.CurrentIssuer],
    set[tuple[str, promotion.date, promotion.date | None]],
    promotion.AnchorExpectation,
    promotion.BoundaryVerification,
]:
    records = promotion.HistoricalComponentHistoryAdapter(
        source_ref=cast(str, args.component_history_ref)
    ).load(cast(Path, args.component_history))
    current = promotion._load_current(cast(Path, args.current_components))
    verified = promotion._verified_interval_keys(
        cast(Path, args.ticker_lineages),
        cast(str, args.ticker_lineages_ref),
    )
    anchor = promotion._load_anchor(cast(Path, args.anchor))
    boundary_verification = promotion._load_boundary_verification(
        cast(Path, args.boundary_audit)
    )
    return records, current, verified, anchor, boundary_verification


def _observed_at(value: str | None) -> datetime:
    observed_at = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(UTC)
    )
    if observed_at.tzinfo is None:
        raise ValueError("observed-at must be timezone-aware")
    return observed_at


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize HU-2 production universe rows.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--component-history", type=Path)
    parser.add_argument("--component-history-ref")
    parser.add_argument("--current-components", type=Path)
    parser.add_argument("--ticker-lineages", type=Path)
    parser.add_argument("--ticker-lineages-ref")
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--boundary-audit", type=Path)
    parser.add_argument("--observed-at")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument(
        "--recover-operation-id",
        help="Export a committed operation receipt without replaying the mutation.",
    )
    parser.add_argument(
        "--operation-id",
        help="Stable idempotency key. Required for --apply.",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.recover_operation_id:
        if args.operation_id:
            parser.error("--operation-id cannot be combined with --recover-operation-id")
        _validate_operation_id(cast(str, args.recover_operation_id))
        return

    missing = [name for name in _REQUIRED_SOURCE_ARGS if getattr(args, name) is None]
    if missing:
        parser.error(
            "source arguments are required outside recovery mode: "
            + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        )
    if args.apply and not args.operation_id:
        parser.error("--operation-id is required with --apply")
    if args.operation_id and not args.apply:
        parser.error("--operation-id requires --apply")
    if args.operation_id:
        _validate_operation_id(cast(str, args.operation_id))


def _recover(
    *,
    database_url: str,
    operation_id: str,
    output: Path,
) -> int:
    engine = create_db_engine(database_url)
    try:
        with Session(engine) as session:
            payload = _load_receipt(session, operation_id)
            session.rollback()
    finally:
        engine.dispose()
    if payload is None:
        raise RuntimeError(f"operation receipt {operation_id!r} does not exist")
    _write_report(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    if args.recover_operation_id:
        return _recover(
            database_url=cast(str, args.database_url),
            operation_id=_validate_operation_id(cast(str, args.recover_operation_id)),
            output=cast(Path, args.output),
        )

    request_sha256 = _hash_json(_request_payload(args)) if args.apply else None
    operation_id = (
        _validate_operation_id(cast(str, args.operation_id)) if args.operation_id else None
    )

    engine = create_db_engine(cast(str, args.database_url))
    try:
        with Session(engine) as session:
            if args.apply and operation_id is not None and request_sha256 is not None:
                existing = _load_receipt(
                    session,
                    operation_id,
                    expected_request_sha256=request_sha256,
                )
                if existing is not None:
                    session.rollback()
                    payload = existing
                else:
                    payload = _execute_new(
                        session,
                        args=args,
                        operation_id=operation_id,
                        request_sha256=request_sha256,
                    )
            else:
                payload = _execute_new(
                    session,
                    args=args,
                    operation_id=None,
                    request_sha256=None,
                )
    finally:
        engine.dispose()

    _write_report(cast(Path, args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.apply and not bool(payload.get("applied")):
        return 2
    return 0


def _execute_new(
    session: Session,
    *,
    args: argparse.Namespace,
    operation_id: str | None,
    request_sha256: str | None,
) -> dict[str, object]:
    records, current, verified, anchor, boundary_verification = _load_inputs(args)
    try:
        plan = promotion.materialize(
            session,
            records=records,
            current_by_cik=current,
            verified_intervals=verified,
            observed_at=_observed_at(args.observed_at),
            stage=args.apply,
            boundary_verification=boundary_verification,
            anchor=anchor,
        )
        if args.apply:
            validation = promotion.validate_materialized_state(session, anchor)
            validation_payload = validation.as_dict()
            applied = validation.commit_eligible
            payload = _build_report(
                plan=plan,
                apply_requested=True,
                applied=applied,
                validation_payload=validation_payload,
                operation_id=operation_id,
                request_sha256=request_sha256,
            )
            if applied:
                if operation_id is None or request_sha256 is None:
                    raise RuntimeError("apply requires an operation receipt identity")
                _stage_receipt(
                    session,
                    operation_id=operation_id,
                    request_sha256=request_sha256,
                    payload=payload,
                )
                session.commit()
            else:
                session.rollback()
            return payload

        validation_payload: dict[str, object] = {
            "anchor_id": anchor.anchor_id,
            "universe_code": anchor.universe_code,
            "as_of": anchor.effective_at.isoformat(),
            "status": "not_run",
            "reason": (
                "Exact validation requires an explicit staged apply transaction. "
                "Dry-run planning performs no inserts, updates, or sequence advances."
            ),
            "commit_eligible": False,
        }
        session.rollback()
        return _build_report(
            plan=plan,
            apply_requested=False,
            applied=False,
            validation_payload=validation_payload,
        )
    except Exception:
        session.rollback()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
