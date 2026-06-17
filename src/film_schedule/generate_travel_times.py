from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .optimizer import DEFAULT_TIME_PROFILES, Location, load_plan


TOMTOM_ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute/{origin}:{destination}/json"


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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    *_unused, _settings, locations = load_plan(data, args.input.parent)
    profiles = _parse_profiles(args.profile)
    _validate_coordinates(locations)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

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
    for from_id in ids:
        for to_id in ids:
            if from_id == to_id:
                continue
            base = _fetch_or_static(args, locations[from_id], locations[to_id], None)
            _set_nested(output["times"], from_id, to_id, base)
            for profile in profiles:
                profiled = _fetch_or_static(args, locations[from_id], locations[to_id], profile)
                _set_nested(output["profile_times"][profile["id"]], from_id, to_id, profiled)
                time.sleep(args.sleep)
            time.sleep(args.sleep)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


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
    cache_path = args.cache_dir / f"{origin.id}__{destination.id}__{profile['id'] if profile else 'base'}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))["entry"]
    if args.provider == "static":
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
        entry = _fetch_tomtom(args.api_key, origin, destination, profile)
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
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
    return entry


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
        "raw": summary,
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
