from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank HU-5 provisional membership blockers by strict-day unlock impact."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def build_remediation_queue(payload: dict[str, Any]) -> dict[str, Any]:
    blockers = {
        str(item["blocker_id"]): item
        for item in payload.get("membership_blockers", [])
    }
    segments = [
        {
            "day_count": int(item["day_count"]),
            "blocker_ids": set(item.get("membership_blocker_ids", [])),
        }
        for item in payload.get("segments", [])
        if item.get("membership_blocker_ids")
    ]
    remaining = set(blockers)
    ranked: list[dict[str, Any]] = []
    cumulative_unlocked = 0

    while remaining:
        choices: list[tuple[int, float, int, str]] = []
        for blocker_id in sorted(remaining):
            marginal = sum(
                segment["day_count"]
                for segment in segments
                if (segment["blocker_ids"] & remaining) == {blocker_id}
            )
            pressure = sum(
                segment["day_count"] / len(segment["blocker_ids"] & remaining)
                for segment in segments
                if blocker_id in (segment["blocker_ids"] & remaining)
            )
            active_days = int(blockers[blocker_id].get("active_day_count", 0))
            choices.append((marginal, pressure, active_days, blocker_id))

        marginal, pressure, _active_days, selected = max(
            choices,
            key=lambda item: (item[0], item[1], item[2], item[3]),
        )
        remaining.remove(selected)
        cumulative_unlocked += marginal
        blocker = blockers[selected]
        ranked.append(
            {
                "rank": len(ranked) + 1,
                "blocker_id": selected,
                "security_id": blocker["security_id"],
                "cik": blocker.get("cik"),
                "symbols": blocker.get("symbols", []),
                "effective_from": blocker["effective_from"],
                "effective_to": blocker.get("effective_to"),
                "source_hash": blocker["source_hash"],
                "active_day_count": int(blocker.get("active_day_count", 0)),
                "exclusive_day_count": int(blocker.get("exclusive_day_count", 0)),
                "marginal_unlocked_day_count": marginal,
                "cumulative_unlocked_day_count": cumulative_unlocked,
                "blocking_pressure_score": round(pressure, 6),
            }
        )

    return {
        "schema_version": "fdre-hu5-strict-remediation-queue-v1",
        "blocker_audit_id": payload.get("blocker_audit_id"),
        "input_provenance_id": payload.get("input_provenance_id"),
        "universe_code": payload.get("universe_code"),
        "window_start": payload.get("window_start"),
        "window_end": payload.get("window_end"),
        "membership_blocker_count": len(blockers),
        "membership_blocked_day_count": int(payload.get("membership_blocked_day_count", 0)),
        "ranked_membership_blockers": ranked,
    }


def main() -> int:
    args = _parser().parse_args()
    payload = json.loads(args.input.read_text())
    queue = build_remediation_queue(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n")

    print(
        json.dumps(
            {
                "blocker_audit_id": queue["blocker_audit_id"],
                "membership_blocker_count": queue["membership_blocker_count"],
                "top_blockers": queue["ranked_membership_blockers"][:10],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
