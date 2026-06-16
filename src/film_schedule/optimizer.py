from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Film:
    """A film definition with a flexible, user-defined priority category."""

    id: str
    title: str
    duration_minutes: int
    priority: str


@dataclass(frozen=True)
class CinemaPlan:
    """Cinema-specific settings that affect screening feasibility."""

    id: str
    name: str
    ads_minutes: int = 0
    address: str | None = None


@dataclass(frozen=True)
class Place:
    """A named non-cinema location that can be used as schedule start or end."""

    id: str
    name: str
    address: str | None = None


@dataclass(frozen=True)
class RequiredFilmCinema:
    """A requirement to include a film in a specific cinema."""

    film_id: str
    cinema_id: str


@dataclass(frozen=True)
class ScheduleConstraints:
    """Optional constraints that should be satisfied before priority scoring."""

    required_film_ids: frozenset[str] = frozenset()
    required_film_cinemas: tuple[RequiredFilmCinema, ...] = ()
    start_location_id: str | None = None
    end_location_id: str | None = None


@dataclass(frozen=True)
class Screening:
    """A single movie screening in one cinema."""

    id: str
    film_id: str
    cinema_id: str
    starts_at: int
    margin_before_minutes: int = 0
    margin_after_minutes: int = 0


@dataclass(frozen=True)
class ScheduledScreening:
    """A screening enriched with computed timing information."""

    screening: Screening
    film: Film
    cinema: CinemaPlan
    movie_starts_at: int
    movie_ends_at: int
    blocked_from: int
    blocked_until: int


@dataclass(frozen=True)
class ScheduleOption:
    """One feasible ordered set of screenings."""

    screenings: tuple[ScheduledScreening, ...]
    score: int
    covered_priorities: tuple[str, ...]
    total_wait_minutes: int
    total_travel_minutes: int
    satisfied_required_films: tuple[str, ...] = ()
    satisfied_required_film_cinemas: tuple[RequiredFilmCinema, ...] = ()


@dataclass(frozen=True)
class TravelTimes:
    """Directed travel-time lookup between cinemas and other locations."""

    times: dict[tuple[str, str], int] = field(default_factory=dict)
    default_minutes: int = 0

    def between(self, from_location_id: str, to_location_id: str) -> int:
        if from_location_id == to_location_id:
            return 0
        return self.times.get((from_location_id, to_location_id), self.default_minutes)


def parse_clock(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M").time()
    return parsed.hour * 60 + parsed.minute


def format_clock(minutes: int) -> str:
    minutes = minutes % MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load_plan(
    data: dict[str, Any],
) -> tuple[dict[str, Film], dict[str, CinemaPlan], list[Screening], dict[str, int], TravelTimes, ScheduleConstraints]:
    priority_weights = {str(name): int(weight) for name, weight in data.get("priorities", {}).items()}
    if not priority_weights:
        raise ValueError("Input must define at least one priority in 'priorities'.")

    films = {
        str(item["id"]): Film(
            id=str(item["id"]),
            title=str(item["title"]),
            duration_minutes=int(item["duration_minutes"]),
            priority=str(item["priority"]),
        )
        for item in data.get("films", [])
    }
    unknown_priorities = {film.priority for film in films.values()} - set(priority_weights)
    if unknown_priorities:
        raise ValueError(f"Films use undefined priorities: {', '.join(sorted(unknown_priorities))}.")

    cinemas = {
        str(item["id"]): CinemaPlan(
            id=str(item["id"]),
            name=str(item.get("name", item["id"])),
            ads_minutes=int(item.get("ads_minutes", 0)),
            address=str(item["address"]) if item.get("address") is not None else None,
        )
        for item in data.get("cinemas", [])
    }

    defaults = data.get("defaults", {})
    default_before = int(defaults.get("margin_before_minutes", 0))
    default_after = int(defaults.get("margin_after_minutes", 0))
    screenings = [
        Screening(
            id=str(item["id"]),
            film_id=str(item["film_id"]),
            cinema_id=str(item["cinema_id"]),
            starts_at=parse_clock(str(item["starts_at"])),
            margin_before_minutes=int(item.get("margin_before_minutes", default_before)),
            margin_after_minutes=int(item.get("margin_after_minutes", default_after)),
        )
        for item in data.get("screenings", [])
    ]

    for screening in screenings:
        if screening.film_id not in films:
            raise ValueError(f"Screening '{screening.id}' references unknown film '{screening.film_id}'.")
        if screening.cinema_id not in cinemas:
            raise ValueError(f"Screening '{screening.id}' references unknown cinema '{screening.cinema_id}'.")

    places = {
        str(item["id"]): Place(
            id=str(item["id"]),
            name=str(item.get("name", item["id"])),
            address=str(item["address"]) if item.get("address") is not None else None,
        )
        for item in data.get("places", [])
    }
    location_ids = set(cinemas) | set(places)

    constraints_data = data.get("constraints", {})
    constraints = ScheduleConstraints(
        required_film_ids=frozenset(str(item) for item in constraints_data.get("required_films", [])),
        required_film_cinemas=tuple(
            RequiredFilmCinema(film_id=str(item["film_id"]), cinema_id=str(item["cinema_id"]))
            for item in constraints_data.get("required_film_cinemas", [])
        ),
        start_location_id=(
            str(constraints_data["start_location_id"])
            if constraints_data.get("start_location_id") is not None
            else None
        ),
        end_location_id=(
            str(constraints_data["end_location_id"]) if constraints_data.get("end_location_id") is not None else None
        ),
    )
    unknown_required_films = constraints.required_film_ids - set(films)
    if unknown_required_films:
        raise ValueError(f"Constraints require unknown films: {', '.join(sorted(unknown_required_films))}.")
    for requirement in constraints.required_film_cinemas:
        if requirement.film_id not in films:
            raise ValueError(f"Constraints require unknown film '{requirement.film_id}'.")
        if requirement.cinema_id not in cinemas:
            raise ValueError(f"Constraints require unknown cinema '{requirement.cinema_id}'.")
    for label, location_id in (
        ("start_location_id", constraints.start_location_id),
        ("end_location_id", constraints.end_location_id),
    ):
        if location_id is not None and location_id not in location_ids:
            raise ValueError(f"Constraints use unknown {label} '{location_id}'.")

    travel_data = data.get("travel_times", {})
    travel_times = TravelTimes(
        times={
            (str(from_id), str(to_id)): int(minutes)
            for from_id, destinations in travel_data.get("times", {}).items()
            for to_id, minutes in destinations.items()
        },
        default_minutes=int(travel_data.get("default_minutes", 0)),
    )
    return films, cinemas, screenings, priority_weights, travel_times, constraints


def optimize_schedule(
    films: dict[str, Film],
    cinemas: dict[str, CinemaPlan],
    screenings: list[Screening],
    priority_weights: dict[str, int],
    travel_times: TravelTimes,
    constraints: ScheduleConstraints | None = None,
    *,
    require_all_films: bool = False,
    earliest_start: int | None = None,
    latest_end: int | None = None,
) -> list[ScheduleOption]:
    """Return all feasible schedule variants sorted from best to worst."""

    constraints = constraints or ScheduleConstraints()
    enriched = sorted(
        (
            _enrich_screening(screening, films[screening.film_id], cinemas[screening.cinema_id])
            for screening in screenings
        ),
        key=lambda item: (item.blocked_from, item.movie_starts_at, item.film.title),
    )
    options: list[ScheduleOption] = []

    def visit(path: tuple[ScheduledScreening, ...], start_index: int) -> None:
        if path and _matches_end_location(path, constraints, travel_times):
            options.append(_build_option(path, priority_weights, travel_times, constraints))

        used_films = {item.film.id for item in path}
        last = path[-1] if path else None
        for index in range(start_index, len(enriched)):
            candidate = enriched[index]
            if candidate.film.id in used_films:
                continue
            if earliest_start is not None and candidate.movie_starts_at < earliest_start:
                continue
            if latest_end is not None and candidate.movie_ends_at > latest_end:
                continue
            if last and not _can_follow(last, candidate, travel_times):
                continue
            if not last and not _matches_start_location(candidate, constraints, travel_times):
                continue
            visit((*path, candidate), index + 1)

    visit((), 0)

    if require_all_films:
        required = set(films)
        options = [option for option in options if {item.film.id for item in option.screenings} == required]

    if constraints.required_film_ids or constraints.required_film_cinemas:
        best_satisfied_count = max((_satisfied_requirement_count(option) for option in options), default=0)
        options = [option for option in options if _satisfied_requirement_count(option) == best_satisfied_count]

    return sorted(
        options,
        key=lambda option: (
            -_satisfied_requirement_count(option),
            -option.score,
            -len(option.screenings),
            option.total_travel_minutes,
            option.total_wait_minutes,
            tuple(item.movie_starts_at for item in option.screenings),
        ),
    )


def _enrich_screening(screening: Screening, film: Film, cinema: CinemaPlan) -> ScheduledScreening:
    movie_starts_at = screening.starts_at + cinema.ads_minutes
    movie_ends_at = movie_starts_at + film.duration_minutes
    return ScheduledScreening(
        screening=screening,
        film=film,
        cinema=cinema,
        movie_starts_at=movie_starts_at,
        movie_ends_at=movie_ends_at,
        blocked_from=movie_starts_at - screening.margin_before_minutes,
        blocked_until=movie_ends_at + screening.margin_after_minutes,
    )


def _can_follow(previous: ScheduledScreening, current: ScheduledScreening, travel_times: TravelTimes) -> bool:
    return previous.blocked_until + travel_times.between(previous.cinema.id, current.cinema.id) <= current.blocked_from


def _matches_start_location(
    first: ScheduledScreening, constraints: ScheduleConstraints, travel_times: TravelTimes
) -> bool:
    if constraints.start_location_id is None:
        return True
    return travel_times.between(constraints.start_location_id, first.cinema.id) <= first.blocked_from


def _matches_end_location(path: tuple[ScheduledScreening, ...], constraints: ScheduleConstraints, travel_times: TravelTimes) -> bool:
    if constraints.end_location_id is None:
        return True
    last = path[-1]
    return last.blocked_until + travel_times.between(last.cinema.id, constraints.end_location_id) <= MINUTES_PER_DAY


def _build_option(
    path: tuple[ScheduledScreening, ...],
    priority_weights: dict[str, int],
    travel_times: TravelTimes,
    constraints: ScheduleConstraints,
) -> ScheduleOption:
    score = sum(priority_weights[item.film.priority] for item in path)
    covered_priorities = tuple(sorted({item.film.priority for item in path}, key=lambda item: -priority_weights[item]))
    total_travel = 0
    total_wait = 0
    if constraints.start_location_id is not None:
        total_travel += travel_times.between(constraints.start_location_id, path[0].cinema.id)
    if constraints.end_location_id is not None:
        total_travel += travel_times.between(path[-1].cinema.id, constraints.end_location_id)
    for previous, current in zip(path, path[1:]):
        travel = travel_times.between(previous.cinema.id, current.cinema.id)
        total_travel += travel
        total_wait += current.blocked_from - (previous.blocked_until + travel)
    seen_films = {item.film.id for item in path}
    satisfied_films = tuple(sorted(constraints.required_film_ids & seen_films))
    satisfied_pairs = tuple(
        requirement
        for requirement in constraints.required_film_cinemas
        if any(
            item.film.id == requirement.film_id and item.cinema.id == requirement.cinema_id
            for item in path
        )
    )
    return ScheduleOption(
        screenings=path,
        score=score,
        covered_priorities=covered_priorities,
        total_wait_minutes=total_wait,
        total_travel_minutes=total_travel,
        satisfied_required_films=satisfied_films,
        satisfied_required_film_cinemas=satisfied_pairs,
    )


def _satisfied_requirement_count(option: ScheduleOption) -> int:
    return len(option.satisfied_required_films) + len(option.satisfied_required_film_cinemas)


def option_to_dict(option: ScheduleOption) -> dict[str, Any]:
    return {
        "score": option.score,
        "films_count": len(option.screenings),
        "covered_priorities": list(option.covered_priorities),
        "total_wait_minutes": option.total_wait_minutes,
        "total_travel_minutes": option.total_travel_minutes,
        "satisfied_required_films": list(option.satisfied_required_films),
        "satisfied_required_film_cinemas": [
            {"film_id": item.film_id, "cinema_id": item.cinema_id}
            for item in option.satisfied_required_film_cinemas
        ],
        "plan": [
            {
                "film": item.film.title,
                "priority": item.film.priority,
                "cinema": item.cinema.name,
                "cinema_address": item.cinema.address,
                "advertised_start": format_clock(item.screening.starts_at),
                "movie_start_after_ads": format_clock(item.movie_starts_at),
                "movie_end": format_clock(item.movie_ends_at),
                "blocked_from": format_clock(item.blocked_from),
                "blocked_until": format_clock(item.blocked_until),
            }
            for item in option.screenings
        ],
    }


def option_to_text(option: ScheduleOption, ordinal: int) -> str:
    parts = [
        f"{item.film.title} o {format_clock(item.screening.starts_at)} ({item.cinema.name})"
        for item in option.screenings
    ]
    return (
        f"{ordinal}. "
        f"score={option.score}, filmy={len(option.screenings)}, "
        f"dojazdy={option.total_travel_minutes} min, czekanie={option.total_wait_minutes} min: "
        + "; ".join(parts)
    )
