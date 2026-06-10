from __future__ import annotations

import argparse
import subprocess
import sys

from fdre.ingestion.ticker_map import DEFAULT_SAMPLE_TICKERS, sp500_batch_tickers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SEC ingest pipeline for a ticker batch (metadata → parse → chunk → index)"
    )
    parser.add_argument(
        "--universe",
        choices=["megacap", "sp500"],
        default="megacap",
        help="Ticker universe to ingest",
    )
    parser.add_argument("--tickers", nargs="+", help="Explicit tickers (overrides universe)")
    parser.add_argument("--offset", type=int, default=0, help="Batch offset for sp500 universe")
    parser.add_argument("--limit", type=int, default=10, help="Batch size")
    parser.add_argument("--forms", nargs="+", default=["10-K", "10-Q"])
    parser.add_argument("--filing-limit", type=int, default=1, help="Latest N filings per form")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--force-rechunk", action="store_true")
    return parser.parse_args()


def _selected_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [ticker.upper() for ticker in args.tickers]
    if args.universe == "sp500":
        return sp500_batch_tickers(offset=args.offset, limit=args.limit)
    return list(DEFAULT_SAMPLE_TICKERS)


def _run(command: list[str]) -> None:
    print({"run": " ".join(command)}, flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    tickers = _selected_tickers(args)
    if not tickers:
        print({"status": "empty_batch", "offset": args.offset, "limit": args.limit})
        return

    ticker_args = ["--tickers", *tickers]
    form_args = ["--forms", *args.forms]

    _run(
        [
            sys.executable,
            "scripts/ingest_sec_sample.py",
            *ticker_args,
            *form_args,
            "--limit",
            str(args.filing_limit),
        ]
    )

    download_cmd = [
        sys.executable,
        "-m",
        "scripts.download_filings",
        *ticker_args,
        *form_args,
        "--limit",
        str(args.filing_limit),
        "--download",
        "--parse",
    ]
    if args.force_parse:
        download_cmd.append("--force-parse")
    _run(download_cmd)

    chunk_cmd = [sys.executable, "-m", "scripts.retrieval_pipeline", "chunk", *ticker_args]
    if args.force_rechunk:
        chunk_cmd.append("--force-rechunk")
    _run(chunk_cmd)

    _run([sys.executable, "-m", "scripts.retrieval_pipeline", "index", *ticker_args])

    print(
        {
            "status": "completed",
            "universe": args.universe,
            "tickers": tickers,
            "offset": args.offset,
            "limit": args.limit,
        }
    )


if __name__ == "__main__":
    main()
