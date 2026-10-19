"""Route summaries and the recommendation rule from the assessment.

Prefer, in order:
    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk
    4. Shortest travel time

Assumption (README): "No Travel" is worse than "Severe" but is not listed in the
preference order. A route with No Travel miles must never beat a route without
them, so "fewest No Travel miles" is applied before rule 1. When no route has
No Travel miles (the normal case) the ranking is exactly the PDF's four rules.

Miles at each level come from checkpoint coverage (each checkpoint represents the
stretch halfway to its neighbours). Average risk is the distance-weighted mean of
checkpoint levels on a 0-4 scale (Low=0, Moderate=1, High=2, Severe=3, No Travel=4).
"""
from dataclasses import dataclass, field

from .risk import HIGH, LEVEL_NAMES, NO_TRAVEL, SEVERE


@dataclass
class RouteSummary:
    route_id: str
    distance_miles: float
    duration_seconds: float
    miles_by_level: dict = field(default_factory=dict)  # level name -> miles
    average_risk: float = 0.0
    max_level: int = 0

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[LEVEL_NAMES[NO_TRAVEL]]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[LEVEL_NAMES[SEVERE]]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[LEVEL_NAMES[HIGH]]

    def sort_key(self):
        # Rounded so floating-point noise never decides a ranking.
        return (
            round(self.no_travel_miles, 1),
            round(self.severe_miles, 1),
            round(self.high_miles, 1),
            round(self.average_risk, 2),
            round(self.duration_seconds),
        )


def summarize(route_id: str, distance_miles: float, duration_seconds: float,
              checkpoint_levels: list[tuple[int, float]]) -> RouteSummary:
    """checkpoint_levels: list of (risk level, covered miles)."""
    miles = {name: 0.0 for name in LEVEL_NAMES}
    total = weighted = 0.0
    max_level = 0
    for level, covered in checkpoint_levels:
        miles[LEVEL_NAMES[level]] += covered
        total += covered
        weighted += level * covered
        max_level = max(max_level, level)
    avg = weighted / total if total > 0 else (checkpoint_levels[0][0] if checkpoint_levels else 0.0)
    return RouteSummary(
        route_id=route_id,
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        miles_by_level={k: round(v, 1) for k, v in miles.items()},
        average_risk=round(avg, 3),
        max_level=max_level,
    )


CRITERIA = [
    ("No Travel miles", lambda s: round(s.no_travel_miles, 1), "{:.1f} mi"),
    ("Severe miles", lambda s: round(s.severe_miles, 1), "{:.1f} mi"),
    ("High miles", lambda s: round(s.high_miles, 1), "{:.1f} mi"),
    ("average risk", lambda s: round(s.average_risk, 2), "{:.2f}"),
    ("travel time", lambda s: round(s.duration_seconds), None),
]


def _fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    return f"{minutes // 60}h {minutes % 60:02d}m"


def rank(summaries: list[RouteSummary]) -> tuple[list[RouteSummary], str]:
    """Return summaries best-first and a one-sentence explanation of the choice."""
    ordered = sorted(summaries, key=lambda s: s.sort_key())
    best = ordered[0]
    if len(ordered) == 1:
        return ordered, f"{best.route_id} is the only available route."
    runner = ordered[1]
    for label, getter, fmt in CRITERIA:
        if getter(best) != getter(runner):
            others = ", ".join(
                f"{s.route_id}: {(fmt.format(getter(s)) if fmt else _fmt_duration(s.duration_seconds))}"
                for s in ordered[1:]
            )
            mine = fmt.format(getter(best)) if fmt else _fmt_duration(best.duration_seconds)
            ties = [c[0] for c in CRITERIA[:CRITERIA.index((label, getter, fmt))]
                    if not (c[0] == "No Travel miles" and best.no_travel_miles == 0)]
            tie_text = f"Tied on {' and '.join(ties)}; " if ties else ""
            kind = "shortest" if label == "travel time" else ("lowest" if label == "average risk" else "fewest")
            return ordered, (f"{tie_text}{best.route_id} has the {kind} {label} "
                             f"({mine} vs {others}).")
    return ordered, f"All routes are tied on every rule; {best.route_id} is listed first by the routing service."
