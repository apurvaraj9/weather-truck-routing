"""Weather heatmap along the trip corridor.

The corridor is every grid cell whose centre lies within CORRIDOR_MILES of any of the
route options. Grid spacing grows with trip length so the number of cells (and so the
number of Open-Meteo lookups) stays bounded.
"""
import math
from datetime import datetime, timedelta

from .geo import LatLon, cumulative_mi, haversine_mi, point_at
from .providers import openmeteo
from .risk import assess

CORRIDOR_MILES = 25.0
MAX_CELLS = 160
MIN_SPACING_MILES = 6.0
HEATMAP_HOURS = 48  # slider covers forecast hours 0..48 inclusive


def _route_samples(points: list[LatLon], every_miles: float) -> list[LatLon]:
    cum = cumulative_mi(points)
    n = max(2, int(cum[-1] / every_miles) + 2)
    return [point_at(points, cum, cum[-1] * i / (n - 1)) for i in range(n)]


def build_grid(routes: list[list[LatLon]]) -> dict:
    """Return {"spacing_miles", "cells": [{"lat","lon","dlat","dlon"}]} covering the corridor."""
    longest = max(cumulative_mi(r)[-1] for r in routes)
    area = max(longest, 1.0) * 2 * CORRIDOR_MILES
    spacing = max(MIN_SPACING_MILES, math.sqrt(area / (MAX_CELLS * 0.8)))

    all_pts = [p for r in routes for p in r]
    lat_min = min(p[0] for p in all_pts)
    lat_max = max(p[0] for p in all_pts)
    lon_min = min(p[1] for p in all_pts)
    lon_max = max(p[1] for p in all_pts)
    mid_lat = (lat_min + lat_max) / 2

    while True:
        dlat = spacing / 69.0
        dlon = spacing / (69.0 * max(0.2, math.cos(math.radians(mid_lat))))
        samples = [s for r in routes for s in _route_samples(r, spacing / 2)]
        pad_lat = CORRIDOR_MILES / 69.0
        pad_lon = CORRIDOR_MILES / (69.0 * max(0.2, math.cos(math.radians(mid_lat))))
        cells = []
        lat = lat_min - pad_lat
        while lat <= lat_max + pad_lat:
            lon = lon_min - pad_lon
            while lon <= lon_max + pad_lon:
                # quick bounding-box rejection before exact distance checks
                if any(abs(s[0] - lat) <= pad_lat and abs(s[1] - lon) <= pad_lon
                       and haversine_mi((lat, lon), s) <= CORRIDOR_MILES for s in samples):
                    cells.append({"lat": round(lat, 4), "lon": round(lon, 4),
                                  "dlat": round(dlat, 5), "dlon": round(dlon, 5)})
                lon += dlon
            lat += dlat
        if len(cells) <= MAX_CELLS:
            return {"spacing_miles": round(spacing, 1), "cells": cells}
        spacing *= 1.15


def forecast_query(cells: list[dict], start: datetime) -> dict:
    """Open-Meteo request (made by the browser) for hours 0..48 after `start`."""
    start_h = openmeteo.hour_floor(start)
    query, index = openmeteo.build_query([(c["lat"], c["lon"]) for c in cells],
                                         start_h, start_h + timedelta(hours=HEATMAP_HOURS))
    query["start"] = start_h.isoformat()
    query["cell_point"] = index  # cell i uses query["points"][cell_point[i]]
    return query


def hourly_risk(series: list, cell_point: list[int], start: datetime, load_lb: float) -> dict:
    """Wind/rain/snow and risk level for each cell for hours 0..HEATMAP_HOURS after `start`."""
    start_h = openmeteo.hour_floor(start)
    out = []
    for p in cell_point:
        s = series[p]
        wind, rain, snow, level = [], [], [], []
        for h in range(HEATMAP_HOURS + 1):
            # Value "at" hour h: wind at that hour, precipitation over the hour starting there.
            w = s.at(start_h.timestamp() + h * 3600)
            r = assess(w["wind_mph"], w["rain_in_hr"], w["snow_in_hr"], load_lb)
            wind.append(w["wind_mph"])
            rain.append(w["rain_in_hr"])
            snow.append(w["snow_in_hr"])
            level.append(r.level)
        out.append({"wind": wind, "rain": rain, "snow": snow, "level": level})
    return {"start": start_h.isoformat(), "hours": HEATMAP_HOURS, "cells": out}
