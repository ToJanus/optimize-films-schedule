from __future__ import annotations

import argparse
import json
from pathlib import Path

from film_schedule.generate_travel_times import _fetch_or_static, main
from film_schedule.optimizer import Location


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "routes": [
                    {
                        "summary": {
                            "travelTimeInSeconds": 1500,
                            "lengthInMeters": 4200,
                            "noTrafficTravelTimeInSeconds": 1200,
                            "historicTrafficTravelTimeInSeconds": 1320,
                            "liveTrafficIncidentsTravelTimeInSeconds": 1500,
                        }
                    }
                ]
            }
        ).encode("utf-8")


def _args(tmp_path: Path, provider: str) -> argparse.Namespace:
    return argparse.Namespace(provider=provider, api_key="key", cache_dir=tmp_path, static_minutes=20)


def _location(location_id: str, lat: float, lon: float) -> Location:
    return Location(id=location_id, name=location_id, kind="place", address=None, lat=lat, lon=lon)


def test_tomtom_ignores_static_cache_and_rewrites_provider(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "a__b__base.json"
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-01-01T00:00:00+00:00",
                "from_location_id": "a",
                "to_location_id": "b",
                "profile_id": None,
                "entry": {"minutes": 20, "raw": {"provider": "static"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("film_schedule.generate_travel_times.urllib.request.urlopen", lambda request, timeout: _Response())

    entry = _fetch_or_static(_args(tmp_path, "tomtom"), _location("a", 1.0, 2.0), _location("b", 3.0, 4.0), None)

    assert entry["minutes"] == 25
    assert entry["raw"]["provider"] == "tomtom"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["provider"] == "tomtom"
    assert cached["entry"]["raw"]["provider"] == "tomtom"


def test_static_cache_is_reused_for_static_provider(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "a__b__base.json"
    cache_path.write_text(
        json.dumps({"provider": "static", "entry": {"minutes": 20, "raw": {"provider": "static"}}}),
        encoding="utf-8",
    )

    def fail_urlopen(request, timeout):
        raise AssertionError("TomTom should not be called for static cache")

    monkeypatch.setattr("film_schedule.generate_travel_times.urllib.request.urlopen", fail_urlopen)

    entry = _fetch_or_static(_args(tmp_path, "static"), _location("a", 1.0, 2.0), _location("b", 3.0, 4.0), None)

    assert entry == {"minutes": 20, "raw": {"provider": "static"}}


def test_main_ignores_existing_travel_times_file_while_generating_static(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "schedule.json"
    output_path = tmp_path / "generated_travel_times.json"
    input_path.write_text(
        json.dumps(
            {
                "priorities": {"must": 100},
                "cinemas": [
                    {"id": "a", "name": "Kino A", "lat": 52.1, "lon": 21.0},
                    {"id": "b", "name": "Kino B", "lat": 52.2, "lon": 21.1},
                ],
                "films": [],
                "screenings": [],
                "travel_times_file": "sample_travel_times.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_travel_times.py",
            str(input_path),
            str(output_path),
            "--provider",
            "static",
            "--static-minutes",
            "17",
        ],
    )

    main()

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["times"]["a"]["b"]["minutes"] == 17
    assert generated["times"]["b"]["a"]["minutes"] == 17
