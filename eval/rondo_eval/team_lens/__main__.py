"""Command-line entry point for offline Team Lens reduction and rendering."""

import argparse
from pathlib import Path

from .reducer import write_team_view
from .report import write_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.team_lens")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reduce_parser = subparsers.add_parser("reduce", help="reduce a native rollout bundle")
    reduce_parser.add_argument("--product", choices=("codex", "rondo-multi"), required=True)
    reduce_parser.add_argument("--bundle", type=Path, required=True)
    reduce_parser.add_argument("--output", type=Path, required=True)

    report_parser = subparsers.add_parser("report", help="render a normalized Team View")
    report_parser.add_argument("--input", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "reduce":
        write_team_view(args.bundle, args.product, args.output)
    else:
        write_report(args.input, args.output)


if __name__ == "__main__":
    main()
