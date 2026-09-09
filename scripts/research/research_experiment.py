from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import get_engine
from fdre.research.experiment_registry import (
    build_research_experiment_bundle,
    inspect_research_experiment,
    read_research_experiment_bundle,
    replay_research_experiment,
    verify_research_experiment,
    verify_research_experiment_bundle,
    write_research_experiment_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect, verify, replay, export, or independently verify an FDRE research experiment."
        )
    )
    parser.add_argument(
        "action",
        choices=["inspect", "verify", "replay", "bundle", "verify-bundle"],
    )
    parser.add_argument(
        "target",
        help="Experiment id for registry actions, or bundle path for verify-bundle.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a bundle to this path instead of printing the full JSON payload.",
    )
    parser.add_argument(
        "--expected-experiment-id",
        help="For verify-bundle, require the portable bundle to match this pinned root id.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.action == "verify-bundle":
        bundle = read_research_experiment_bundle(args.target)
        result = verify_research_experiment_bundle(
            bundle,
            expected_experiment_id=args.expected_experiment_id,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0

    with Session(get_engine()) as session:
        if args.action == "inspect":
            payload = inspect_research_experiment(session, args.target).model_dump(mode="json")
        elif args.action == "verify":
            payload = verify_research_experiment(session, args.target).model_dump(mode="json")
        elif args.action == "replay":
            payload = replay_research_experiment(session, args.target).model_dump(mode="json")
        else:
            bundle = build_research_experiment_bundle(session, args.target)
            if args.output is not None:
                destination = write_research_experiment_bundle(args.output, bundle)
                payload = {
                    "experiment_id": bundle.experiment_id,
                    "bundle_sha256": bundle.bundle_sha256,
                    "output": str(destination),
                }
            else:
                payload = bundle.model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
