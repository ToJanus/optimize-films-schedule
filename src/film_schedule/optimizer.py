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


@dataclass(frozen=True)
class TravelTimes:
    """Directed travel-time lookup between cinemas."""

    times: dict[tuple[str, str], int] = field(default_factory=dict)
    default_minutes: int = 0

    def between(self, from_cinema_id: str, to_cinema_id: str) -> int:
        if from_cinema_id == to_cinema_id:
            return 0
        return self.times.get((from_cinema_id, to_cinema_id), self.default_minutes)


def parse_clock(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M").time()
    return parsed.hour * 60 + parsed.minute


def format_clock(minutes: int) -> str:
    minutes = minutes % MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load_plan(data: dict[str, Any]) -> tuple[dict[str, Film], dict[str, CinemaPlan], list[Screening], dict[str, int], TravelTimes]:
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

    travel_data = data.get("travel_times", {})
    travel_times = TravelTimes(
        times={
            (str(from_id), str(to_id)): int(minutes)
            for from_id, destinations in travel_data.get("times", {}).items()
            for to_id, minutes in destinations.items()
        },
        default_minutes=int(travel_data.get("default_minutes", 0)),
    )
    return films, cinemas, screenings, priority_weights, travel_times


def optimize_schedule(
    films: dict[str, Film],
    cinemas: dict[str, CinemaPlan],
    screenings: list[Screening],
    priority_weights: dict[str, int],
    travel_times: TravelTimes,
    *,
    require_all_films: bool = False,
) -> list[ScheduleOption]:
    """Return all feasible schedule variants sorted from best to worst."""

    enriched = sorted(
        (
            _enrich_screening(screening, films[screening.film_id], cinemas[screening.cinema_id])
            for screening in screenings
        ),
        key=lambda item: (item.blocked_from, item.movie_starts_at, item.film.title),
    )
    options: list[ScheduleOption] = []

    def visit(path: tuple[ScheduledScreening, ...], start_index: int) -> None:
        if path:
            options.append(_build_option(path, priority_weights, travel_times))

        used_films = {item.film.id for item in path}
        last = path[-1] if path else None
        for index in range(start_index, len(enriched)):
            candidate = enriched[index]
            if candidate.film.id in used_films:
                continue
            if last and not _can_follow(last, candidate, travel_times):
                continue
            visit((*path, candidate), index + 1)

    visit((), 0)

    if require_all_films:
        required = set(films)
        options = [option for option in options if {item.film.id for item in option.screenings} == required]

    return sorted(
        options,
        key=lambda option: (
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


def _build_option(
    path: tuple[ScheduledScreening, ...], priority_weights: dict[str, int], travel_times: TravelTimes
) -> ScheduleOption:
    score = sum(priority_weights[item.film.priority] for item in path)
    covered_priorities = tuple(sorted({item.film.priority for item in path}, key=lambda item: -priority_weights[item]))
    total_travel = 0
    total_wait = 0
    for previous, current in zip(path, path[1:]):
        travel = travel_times.between(previous.cinema.id, current.cinema.id)
        total_travel += travel
        total_wait += current.blocked_from - (previous.blocked_until + travel)
    return ScheduleOption(
        screenings=path,
        score=score,
        covered_priorities=covered_priorities,
        total_wait_minutes=total_wait,
        total_travel_minutes=total_travel,
    )


def option_to_dict(option: ScheduleOption) -> dict[str, Any]:
    return {
        "score": option.score,
        "films_count": len(option.screenings),
        "covered_priorities": list(option.covered_priorities),
        "total_wait_minutes": option.total_wait_minutes,
        "total_travel_minutes": option.total_travel_minutes,
        "plan": [
            {
                "film": item.film.title,
                "priority": item.film.priority,
                "cinema": item.cinema.name,
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
