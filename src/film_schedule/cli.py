from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from .optimizer import (
    ScheduleOption,
    load_plan,
    optimize_schedule,
    option_to_dict,
    option_to_text,
    parse_clock,
)


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
    parser.add_argument(
        "--earliest-start",
        type=_parse_clock_argument,
        help="Earliest movie start time in HH:MM format.",
    )
    parser.add_argument(
        "--latest-end",
        type=_parse_clock_argument,
        help="Latest movie end time in HH:MM format.",
    )
    parser.add_argument(
        "--travel-times",
        type=Path,
        help="Override or provide an external travel_times JSON file.",
    )
    parser.add_argument(
        "--sort-by-risk",
        action="store_true",
        help="Prefer lower-risk schedules after requirements, score and film count.",
    )
    parser.add_argument(
        "--validate-routes",
        type=int,
        default=0,
        metavar="N",
        help="Print route legs from the top N optimized schedules for optional live/API validation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Save one aggregate result file and every single schedule option as a separate file "
            "in a newly created sibling subdirectory."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if (
        args.earliest_start is not None
        and args.latest_end is not None
        and args.earliest_start > args.latest_end
    ):
        parser.error("--earliest-start cannot be later than --latest-end.")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if args.travel_times:
        data["travel_times_file"] = str(args.travel_times)
    if args.sort_by_risk:
        data.setdefault("optimization_settings", {})["sort_by_risk"] = True
    films, cinemas, screenings, priority_weights, travel_times, constraints, settings, _locations = load_plan(data, args.input.parent)
    options = optimize_schedule(
        films,
        cinemas,
        screenings,
        priority_weights,
        travel_times,
        constraints,
        require_all_films=args.all_films,
        earliest_start=args.earliest_start,
        latest_end=args.latest_end,
        optimization_settings=settings,
    )
    selected = options if args.limit == 0 else options[: args.limit]

    if args.validate_routes:
        print(json.dumps(_route_validation_payload(selected[: args.validate_routes]), ensure_ascii=False, indent=2))
        return

    if args.output:
        records_dir = save_options(selected, args.output, args.format)
        print(f"Zapisano {len(selected)} terminarzy do {args.output} oraz do katalogu {records_dir}.")
        return

    if args.format == "json":
        print(json.dumps([option_to_dict(option) for option in selected], ensure_ascii=False, indent=2))
        return

    if not selected:
        print("Brak możliwych terminarzy dla podanych ograniczeń.")
        return

    for ordinal, option in enumerate(selected, start=1):
        print(option_to_text(option, ordinal))


def _route_validation_payload(options: Sequence[ScheduleOption]) -> list[dict[str, object]]:
    return [
        {
            "option": ordinal,
            "score": option.score,
            "risk_score": option.risk_score,
            "routes": option_to_dict(option)["routes"],
        }
        for ordinal, option in enumerate(options, start=1)
    ]


def save_options(options: Sequence[ScheduleOption], output_path: Path, output_format: str) -> Path:
    """Save an aggregate file and one file per schedule option."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    records_dir = output_path.with_name(f"{output_path.stem}_records")
    records_dir.mkdir(parents=True, exist_ok=True)

    if output_format == "json":
        output_path.write_text(
            json.dumps([option_to_dict(option) for option in options], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for ordinal, option in enumerate(options, start=1):
            record_path = records_dir / f"{ordinal:03d}_{_slugify_option(option, ordinal)}.json"
            record_path.write_text(
                json.dumps(option_to_dict(option), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return records_dir

    if options:
        text = "\n\n".join(option_to_text(option, ordinal) for ordinal, option in enumerate(options, start=1))
    else:
        text = "Brak możliwych terminarzy dla podanych ograniczeń."
    output_path.write_text(f"{text}\n", encoding="utf-8")
    for ordinal, option in enumerate(options, start=1):
        record_path = records_dir / f"{ordinal:03d}_{_slugify_option(option, ordinal)}.txt"
        record_path.write_text(f"{option_to_text(option, ordinal)}\n", encoding="utf-8")
    return records_dir


def _parse_clock_argument(value: str) -> int:
    try:
        return parse_clock(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected time in HH:MM format.") from error


def _slugify_option(option: ScheduleOption, ordinal: int) -> str:
    if not option.screenings:
        return f"option_{ordinal:03d}"
    starts_at = option.screenings[0].movie_starts_at
    ends_at = option.screenings[-1].movie_ends_at
    title = option.screenings[0].film.title
    raw = f"{starts_at:04d}_{ends_at:04d}_{title}"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower()
    return slug or f"option_{ordinal:03d}"


if __name__ == "__main__":
    main()
