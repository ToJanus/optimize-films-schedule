from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

MINUTES_PER_DAY = 24 * 60
DEFAULT_TIME_PROFILES = (
    {"id": "morning", "start": "06:00", "end": "11:00"},
    {"id": "midday", "start": "11:00", "end": "15:00"},
    {"id": "afternoon", "start": "15:00", "end": "19:00"},
    {"id": "evening", "start": "19:00", "end": "23:00"},
    {"id": "night", "start": "23:00", "end": "06:00"},
)


@dataclass(frozen=True)
class Film:
    """A film definition with a flexible, user-defined priority category."""

    id: str
    title: str
    duration_minutes: int
    priority: str


@dataclass(frozen=True)
class Location:
    """A routable point shared by cinemas and custom places."""

    id: str
    name: str
    kind: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class CinemaPlan:
    """Cinema-specific settings that affect screening feasibility and optional ranking."""

    id: str
    name: str
    ads_minutes: int = 0
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    priority: int = 1


@dataclass(frozen=True)
class Place:
    """A named non-cinema location that can be used as schedule start or end."""

    id: str
    name: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class RequiredFilmCinema:
    """A requirement to include a film in a specific cinema."""

    film_id: str
    cinema_id: str


@dataclass(frozen=True)
class BreakWindow:
    """A planned break, optionally anchored to a cinema or custom place."""

    start_minutes: int
    end_minutes: int
    location_id: str | None = None


@dataclass(frozen=True)
class ScheduleConstraints:
    """Optional constraints that should be satisfied before priority scoring."""

    required_film_ids: frozenset[str] = frozenset()
    required_film_cinemas: tuple[RequiredFilmCinema, ...] = ()
    start_location_id: str | None = None
    end_location_id: str | None = None
    breaks: tuple[BreakWindow, ...] = ()


@dataclass(frozen=True)
class OptimizationSettings:
    """Optional knobs controlling travel profile selection and risk-aware ranking."""

    travel_time_profile: str | None = None
    sort_by_risk: bool = False
    risk_warning_threshold_minutes: int = 10
    risk_warning_threshold_ratio: float = 1.5
    use_cinema_priorities: bool = False


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
class RouteRisk:
    """Risk details for one transfer between two locations."""

    from_location_id: str
    to_location_id: str
    departure_minutes: int
    profile_id: str | None
    travel_minutes: int
    no_traffic_minutes: int | None = None
    traffic_delay_minutes: int = 0
    traffic_ratio: float = 1.0
    risk_score: float = 0.0
    warning: str | None = None


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
    risk_score: float = 0.0
    risk_warnings: tuple[str, ...] = ()
    route_risks: tuple[RouteRisk, ...] = ()


@dataclass(frozen=True)
class TravelTimeProfile:
    """A named time-of-day bucket used for profile-aware routing."""

    id: str
    start_minutes: int
    end_minutes: int

    def contains(self, minutes: int) -> bool:
        minutes = minutes % MINUTES_PER_DAY
        if self.start_minutes <= self.end_minutes:
            return self.start_minutes <= minutes < self.end_minutes
        return minutes >= self.start_minutes or minutes < self.end_minutes


@dataclass(frozen=True)
class TravelTimeEntry:
    """Stored travel details for one directed relation and optional profile."""

    minutes: int
    distance_meters: int | None = None
    no_traffic_minutes: int | None = None
    historic_traffic_minutes: int | None = None
    live_traffic_minutes: int | None = None
    traffic_delay_minutes: int = 0
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class TravelTimes:
    """Directed travel-time lookup between cinemas and other locations."""

    times: dict[tuple[str, str], TravelTimeEntry] = field(default_factory=dict)
    profile_times: dict[str, dict[tuple[str, str], TravelTimeEntry]] = field(
        default_factory=dict
    )
    profiles: tuple[TravelTimeProfile, ...] = ()
    default_minutes: int = 0

    def between(
        self,
        from_location_id: str,
        to_location_id: str,
        departure_minutes: int | None = None,
    ) -> int:
        return self.entry_between(
            from_location_id, to_location_id, departure_minutes
        ).minutes

    def entry_between(
        self,
        from_location_id: str,
        to_location_id: str,
        departure_minutes: int | None = None,
    ) -> TravelTimeEntry:
        if from_location_id == to_location_id:
            return TravelTimeEntry(minutes=0, no_traffic_minutes=0)
        profile_id = self.profile_for(departure_minutes)
        if profile_id is not None:
            entry = self.profile_times.get(profile_id, {}).get(
                (from_location_id, to_location_id)
            )
            if entry is not None:
                return entry
        entry = self.times.get((from_location_id, to_location_id))
        if entry is not None:
            return entry
        return TravelTimeEntry(minutes=self.default_minutes)

    def profile_for(self, departure_minutes: int | None) -> str | None:
        if departure_minutes is None:
            return None
        for profile in self.profiles:
            if profile.contains(departure_minutes):
                return profile.id
        return None


def parse_clock(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M").time()
    return parsed.hour * 60 + parsed.minute


def format_clock(minutes: int) -> str:
    minutes = minutes % MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load_json_file(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_plan(data: dict[str, Any], base_path: Path | None = None) -> tuple[
    dict[str, Film],
    dict[str, CinemaPlan],
    list[Screening],
    dict[str, int],
    TravelTimes,
    ScheduleConstraints,
    OptimizationSettings,
    dict[str, Location],
]:
    priority_weights = {
        str(name): int(weight) for name, weight in data.get("priorities", {}).items()
    }
    if not priority_weights:
        raise ValueError("Input must define at least one priority in 'priorities'.")

    raw_films = data.get("films", [])
    unknown_priorities = {str(item["priority"]) for item in raw_films} - set(
        priority_weights
    )
    if unknown_priorities:
        raise ValueError(
            f"Films use undefined priorities: {', '.join(sorted(unknown_priorities))}."
        )

    film_items = sorted(
        raw_films,
        key=lambda item: (
            -priority_weights[str(item["priority"])],
            str(item["title"]).casefold(),
        ),
    )
    films = {
        str(item["id"]): Film(
            id=str(item["id"]),
            title=str(item["title"]),
            duration_minutes=int(item["duration_minutes"]),
            priority=str(item["priority"]),
        )
        for item in film_items
    }
    cinemas = {
        str(item["id"]): CinemaPlan(
            id=str(item["id"]),
            name=str(item.get("name", item["id"])),
            ads_minutes=int(item.get("ads_minutes", 0)),
            address=str(item["address"]) if item.get("address") is not None else None,
            lat=_optional_float(item.get("lat")),
            lon=_optional_float(item.get("lon")),
            priority=int(item.get("priority", 1)),
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
            margin_before_minutes=int(
                item.get("margin_before_minutes", default_before)
            ),
            margin_after_minutes=int(item.get("margin_after_minutes", default_after)),
        )
        for item in data.get("screenings", [])
    ]

    for screening in screenings:
        if screening.film_id not in films:
            raise ValueError(
                f"Screening '{screening.id}' references unknown film '{screening.film_id}'."
            )
        if screening.cinema_id not in cinemas:
            raise ValueError(
                f"Screening '{screening.id}' references unknown cinema '{screening.cinema_id}'."
            )

    places = {
        str(item["id"]): Place(
            id=str(item["id"]),
            name=str(item.get("name", item["id"])),
            address=str(item["address"]) if item.get("address") is not None else None,
            lat=_optional_float(item.get("lat")),
            lon=_optional_float(item.get("lon")),
        )
        for item in data.get("places", [])
    }
    locations = build_locations(cinemas, places)

    constraints_data = data.get("constraints", {})
    constraints = ScheduleConstraints(
        required_film_ids=frozenset(
            str(item) for item in constraints_data.get("required_films", [])
        ),
        required_film_cinemas=tuple(
            RequiredFilmCinema(
                film_id=str(item["film_id"]), cinema_id=str(item["cinema_id"])
            )
            for item in constraints_data.get("required_film_cinemas", [])
        ),
        start_location_id=(
            str(constraints_data["start_location_id"])
            if constraints_data.get("start_location_id") is not None
            else None
        ),
        end_location_id=(
            str(constraints_data["end_location_id"])
            if constraints_data.get("end_location_id") is not None
            else None
        ),
        breaks=tuple(
            _parse_break_window(item) for item in constraints_data.get("breaks", [])
        ),
    )
    _validate_constraints(constraints, films, cinemas, set(locations))

    optimization_settings = _load_optimization_settings(
        data.get("optimization_settings", {})
    )
    travel_data = _load_travel_data(data, base_path)
    travel_times = load_travel_times(
        travel_data, optimization_settings.travel_time_profile
    )
    return (
        films,
        cinemas,
        screenings,
        priority_weights,
        travel_times,
        constraints,
        optimization_settings,
        locations,
    )


def build_locations(
    cinemas: dict[str, CinemaPlan], places: dict[str, Place]
) -> dict[str, Location]:
    locations = {
        item.id: Location(
            item.id, item.name, "cinema", item.address, item.lat, item.lon
        )
        for item in cinemas.values()
    }
    locations.update(
        {
            item.id: Location(
                item.id, item.name, "place", item.address, item.lat, item.lon
            )
            for item in places.values()
        }
    )
    return locations


def load_travel_times(
    travel_data: dict[str, Any], forced_profile_id: str | None = None
) -> TravelTimes:
    profiles = tuple(
        TravelTimeProfile(
            id=str(item["id"]),
            start_minutes=parse_clock(str(item["start"])),
            end_minutes=parse_clock(str(item["end"])),
        )
        for item in travel_data.get("profiles", [])
    )
    if forced_profile_id:
        profiles = (TravelTimeProfile(forced_profile_id, 0, MINUTES_PER_DAY),)
    return TravelTimes(
        times=_parse_times_map(travel_data.get("times", {})),
        profile_times={
            str(profile): _parse_times_map(times)
            for profile, times in travel_data.get("profile_times", {}).items()
        },
        profiles=profiles,
        default_minutes=int(travel_data.get("default_minutes", 0)),
    )


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
    time_bounds_apply_to_locations: bool = False,
    optimization_settings: OptimizationSettings | None = None,
) -> list[ScheduleOption]:
    """Return all feasible schedule variants sorted from best to worst."""

    constraints = constraints or ScheduleConstraints()
    optimization_settings = optimization_settings or OptimizationSettings()
    enriched = sorted(
        (
            _enrich_screening(
                screening, films[screening.film_id], cinemas[screening.cinema_id]
            )
            for screening in screenings
        ),
        key=lambda item: (item.blocked_from, item.movie_starts_at, item.film.title),
    )
    options: list[ScheduleOption] = []

    def visit(path: tuple[ScheduledScreening, ...], start_index: int) -> None:
        if (
            path
            and _matches_end_location(path, constraints, travel_times)
            and _path_satisfies_breaks(path, constraints, travel_times)
        ):
            options.append(
                _build_option(
                    path,
                    priority_weights,
                    travel_times,
                    constraints,
                    optimization_settings,
                )
            )

        used_films = {item.film.id for item in path}
        last = path[-1] if path else None
        for index in range(start_index, len(enriched)):
            candidate = enriched[index]
            if candidate.film.id in used_films:
                continue
            if earliest_start is not None and not _matches_earliest_start(
                candidate,
                constraints,
                travel_times,
                earliest_start,
                time_bounds_apply_to_locations,
            ):
                continue
            if latest_end is not None and not _matches_latest_end(
                candidate,
                constraints,
                travel_times,
                latest_end,
                time_bounds_apply_to_locations,
            ):
                continue
            if _screening_overlaps_break(candidate, constraints):
                continue
            if last and not _can_follow(last, candidate, travel_times, constraints):
                continue
            if not last and not _matches_start_location(
                candidate, constraints, travel_times
            ):
                continue
            visit((*path, candidate), index + 1)

    visit((), 0)

    if require_all_films:
        required = set(films)
        options = [
            option
            for option in options
            if {item.film.id for item in option.screenings} == required
        ]

    if constraints.required_film_ids or constraints.required_film_cinemas:
        best_satisfied_count = max(
            (_satisfied_requirement_count(option) for option in options), default=0
        )
        options = [
            option
            for option in options
            if _satisfied_requirement_count(option) == best_satisfied_count
        ]

    return sorted(options, key=lambda option: _sort_key(option, optimization_settings))


def _path_satisfies_breaks(
    path: tuple[ScheduledScreening, ...],
    constraints: ScheduleConstraints,
    travel_times: TravelTimes,
) -> bool:
    for item in constraints.breaks:
        if any(
            screening.movie_starts_at < item.end_minutes
            and screening.movie_ends_at > item.start_minutes
            for screening in path
        ):
            return False
        if item.location_id is None:
            continue

        previous = next(
            (
                screening
                for screening in reversed(path)
                if screening.movie_ends_at <= item.start_minutes
            ),
            None,
        )
        current = next(
            (
                screening
                for screening in path
                if screening.blocked_from >= item.end_minutes
            ),
            None,
        )
        if previous is not None:
            if (
                previous.blocked_until
                + travel_times.between(
                    previous.cinema.id, item.location_id, previous.blocked_until
                )
                > item.start_minutes
            ):
                return False
        elif constraints.start_location_id is not None:
            if (
                travel_times.between(constraints.start_location_id, item.location_id, 0)
                > item.start_minutes
            ):
                return False
        if current is not None:
            if (
                item.end_minutes
                + travel_times.between(
                    item.location_id, current.cinema.id, item.end_minutes
                )
                > current.blocked_from
            ):
                return False
        elif constraints.end_location_id is not None:
            if (
                item.end_minutes
                + travel_times.between(
                    item.location_id, constraints.end_location_id, item.end_minutes
                )
                > MINUTES_PER_DAY
            ):
                return False
    return True


def _enrich_screening(
    screening: Screening, film: Film, cinema: CinemaPlan
) -> ScheduledScreening:
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


def _can_follow(
    previous: ScheduledScreening,
    current: ScheduledScreening,
    travel_times: TravelTimes,
    constraints: ScheduleConstraints,
) -> bool:
    return (
        _earliest_arrival_after_breaks(previous, current, travel_times, constraints)
        <= current.blocked_from
    )


def _screening_overlaps_break(
    screening: ScheduledScreening, constraints: ScheduleConstraints
) -> bool:
    return any(
        screening.movie_starts_at < item.end_minutes
        and screening.movie_ends_at > item.start_minutes
        for item in constraints.breaks
    )


def _earliest_arrival_after_breaks(
    previous: ScheduledScreening,
    current: ScheduledScreening,
    travel_times: TravelTimes,
    constraints: ScheduleConstraints,
) -> int:
    departure = previous.blocked_until
    arrival = departure + travel_times.between(
        previous.cinema.id, current.cinema.id, departure
    )
    for item in constraints.breaks:
        if not (
            previous.movie_ends_at <= item.start_minutes
            and item.end_minutes <= current.blocked_from
        ):
            continue
        if item.location_id is None:
            departure = max(departure, item.end_minutes)
            arrival = departure + travel_times.between(
                previous.cinema.id, current.cinema.id, departure
            )
            continue
        if (
            previous.blocked_until
            + travel_times.between(
                previous.cinema.id, item.location_id, previous.blocked_until
            )
            <= item.start_minutes
        ):
            arrival = item.end_minutes + travel_times.between(
                item.location_id, current.cinema.id, item.end_minutes
            )
    return arrival


def _matches_earliest_start(
    first: ScheduledScreening,
    constraints: ScheduleConstraints,
    travel_times: TravelTimes,
    earliest_start: int,
    applies_to_locations: bool,
) -> bool:
    if not applies_to_locations:
        return first.movie_starts_at >= earliest_start
    if constraints.start_location_id is None:
        return first.blocked_from >= earliest_start
    return (
        earliest_start
        + travel_times.between(
            constraints.start_location_id, first.cinema.id, earliest_start
        )
        <= first.blocked_from
    )


def _matches_latest_end(
    last: ScheduledScreening,
    constraints: ScheduleConstraints,
    travel_times: TravelTimes,
    latest_end: int,
    applies_to_locations: bool,
) -> bool:
    if not applies_to_locations:
        return last.movie_ends_at <= latest_end
    if constraints.end_location_id is None:
        return last.blocked_until <= latest_end
    return (
        last.blocked_until
        + travel_times.between(
            last.cinema.id, constraints.end_location_id, last.blocked_until
        )
        <= latest_end
    )


def _matches_start_location(
    first: ScheduledScreening,
    constraints: ScheduleConstraints,
    travel_times: TravelTimes,
) -> bool:
    if constraints.start_location_id is None:
        return True
    return (
        travel_times.between(constraints.start_location_id, first.cinema.id, 0)
        <= first.blocked_from
    )


def _matches_end_location(
    path: tuple[ScheduledScreening, ...],
    constraints: ScheduleConstraints,
    travel_times: TravelTimes,
) -> bool:
    if constraints.end_location_id is None:
        return True
    last = path[-1]
    return (
        last.blocked_until
        + travel_times.between(
            last.cinema.id, constraints.end_location_id, last.blocked_until
        )
        <= MINUTES_PER_DAY
    )


def _build_option(
    path: tuple[ScheduledScreening, ...],
    priority_weights: dict[str, int],
    travel_times: TravelTimes,
    constraints: ScheduleConstraints,
    settings: OptimizationSettings,
) -> ScheduleOption:
    score = sum(priority_weights[item.film.priority] for item in path)
    if settings.use_cinema_priorities:
        score += sum(item.cinema.priority for item in path)
    covered_priorities = tuple(
        sorted(
            {item.film.priority for item in path},
            key=lambda item: -priority_weights[item],
        )
    )
    total_travel = 0
    total_wait = 0
    route_risks: list[RouteRisk] = []
    if constraints.start_location_id is not None:
        risk = _route_risk(
            constraints.start_location_id, path[0].cinema.id, 0, travel_times, settings
        )
        total_travel += risk.travel_minutes
        route_risks.append(risk)
    if constraints.end_location_id is not None:
        risk = _route_risk(
            path[-1].cinema.id,
            constraints.end_location_id,
            path[-1].blocked_until,
            travel_times,
            settings,
        )
        total_travel += risk.travel_minutes
        route_risks.append(risk)
    for previous, current in zip(path, path[1:]):
        risk = _route_risk(
            previous.cinema.id,
            current.cinema.id,
            previous.blocked_until,
            travel_times,
            settings,
        )
        total_travel += risk.travel_minutes
        total_wait += current.blocked_from - (
            previous.blocked_until + risk.travel_minutes
        )
        route_risks.append(risk)
    seen_films = {item.film.id for item in path}
    satisfied_films = tuple(sorted(constraints.required_film_ids & seen_films))
    satisfied_pairs = tuple(
        requirement
        for requirement in constraints.required_film_cinemas
        if any(
            item.film.id == requirement.film_id
            and item.cinema.id == requirement.cinema_id
            for item in path
        )
    )
    risk_warnings = tuple(risk.warning for risk in route_risks if risk.warning)
    return ScheduleOption(
        screenings=path,
        score=score,
        covered_priorities=covered_priorities,
        total_wait_minutes=total_wait,
        total_travel_minutes=total_travel,
        satisfied_required_films=satisfied_films,
        satisfied_required_film_cinemas=satisfied_pairs,
        risk_score=round(sum(risk.risk_score for risk in route_risks), 2),
        risk_warnings=risk_warnings,
        route_risks=tuple(route_risks),
    )


def _route_risk(
    from_location_id: str,
    to_location_id: str,
    departure_minutes: int,
    travel_times: TravelTimes,
    settings: OptimizationSettings,
) -> RouteRisk:
    entry = travel_times.entry_between(
        from_location_id, to_location_id, departure_minutes
    )
    profile_id = travel_times.profile_for(departure_minutes)
    no_traffic = entry.no_traffic_minutes
    traffic_delay = entry.traffic_delay_minutes
    if no_traffic is not None and traffic_delay == 0:
        traffic_delay = max(0, entry.minutes - no_traffic)
    ratio = round(entry.minutes / no_traffic, 2) if no_traffic else 1.0
    risk_score = max(float(traffic_delay), max(0.0, ratio - 1.0) * 10)
    warning = None
    if traffic_delay >= settings.risk_warning_threshold_minutes:
        warning = f"{from_location_id}->{to_location_id}: opóźnienie przez ruch {traffic_delay} min"
    elif ratio >= settings.risk_warning_threshold_ratio:
        warning = f"{from_location_id}->{to_location_id}: czas przejazdu {ratio:.2f}x bez korków"
    return RouteRisk(
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        departure_minutes=departure_minutes,
        profile_id=profile_id,
        travel_minutes=entry.minutes,
        no_traffic_minutes=no_traffic,
        traffic_delay_minutes=traffic_delay,
        traffic_ratio=ratio,
        risk_score=round(risk_score, 2),
        warning=warning,
    )


def _satisfied_requirement_count(option: ScheduleOption) -> int:
    return len(option.satisfied_required_films) + len(
        option.satisfied_required_film_cinemas
    )


def _sort_key(
    option: ScheduleOption, settings: OptimizationSettings
) -> tuple[Any, ...]:
    common = (
        -_satisfied_requirement_count(option),
        -option.score,
        -len(option.screenings),
    )
    risk = (option.risk_score,) if settings.sort_by_risk else ()
    return (
        common
        + risk
        + (
            option.total_travel_minutes,
            option.total_wait_minutes,
            tuple(item.movie_starts_at for item in option.screenings),
        )
    )


def option_to_dict(option: ScheduleOption) -> dict[str, Any]:
    return {
        "score": option.score,
        "films_count": len(option.screenings),
        "covered_priorities": list(option.covered_priorities),
        "total_wait_minutes": option.total_wait_minutes,
        "total_travel_minutes": option.total_travel_minutes,
        "risk_score": option.risk_score,
        "risk_warnings": list(option.risk_warnings),
        "satisfied_required_films": list(option.satisfied_required_films),
        "satisfied_required_film_cinemas": [
            {"film_id": item.film_id, "cinema_id": item.cinema_id}
            for item in option.satisfied_required_film_cinemas
        ],
        "routes": [
            {
                "from_location_id": item.from_location_id,
                "to_location_id": item.to_location_id,
                "departure": format_clock(item.departure_minutes),
                "profile_id": item.profile_id,
                "travel_minutes": item.travel_minutes,
                "no_traffic_minutes": item.no_traffic_minutes,
                "traffic_delay_minutes": item.traffic_delay_minutes,
                "traffic_ratio": item.traffic_ratio,
                "risk_score": item.risk_score,
                "warning": item.warning,
            }
            for item in option.route_risks
        ],
        "plan": [
            {
                "film": item.film.title,
                "priority": item.film.priority,
                "cinema": item.cinema.name,
                "cinema_address": item.cinema.address,
                "cinema_lat": item.cinema.lat,
                "cinema_lon": item.cinema.lon,
                "cinema_priority": item.cinema.priority,
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
    risk = f", ryzyko={option.risk_score:g}" if option.risk_score else ""
    warnings = (
        f", ostrzeżenia={len(option.risk_warnings)}" if option.risk_warnings else ""
    )
    return (
        f"{ordinal}. "
        f"score={option.score}, filmy={len(option.screenings)}, "
        f"dojazdy={option.total_travel_minutes} min, czekanie={option.total_wait_minutes} min{risk}{warnings}: "
        + "; ".join(parts)
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _load_optimization_settings(data: dict[str, Any]) -> OptimizationSettings:
    risk_data = data.get("risk", {})
    return OptimizationSettings(
        travel_time_profile=(
            str(data["travel_time_profile"])
            if data.get("travel_time_profile")
            else None
        ),
        sort_by_risk=bool(data.get("sort_by_risk", False)),
        risk_warning_threshold_minutes=int(
            risk_data.get("warning_threshold_minutes", 10)
        ),
        risk_warning_threshold_ratio=float(
            risk_data.get("warning_threshold_ratio", 1.5)
        ),
        use_cinema_priorities=bool(data.get("use_cinema_priorities", False)),
    )


def _load_travel_data(data: dict[str, Any], base_path: Path | None) -> dict[str, Any]:
    if data.get("travel_times_file"):
        path = Path(str(data["travel_times_file"]))
        if not path.is_absolute() and base_path is not None:
            path = base_path / path
        travel_data = load_json_file(path)
        inline = data.get("travel_times", {})
        if inline:
            merged = {**travel_data, **inline}
            if "times" in travel_data or "times" in inline:
                merged["times"] = {
                    **travel_data.get("times", {}),
                    **inline.get("times", {}),
                }
            if "profile_times" in travel_data or "profile_times" in inline:
                merged["profile_times"] = {
                    **travel_data.get("profile_times", {}),
                    **inline.get("profile_times", {}),
                }
            return merged
        return travel_data
    return data.get("travel_times", {})


def _parse_times_map(data: dict[str, Any]) -> dict[tuple[str, str], TravelTimeEntry]:
    parsed = {}
    for from_id, destinations in data.items():
        for to_id, value in destinations.items():
            parsed[(str(from_id), str(to_id))] = _parse_entry(value)
    return parsed


def _parse_entry(value: Any) -> TravelTimeEntry:
    if isinstance(value, dict):
        minutes = int(value.get("minutes", value.get("travel_time_minutes", 0)))
        no_traffic = value.get("no_traffic_minutes")
        historic = value.get("historic_traffic_minutes")
        live = value.get("live_traffic_minutes")
        delay = value.get("traffic_delay_minutes")
        if delay is None and no_traffic is not None:
            delay = max(0, minutes - int(no_traffic))
        return TravelTimeEntry(
            minutes=minutes,
            distance_meters=(
                int(value["distance_meters"])
                if value.get("distance_meters") is not None
                else None
            ),
            no_traffic_minutes=int(no_traffic) if no_traffic is not None else None,
            historic_traffic_minutes=int(historic) if historic is not None else None,
            live_traffic_minutes=int(live) if live is not None else None,
            traffic_delay_minutes=int(delay or 0),
            raw=value.get("raw"),
        )
    return TravelTimeEntry(minutes=int(value))


def _validate_constraints(
    constraints: ScheduleConstraints,
    films: dict[str, Film],
    cinemas: dict[str, CinemaPlan],
    location_ids: set[str],
) -> None:
    unknown_required_films = constraints.required_film_ids - set(films)
    if unknown_required_films:
        raise ValueError(
            f"Constraints require unknown films: {', '.join(sorted(unknown_required_films))}."
        )
    for requirement in constraints.required_film_cinemas:
        if requirement.film_id not in films:
            raise ValueError(
                f"Constraints require unknown film '{requirement.film_id}'."
            )
        if requirement.cinema_id not in cinemas:
            raise ValueError(
                f"Constraints require unknown cinema '{requirement.cinema_id}'."
            )
    for item in constraints.breaks:
        if item.start_minutes > item.end_minutes:
            raise ValueError("Break start cannot be later than break end.")
        if item.location_id is not None and item.location_id not in location_ids:
            raise ValueError(
                f"Constraints use unknown break location_id '{item.location_id}'."
            )
    for label, location_id in (
        ("start_location_id", constraints.start_location_id),
        ("end_location_id", constraints.end_location_id),
    ):
        if location_id is not None and location_id not in location_ids:
            raise ValueError(f"Constraints use unknown {label} '{location_id}'.")


def _parse_break_window(item: Any) -> BreakWindow:
    if isinstance(item, str):
        start, end = item.split(";", 1)
        return BreakWindow(parse_clock(start.strip()), parse_clock(end.strip()))
    return BreakWindow(
        start_minutes=parse_clock(str(item.get("from", item.get("start")))),
        end_minutes=parse_clock(str(item.get("to", item.get("end")))),
        location_id=(
            str(item["location_id"]) if item.get("location_id") is not None else None
        ),
    )
