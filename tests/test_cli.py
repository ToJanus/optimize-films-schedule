import json

from film_schedule.cli import save_options
from film_schedule.optimizer import load_plan, optimize_schedule


def test_save_options_writes_aggregate_and_each_option_file(tmp_path) -> None:
    data = {
        "priorities": {"must": 100, "nice": 10},
        "cinemas": [{"id": "a", "name": "Kino A"}],
        "films": [
            {"id": "f1", "title": "Film 1", "duration_minutes": 60, "priority": "must"},
            {"id": "f2", "title": "Film 2", "duration_minutes": 60, "priority": "nice"},
        ],
        "screenings": [
            {"id": "s1", "film_id": "f1", "cinema_id": "a", "starts_at": "10:00"},
            {"id": "s2", "film_id": "f2", "cinema_id": "a", "starts_at": "12:00"},
        ],
    }
    films, cinemas, screenings, priorities, travel_times = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times)[:2]

    output_path = tmp_path / "results.json"
    records_dir = save_options(options, output_path, "json")

    aggregate = json.loads(output_path.read_text(encoding="utf-8"))
    record_paths = sorted(records_dir.glob("*.json"))
    assert len(aggregate) == len(options)
    assert len(record_paths) == len(options)
    assert json.loads(record_paths[0].read_text(encoding="utf-8"))["score"] == options[0].score
