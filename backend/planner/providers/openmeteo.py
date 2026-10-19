"""Open-Meteo hourly forecast API (free, no API key).

Docs: https://open-meteo.com/en/docs

Variables used (hourly):
* wind_speed_10m  - requested in mph (instantaneous value at the hour)
* rain + showers  - liquid precipitation in mm over the PRECEDING hour (converted to in/hr)
* snowfall        - snowfall in cm over the PRECEDING hour (converted to in/hr)

Many locations are requested in one call (comma-separated lists). Open-Meteo counts
each location as one call against its free limits (600/min, 5,000/hour, 10,000/day),
so locations are de-duplicated on a 0.05 degree grid and results are cached briefly.
"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from . import ProviderError

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 100
SNAP_DEG = 0.05
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54


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


def _hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _parse_location(item: dict) -> HourlySeries:
    hourly = item.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise ProviderError("Open-Meteo returned no hourly data.")

    def series(name):
        return hourly.get(name) or [None] * len(times)

    rain, showers, snow_cm = series("rain"), series("showers"), series("snowfall")
    rain_in = []
    for r, s in zip(rain, showers):
        rain_in.append(None if r is None and s is None else ((r or 0.0) + (s or 0.0)) / MM_PER_INCH)
    return HourlySeries(
        start=int(times[0]),
        wind_mph=list(series("wind_speed_10m")),
        rain_in=rain_in,
        snow_in=[None if v is None else v / CM_PER_INCH for v in snow_cm],
    )


def _fetch_batch(coords: list[tuple[float, float]], start: datetime, end: datetime) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{c[0]:.4f}" for c in coords),
        "longitude": ",".join(f"{c[1]:.4f}" for c in coords),
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    try:
        resp = requests.get(URL, params=params, timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ProviderError(f"Could not reach Open-Meteo: {exc.__class__.__name__}") from exc
    if resp.status_code == 429:
        raise ProviderError("Open-Meteo free-tier rate limit reached. Please wait a minute and retry.", status=503)
    if resp.status_code != 200:
        reason = ""
        try:
            reason = resp.json().get("reason", "")
        except ValueError:
            pass
        raise ProviderError(f"Open-Meteo returned HTTP {resp.status_code}. {reason}".strip())
    data = resp.json()
    items = data if isinstance(data, list) else [data]
    if len(items) != len(coords):
        raise ProviderError("Open-Meteo returned an unexpected number of locations.")
    return [_parse_location(it) for it in items]


def fetch_hourly(points: list[tuple[float, float]], start: datetime, end: datetime) -> list[HourlySeries]:
    """Hourly series for each point covering [start, end] (UTC, inclusive, hour resolution)."""
    start_h = _hour_floor(start)
    end_h = _hour_floor(end) + timedelta(hours=1)
    snapped = [snap(*p) for p in points]

    unique, results = [], {}
    for c in dict.fromkeys(snapped):
        key = f"om:{c[0]}:{c[1]}:{int(start_h.timestamp())}:{int(end_h.timestamp())}"
        hit = cache.get(key)
        if hit is not None:
            results[c] = hit
        else:
            unique.append(c)

    batches = [unique[i:i + BATCH_SIZE] for i in range(0, len(unique), BATCH_SIZE)]
    if batches:
        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            for batch, series_list in zip(batches, pool.map(lambda b: _fetch_batch(b, start_h, end_h), batches)):
                for c, s in zip(batch, series_list):
                    results[c] = s
                    cache.set(f"om:{c[0]}:{c[1]}:{int(start_h.timestamp())}:{int(end_h.timestamp())}", s)
    log.info("Open-Meteo: %d points, %d unique, %d fetched", len(points), len(results), len(unique))
    return [results[c] for c in snapped]
