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

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, constraints, require_all_films=True, optimization_settings=settings)

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

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, constraints, optimization_settings=settings)

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

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, constraints, require_all_films=True, optimization_settings=settings)

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

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(
        films,
        cinemas,
        screenings,
        priorities,
        travel_times,
        constraints,
        earliest_start=9 * 60,
        latest_end=22 * 60,
    )

    assert options
    assert {item.screening.id for option in options for item in option.screenings} == {"middle"}


def test_required_films_are_preferred_over_priority_when_feasible() -> None:
    data = {
        "priorities": {"high": 100, "low": 1},
        "cinemas": [{"id": "a", "name": "Kino A"}],
        "films": [
            {"id": "important", "title": "Important", "duration_minutes": 60, "priority": "high"},
            {"id": "required", "title": "Required", "duration_minutes": 60, "priority": "low"},
        ],
        "screenings": [
            {"id": "important", "film_id": "important", "cinema_id": "a", "starts_at": "10:00"},
            {"id": "required", "film_id": "required", "cinema_id": "a", "starts_at": "10:30"},
        ],
        "constraints": {"required_films": ["required"]},
    }

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, constraints, optimization_settings=settings)

    assert [item.film.id for item in options[0].screenings] == ["required"]
    assert options[0].satisfied_required_films == ("required",)


def test_required_film_cinema_pair_and_start_end_locations_are_used() -> None:
    data = {
        "priorities": {"same": 1},
        "places": [{"id": "home", "name": "Dom", "address": "ul. Domowa 1"}],
        "cinemas": [
            {"id": "a", "name": "Kino A", "address": "ul. Kinowa 1"},
            {"id": "b", "name": "Kino B", "address": "ul. Filmowa 2"},
        ],
        "films": [{"id": "film", "title": "Film", "duration_minutes": 60, "priority": "same"}],
        "screenings": [
            {"id": "too-early", "film_id": "film", "cinema_id": "a", "starts_at": "00:05"},
            {"id": "wanted", "film_id": "film", "cinema_id": "b", "starts_at": "10:00"},
        ],
        "constraints": {
            "required_film_cinemas": [{"film_id": "film", "cinema_id": "b"}],
            "start_location_id": "home",
            "end_location_id": "home",
        },
        "travel_times": {
            "default_minutes": 0,
            "times": {"home": {"a": 30, "b": 20}, "b": {"home": 25}},
        },
    }

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(films, cinemas, screenings, priorities, travel_times, constraints, optimization_settings=settings)

    assert [item.screening.id for item in options[0].screenings] == ["wanted"]
    assert options[0].total_travel_minutes == 45
    assert options[0].screenings[0].cinema.address == "ul. Filmowa 2"


def test_external_profiled_travel_times_and_risk_sorting(tmp_path) -> None:
    travel_file = tmp_path / "travel_times.json"
    travel_file.write_text(
        '{"default_minutes": 99, "profiles": [{"id": "afternoon", "start": "15:00", "end": "19:00"}], '
        '"times": {"a": {"b": {"minutes": 10, "no_traffic_minutes": 10}}}, '
        '"profile_times": {"afternoon": {"a": {"b": {"minutes": 30, "no_traffic_minutes": 10, "traffic_delay_minutes": 20}}}}}',
        encoding="utf-8",
    )
    data = {
        "priorities": {"same": 1},
        "travel_times_file": str(travel_file),
        "optimization_settings": {"sort_by_risk": True},
        "cinemas": [{"id": "a", "name": "Kino A"}, {"id": "b", "name": "Kino B"}],
        "films": [
            {"id": "f1", "title": "First", "duration_minutes": 60, "priority": "same"},
            {"id": "f2", "title": "Second", "duration_minutes": 60, "priority": "same"},
        ],
        "screenings": [
            {"id": "s1", "film_id": "f1", "cinema_id": "a", "starts_at": "14:00"},
            {"id": "s2", "film_id": "f2", "cinema_id": "b", "starts_at": "15:40"},
        ],
    }

    films, cinemas, screenings, priorities, travel_times, constraints, settings, locations = load_plan(data)
    options = optimize_schedule(
        films, cinemas, screenings, priorities, travel_times, constraints, optimization_settings=settings, require_all_films=True
    )

    assert len(options) == 1
    assert options[0].total_travel_minutes == 30
    assert options[0].risk_score == 20
    assert options[0].risk_warnings
