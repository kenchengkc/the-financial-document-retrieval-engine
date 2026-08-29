from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from apps.api.app.db import get_engine
from fdre.research.experiment_registry import (
    inspect_research_experiment,
    replay_research_experiment,
    verify_research_experiment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, verify, or replay a registered FDRE research experiment."
    )
    parser.add_argument("action", choices=["inspect", "verify", "replay"])
    parser.add_argument("experiment_id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    with Session(get_engine()) as session:
        if args.action == "inspect":
            payload = inspect_research_experiment(
                session, args.experiment_id
            ).model_dump(mode="json")
        elif args.action == "verify":
            payload = verify_research_experiment(
                session, args.experiment_id
            ).model_dump(mode="json")
        else:
            payload = replay_research_experiment(
                session, args.experiment_id
            ).model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
