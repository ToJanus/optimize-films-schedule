from film_schedule.optimizer import load_plan, optimize_schedule, option_to_text


def test_optimizer_finds_full_best_schedule_with_ads_travel_and_margins() -> None:
    data = {
        "priorities": {"must": 100, "nice": 10},
        "defaults": {"margin_before_minutes": 5, "margin_after_minutes": 5},
        "cinemas": [
            {"id": "a", "name": "Kino A", "ads_minutes": 10},
            {"id": "b", "name": "Kino B", "ads_minutes": 15},
        ],
        "films": [
            {"id": "f1", "title": "Film 1", "duration_minutes": 90, "priority": "must"},
            {"id": "f2", "title": "Film 2", "duration_minutes": 80, "priority": "nice"},
            {"id": "f3", "title": "Film 3", "duration_minutes": 100, "priority": "must"},
        ],
        "screenings": [
            {"id": "s1", "film_id": "f1", "cinema_id": "a", "starts_at": "10:00"},
            {"id": "s2", "film_id": "f2", "cinema_id": "b", "starts_at": "12:15"},
            {"id": "s3", "film_id": "f3", "cinema_id": "a", "starts_at": "15:00"},
            {"id": "s4", "film_id": "f2", "cinema_id": "b", "starts_at": "11:20"},
        ],
        "travel_times": {"times": {"a": {"b": 20}, "b": {"a": 20}}},
    }

    films, cinemas, screenings, priorities, travel_times = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, require_all_films=True)

    assert len(options) == 1
    assert [item.screening.id for item in options[0].screenings] == ["s1", "s2", "s3"]
    assert options[0].score == 210
    assert option_to_text(options[0], 1).startswith("1. score=210")


def test_optimizer_sorts_higher_priority_subset_before_longer_low_priority_plan() -> None:
    data = {
        "priorities": {"high": 100, "low": 1},
        "cinemas": [{"id": "a", "name": "Kino A"}],
        "films": [
            {"id": "important", "title": "Important", "duration_minutes": 90, "priority": "high"},
            {"id": "low1", "title": "Low 1", "duration_minutes": 40, "priority": "low"},
            {"id": "low2", "title": "Low 2", "duration_minutes": 40, "priority": "low"},
        ],
        "screenings": [
            {"id": "important", "film_id": "important", "cinema_id": "a", "starts_at": "10:00"},
            {"id": "low1", "film_id": "low1", "cinema_id": "a", "starts_at": "08:00"},
            {"id": "low2", "film_id": "low2", "cinema_id": "a", "starts_at": "09:00"},
        ],
    }

    films, cinemas, screenings, priorities, travel_times = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times)

    assert options[0].score == 102
    assert [item.film.id for item in options[0].screenings] == ["low1", "low2", "important"]
    assert any(option.score == 100 for option in options)


def test_margin_before_is_counted_from_movie_start_after_ads() -> None:
    data = {
        "priorities": {"same": 1},
        "cinemas": [{"id": "a", "name": "Kino A", "ads_minutes": 20}],
        "films": [
            {"id": "first", "title": "First", "duration_minutes": 30, "priority": "same"},
            {"id": "second", "title": "Second", "duration_minutes": 60, "priority": "same"},
        ],
        "screenings": [
            {"id": "first", "film_id": "first", "cinema_id": "a", "starts_at": "10:00"},
            {
                "id": "second",
                "film_id": "second",
                "cinema_id": "a",
                "starts_at": "10:35",
                "margin_before_minutes": 5,
            },
        ],
    }

    films, cinemas, screenings, priorities, travel_times = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, require_all_films=True)

    assert len(options) == 1
    assert [item.screening.id for item in options[0].screenings] == ["first", "second"]
    assert options[0].screenings[1].blocked_from == 10 * 60 + 50


def test_undefined_priority_is_reported() -> None:
    data = {
        "priorities": {"known": 1},
        "cinemas": [],
        "films": [{"id": "f", "title": "Film", "duration_minutes": 90, "priority": "unknown"}],
        "screenings": [],
    }

    try:
        load_plan(data)
    except ValueError as error:
        assert "undefined priorities" in str(error)
    else:
        raise AssertionError("Expected ValueError")


def test_optimizer_filters_by_earliest_start_and_latest_end() -> None:
    data = {
        "priorities": {"same": 1},
        "cinemas": [{"id": "a", "name": "Kino A"}],
        "films": [
            {"id": "early", "title": "Early", "duration_minutes": 50, "priority": "same"},
            {"id": "middle", "title": "Middle", "duration_minutes": 50, "priority": "same"},
            {"id": "late", "title": "Late", "duration_minutes": 90, "priority": "same"},
        ],
        "screenings": [
            {"id": "early", "film_id": "early", "cinema_id": "a", "starts_at": "08:00"},
            {"id": "middle", "film_id": "middle", "cinema_id": "a", "starts_at": "10:00"},
            {"id": "late", "film_id": "late", "cinema_id": "a", "starts_at": "21:00"},
        ],
    }

    films, cinemas, screenings, priorities, travel_times = load_plan(data)
    options = optimize_schedule(
        films,
        cinemas,
        screenings,
        priorities,
        travel_times,
        earliest_start=9 * 60,
        latest_end=22 * 60,
    )

    assert options
    assert {item.screening.id for option in options for item in option.screenings} == {"middle"}
