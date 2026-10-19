"""Open-Meteo hourly forecast API (free, no API key).

Docs: https://open-meteo.com/en/docs

Why the BROWSER makes the Open-Meteo requests
---------------------------------------------
Open-Meteo's free tier is limited per IP address (600 calls/minute, 5,000/hour,
10,000/day). Free hosting platforms send all their apps' traffic from a few shared
IP addresses, so server-side calls are refused there because other apps have used up
the allowance. The server therefore only *describes* the request (``build_query``):
which points, which hours, which variables. The visitor's browser sends that exact
request to Open-Meteo, and posts the raw ``hourly`` blocks back. All interpretation
(unit conversion, picking the hour at each ETA, risk rules) stays here on the server.

Variables used (hourly):
* wind_speed_10m  - requested in mph (instantaneous value at the hour)
* rain + showers  - liquid precipitation in mm over the PRECEDING hour (converted to in/hr)
* snowfall        - snowfall in cm over the PRECEDING hour (converted to in/hr)

Locations are de-duplicated on a 0.05 degree grid (about 3.5 miles) to save calls.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import ProviderError

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = "wind_speed_10m,rain,showers,snowfall"
BATCH_SIZE = 100          # locations per browser request
SNAP_DEG = 0.05
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54
MAX_HOURS = 24 * 10       # sanity limit for posted data


@dataclass
class HourlySeries:
    start: int            # unix seconds of first hour (UTC, top of hour)
    wind_mph: list
    rain_in: list         # liquid precipitation (rain + showers) during the preceding hour
    snow_in: list         # snowfall during the preceding hour

    def _index(self, unix_seconds: float) -> int:
        return int(round((unix_seconds - self.start) / 3600))

    def _value(self, values: list, idx: int):
        if 0 <= idx < len(values) and values[idx] is not None:
            return values[idx]
        return None

    def at(self, unix_seconds: float) -> dict:
        """Weather the truck experiences at the given time.

        Wind: nearest hourly value. Precipitation: the hourly total for the hour that
        contains the time (Open-Meteo stamps precipitation at the END of its hour).
        """
        wind = self._value(self.wind_mph, self._index(unix_seconds))
        end_of_hour = math.floor(unix_seconds / 3600) * 3600 + 3600
        p_idx = int((end_of_hour - self.start) // 3600)
        rain = self._value(self.rain_in, p_idx)
        snow = self._value(self.snow_in, p_idx)
        missing = wind is None or rain is None or snow is None
        return {
            "wind_mph": round(wind or 0.0, 1),
            "rain_in_hr": round(rain or 0.0, 3),
            "snow_in_hr": round(snow or 0.0, 3),
            "missing": missing,
        }


def snap(lat: float, lon: float) -> tuple[float, float]:
    return (round(round(lat / SNAP_DEG) * SNAP_DEG, 4), round(round(lon / SNAP_DEG) * SNAP_DEG, 4))


def hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def build_query(points: list[tuple[float, float]], start: datetime, end: datetime) -> tuple[dict, list[int]]:
    """Describe the Open-Meteo request covering [start, end] for `points`.

    Returns (query, index) where query = {url, params, points, batch_size} for the
    browser, and index[i] is the position in query["points"] that serves points[i].
    """
    start_h = hour_floor(start)
    end_h = hour_floor(end) + timedelta(hours=1)
    unique: dict[tuple[float, float], int] = {}
    index = []
    for p in points:
        index.append(unique.setdefault(snap(*p), len(unique)))
    query = {
        "url": URL,
        "params": {
            "hourly": HOURLY_VARIABLES,
            "wind_speed_unit": "mph",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "start_hour": start_h.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end_h.strftime("%Y-%m-%dT%H:%M"),
        },
        "points": [list(p) for p in unique],
        "batch_size": BATCH_SIZE,
    }
    return query, index


def _number_list(value, name: str) -> list:
    if not isinstance(value, list) or len(value) > MAX_HOURS:
        raise ProviderError(f"Weather data field '{name}' is missing or too long.", status=400)
    for v in value:
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)):
            raise ProviderError(f"Weather data field '{name}' contains a non-numeric value.", status=400)
    return value


def parse_hourly(hourly) -> HourlySeries:
    """Parse one location's raw Open-Meteo ``hourly`` block (as posted by the browser)."""
    if not isinstance(hourly, dict):
        raise ProviderError("Weather data is not in Open-Meteo's format.", status=400)
    times = _number_list(hourly.get("time"), "time")
    if not times or any(t is None for t in times):
        raise ProviderError("Weather data has no hourly timestamps.", status=400)

    def series(name):
        values = _number_list(hourly.get(name, [None] * len(times)), name)
        if len(values) != len(times):
            raise ProviderError(f"Weather data field '{name}' has the wrong length.", status=400)
        return values

    rain, showers, snow_cm = series("rain"), series("showers"), series("snowfall")
    rain_in = [None if r is None and s is None else ((r or 0.0) + (s or 0.0)) / MM_PER_INCH
               for r, s in zip(rain, showers)]
    return HourlySeries(
        start=int(times[0]),
        wind_mph=list(series("wind_speed_10m")),
        rain_in=rain_in,
        snow_in=[None if v is None else v / CM_PER_INCH for v in snow_cm],
    )


def parse_many(weather, expected: int) -> list[HourlySeries]:
    if not isinstance(weather, list) or len(weather) != expected:
        raise ProviderError(f"Expected weather for {expected} locations.", status=400)
    return [parse_hourly(h) for h in weather]
