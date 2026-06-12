from __future__ import annotations

import argparse
import json
from pathlib import Path

from .optimizer import load_plan, optimize_schedule, option_to_dict, option_to_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize one-day cinema movie schedules.")
    parser.add_argument("input", type=Path, help="Path to a JSON input file with films, cinemas and screenings.")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of options to print. Use 0 for all.")
    parser.add_argument(
        "--all-films",
        action="store_true",
        help="Only show schedules that contain every distinct film from the input exactly once.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    films, cinemas, screenings, priority_weights, travel_times = load_plan(data)
    options = optimize_schedule(
        films,
        cinemas,
        screenings,
        priority_weights,
        travel_times,
        require_all_films=args.all_films,
    )
    selected = options if args.limit == 0 else options[: args.limit]

    if args.format == "json":
        print(json.dumps([option_to_dict(option) for option in selected], ensure_ascii=False, indent=2))
        return

    if not selected:
        print("Brak możliwych terminarzy dla podanych ograniczeń.")
        return

    for ordinal, option in enumerate(selected, start=1):
        print(option_to_text(option, ordinal))


if __name__ == "__main__":
    main()
