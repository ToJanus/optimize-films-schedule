from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .optimizer import DEFAULT_TIME_PROFILES, Location, load_plan


TOMTOM_ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute/{origin}:{destination}/json"
LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a travel_times JSON file for a film schedule input.")
    parser.add_argument("input", type=Path, help="Schedule input JSON containing cinemas and places with lat/lon.")
    parser.add_argument("output", type=Path, help="Path for generated travel_times JSON.")
    parser.add_argument("--provider", choices=("tomtom", "static"), default="tomtom")
    parser.add_argument("--api-key", default=os.getenv("TOMTOM_API_KEY"), help="TomTom API key or TOMTOM_API_KEY env var.")
    parser.add_argument("--cache-dir", type=Path, default=Path(".travel_cache"), help="Directory for historical route cache JSON files.")
    parser.add_argument("--profile", action="append", help="Time profile as id=HH:MM-HH:MM. Can be repeated.")
    parser.add_argument("--default-minutes", type=int, default=0, help="Fallback minutes stored in generated file.")
    parser.add_argument("--static-minutes", type=int, default=20, help="Minutes used by --provider static.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Delay between TomTom requests.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _configure_logging(args.verbose)
    LOGGER.info("Loading schedule input from %s", args.input)
    data = json.loads(args.input.read_text(encoding="utf-8"))
    *_unused, _settings, locations = load_plan(_without_existing_travel_times(data), args.input.parent)
    profiles = _parse_profiles(args.profile)
    _validate_coordinates(locations)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info(
        "Generating travel times: provider=%s, locations=%d, profiles=%d, cache_dir=%s",
        args.provider,
        len(locations),
        len(profiles),
        args.cache_dir,
    )

    output: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "default_minutes": args.default_minutes,
        "profiles": profiles,
        "times": {},
        "profile_times": {profile["id"]: {} for profile in profiles},
        "locations": [location.__dict__ for location in locations.values()],
    }

    ids = sorted(locations)
    route_count = 0
    for from_id in ids:
        for to_id in ids:
            if from_id == to_id:
                continue
            route_count += 1
            base = _fetch_or_static(args, locations[from_id], locations[to_id], None)
            _set_nested(output["times"], from_id, to_id, base)
            for profile in profiles:
                profiled = _fetch_or_static(args, locations[from_id], locations[to_id], profile)
                _set_nested(output["profile_times"][profile["id"]], from_id, to_id, profiled)
                time.sleep(args.sleep)
            time.sleep(args.sleep)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info(
        "Wrote %d base routes and %d profiled routes to %s", route_count, route_count * len(profiles), args.output
    )


def _without_existing_travel_times(data: dict[str, Any]) -> dict[str, Any]:
    """Return schedule input suitable for location loading while generating a new travel file.

    The generator only needs cinemas/places from the schedule. Existing travel-time
    configuration in that schedule may point at a file that does not exist yet (for
    example the file this command is about to create), so loading it here would make
    generation fail before any routes are produced.
    """
    if "travel_times_file" not in data and "travel_times" not in data:
        return data
    return {key: value for key, value in data.items() if key not in {"travel_times_file", "travel_times"}}


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def _parse_profiles(values: list[str] | None) -> list[dict[str, str]]:
    if not values:
        return list(DEFAULT_TIME_PROFILES)
    profiles = []
    for value in values:
        name, window = value.split("=", 1)
        start, end = window.split("-", 1)
        profiles.append({"id": name, "start": start, "end": end})
    return profiles


def _validate_coordinates(locations: dict[str, Location]) -> None:
    missing = [location.id for location in locations.values() if location.lat is None or location.lon is None]
    if missing:
        raise ValueError(f"Locations require manual lat/lon before routing: {', '.join(sorted(missing))}.")


def _fetch_or_static(args: argparse.Namespace, origin: Location, destination: Location, profile: dict[str, str] | None) -> dict[str, Any]:
    profile_id = profile["id"] if profile else "base"
    cache_path = args.cache_dir / f"{origin.id}__{destination.id}__{profile_id}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if _cache_matches_provider(cached, args.provider):
            LOGGER.info("Using cached %s route %s -> %s from %s", profile_id, origin.id, destination.id, cache_path)
            return cached["entry"]
        LOGGER.info(
            "Ignoring cached %s route %s -> %s from %s because it was created with provider=%s, requested provider=%s",
            profile_id,
            origin.id,
            destination.id,
            cache_path,
            _cache_provider(cached),
            args.provider,
        )
    if args.provider == "static":
        LOGGER.info(
            "Generating static %s route %s -> %s (%d minutes)",
            profile_id,
            origin.id,
            destination.id,
            args.static_minutes,
        )
        entry = {
            "minutes": args.static_minutes,
            "distance_meters": None,
            "no_traffic_minutes": args.static_minutes,
            "historic_traffic_minutes": args.static_minutes,
            "live_traffic_minutes": None,
            "traffic_delay_minutes": 0,
            "raw": {"provider": "static"},
        }
    else:
        if not args.api_key:
            raise ValueError("TomTom provider requires --api-key or TOMTOM_API_KEY.")
        LOGGER.info("Fetching TomTom %s route %s -> %s", profile_id, origin.id, destination.id)
        entry = _fetch_tomtom(args.api_key, origin, destination, profile)
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "provider": args.provider,
                "from_location_id": origin.id,
                "to_location_id": destination.id,
                "profile_id": profile["id"] if profile else None,
                "entry": entry,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    LOGGER.info("Cached %s route %s -> %s in %s", profile_id, origin.id, destination.id, cache_path)
    return entry


def _cache_matches_provider(cached: dict[str, Any], requested_provider: str) -> bool:
    provider = _cache_provider(cached)
    return provider is None or provider == requested_provider


def _cache_provider(cached: dict[str, Any]) -> str | None:
    provider = cached.get("provider")
    if isinstance(provider, str):
        return provider
    raw = cached.get("entry", {}).get("raw", {})
    raw_provider = raw.get("provider") if isinstance(raw, dict) else None
    return raw_provider if isinstance(raw_provider, str) else None


def _fetch_tomtom(api_key: str, origin: Location, destination: Location, profile: dict[str, str] | None) -> dict[str, Any]:
    url = TOMTOM_ROUTE_URL.format(
        origin=f"{origin.lat},{origin.lon}",
        destination=f"{destination.lat},{destination.lon}",
    )
    query = {"key": api_key, "traffic": "true", "travelMode": "car", "routeType": "fastest"}
    if profile is not None:
        query["departAt"] = _today_at(profile["start"])
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(query)}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - user-provided API endpoint is fixed
        payload = json.loads(response.read().decode("utf-8"))
    summary = payload["routes"][0]["summary"]
    travel_seconds = int(summary.get("travelTimeInSeconds", 0))
    no_traffic_seconds = summary.get("noTrafficTravelTimeInSeconds")
    historic_seconds = summary.get("historicTrafficTravelTimeInSeconds")
    live_seconds = summary.get("liveTrafficIncidentsTravelTimeInSeconds")
    return {
        "minutes": _ceil_minutes(travel_seconds),
        "distance_meters": int(summary.get("lengthInMeters", 0)),
        "no_traffic_minutes": _ceil_minutes(no_traffic_seconds) if no_traffic_seconds is not None else None,
        "historic_traffic_minutes": _ceil_minutes(historic_seconds) if historic_seconds is not None else None,
        "live_traffic_minutes": _ceil_minutes(live_seconds) if live_seconds is not None else None,
        "traffic_delay_minutes": _ceil_minutes(max(0, travel_seconds - int(no_traffic_seconds))) if no_traffic_seconds else 0,
        "raw": {"provider": "tomtom", **summary},
    }


def _today_at(clock: str) -> str:
    today = datetime.now().date().isoformat()
    return f"{today}T{clock}:00"


def _ceil_minutes(seconds: int) -> int:
    return (int(seconds) + 59) // 60


def _set_nested(mapping: dict[str, Any], from_id: str, to_id: str, value: dict[str, Any]) -> None:
    mapping.setdefault(from_id, {})[to_id] = value


if __name__ == "__main__":
    main()
