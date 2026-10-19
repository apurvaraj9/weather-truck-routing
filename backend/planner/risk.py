"""Weather risk classification, exactly as specified in the assessment.

Risk table (per checkpoint):

    Condition | Low        | Moderate  | High      | Severe    | No Travel
    Wind      | <25 mph    | 25-34     | 35-44     | 45-54     | >=55 mph
    Rain      | <0.10 in/hr| 0.10-0.25 | 0.25-0.50 | 0.50-1.00 | >1.00
    Snow      | <0.5 in/hr | 0.5-1.0   | 1.0-2.0   | 2.0-3.0   | >3.0

Load rules:
    >=55 mph                  -> No Travel for any load
    45-54 mph + >30,000 lb    -> No Travel
    35-44 mph + >40,000 lb    -> Severe

Boundary interpretation (documented in README "Assumptions"):
* Each band's lower bound is inclusive, so a value exactly on a shared boundary
  goes to the higher band (wind 35.0 -> High, rain 0.25 -> High, snow 1.0 -> High).
* Wind bands are treated as continuous ranges: 34.9 mph is Moderate, 35.0 is High.
* "No Travel" for rain/snow is strictly greater than 1.00 / 3.0, as written,
  so rain of exactly 1.00 in/hr is Severe and snow of exactly 3.0 in/hr is Severe.
* Load thresholds are strict: 30,000 lb exactly does not trigger the 30,000 lb rule.

The overall checkpoint risk is the worst (highest) of the wind (after load rules),
rain and snow levels.
"""
from dataclasses import dataclass

LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = 0, 1, 2, 3, 4
LEVEL_NAMES = ["Low", "Moderate", "High", "Severe", "No Travel"]


def level_name(level: int) -> str:
    return LEVEL_NAMES[level]


def classify_wind(mph: float) -> int:
    if mph >= 55:
        return NO_TRAVEL
    if mph >= 45:
        return SEVERE
    if mph >= 35:
        return HIGH
    if mph >= 25:
        return MODERATE
    return LOW


def classify_rain(in_per_hr: float) -> int:
    if in_per_hr > 1.00:
        return NO_TRAVEL
    if in_per_hr >= 0.50:
        return SEVERE
    if in_per_hr >= 0.25:
        return HIGH
    if in_per_hr >= 0.10:
        return MODERATE
    return LOW


def classify_snow(in_per_hr: float) -> int:
    if in_per_hr > 3.0:
        return NO_TRAVEL
    if in_per_hr >= 2.0:
        return SEVERE
    if in_per_hr >= 1.0:
        return HIGH
    if in_per_hr >= 0.5:
        return MODERATE
    return LOW


def apply_load_rules(wind_mph: float, load_lb: float) -> tuple[int, str | None]:
    """Return (wind level after load rules, description of the load rule applied or None)."""
    base = classify_wind(wind_mph)
    if wind_mph >= 55:
        # Already No Travel from the table; the load rule says the same for any load.
        return NO_TRAVEL, None
    if 45 <= wind_mph < 55 and load_lb > 30_000:
        return NO_TRAVEL, "Wind 45-54 mph with load over 30,000 lb -> No Travel"
    if 35 <= wind_mph < 45 and load_lb > 40_000:
        return SEVERE, "Wind 35-44 mph with load over 40,000 lb -> Severe"
    return base, None


@dataclass(frozen=True)
class CheckpointRisk:
    wind_level: int
    rain_level: int
    snow_level: int
    level: int
    load_rule: str | None

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES[self.level]


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> CheckpointRisk:
    wind_level, load_rule = apply_load_rules(wind_mph, load_lb)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)
    return CheckpointRisk(
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        level=max(wind_level, rain_level, snow_level),
        load_rule=load_rule,
    )
