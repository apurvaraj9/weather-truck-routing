"""Deterministic stand-ins for TomTom and Open-Meteo used by the API tests.

They only replace the HTTP layer (requests.get); all of the app's own parsing,
sampling, risk and recommendation code runs for real.
"""
import re
from datetime import datetime
from urllib.parse import unquote

ORIGIN = (35.0, -100.0)
DEST = (35.0, -98.0)
METERS_PER_MILE = 1609.344


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _route(points, seconds_per_mile=60.0):
    """Build a TomTom-style route dict for a polyline with constant speed."""
    from planner.geo import cumulative_mi
    cum = cumulative_mi(points)
    progress = [{"pointIndex": i, "distanceInMeters": round(cum[i] * METERS_PER_MILE),
                 "travelTimeInSeconds": round(cum[i] * seconds_per_mile)} for i in range(0, len(points), 10)]
    return {
        "summary": {"lengthInMeters": round(cum[-1] * METERS_PER_MILE),
                    "travelTimeInSeconds": round(cum[-1] * seconds_per_mile)},
        "legs": [{"points": [{"latitude": la, "longitude": lo} for la, lo in points]}],
        "progress": progress,
    }


def bent(o, d, lat_shift, n=60):
    """Polyline from o to d bowing north/south by lat_shift degrees in the middle."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        bow = lat_shift * 4 * t * (1 - t)
        pts.append((o[0] + (d[0] - o[0]) * t + bow, o[1] + (d[1] - o[1]) * t))
    return pts


class FakeTomTom:
    """routes_returned: how many routes TomTom's main request returns (1-3)."""

    def __init__(self, routes_returned=3):
        self.routes_returned = routes_returned
        self.route_calls = []

    def __call__(self, url, params, timeout):
        if "/search/2/geocode/" in url:
            q = unquote(url.split("/geocode/")[1].rsplit(".json", 1)[0])
            if q == "Nowhere":
                return FakeResponse(200, {"results": []})
            pos = ORIGIN if q == "Origin City" else DEST
            return FakeResponse(200, {"results": [{"position": {"lat": pos[0], "lon": pos[1]},
                                                   "address": {"freeformAddress": f"{q}, USA"}}]})
        if "/routing/1/calculateRoute/" in url:
            self.route_calls.append(params)
            locs = url.split("/calculateRoute/")[1].split("/json")[0].split(":")
            if len(locs) == 3:  # via circle
                m = re.match(r"circle\(([-\d.]+),([-\d.]+),\d+\)", locs[1])
                via_lat = float(m.group(1))
                return FakeResponse(200, {"routes": [_route(bent(ORIGIN, DEST, via_lat - 35.0), 62)]})
            routes = [_route(bent(ORIGIN, DEST, 0.0), 60),      # fastest, straight
                      _route(bent(ORIGIN, DEST, 0.6), 65),      # north
                      _route(bent(ORIGIN, DEST, -0.6), 70)]     # south
            return FakeResponse(200, {"routes": routes[: self.routes_returned]})
        raise AssertionError(f"unexpected URL {url}")


class FakeOpenMeteo:
    """Weather depends on latitude: north of 35.3 is windy (40 mph), south of 34.7 has heavy rain."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, params, timeout):
        self.calls.append(params)
        lats = [float(v) for v in params["latitude"].split(",")]
        start = datetime.fromisoformat(params["start_hour"] + "+00:00")
        end = datetime.fromisoformat(params["end_hour"] + "+00:00")
        hours = int((end - start).total_seconds() // 3600) + 1
        t0 = int(start.timestamp())
        items = []
        for lat in lats:
            wind = 40.0 if lat > 35.3 else 10.0
            rain = 7.0 if lat < 34.7 else 0.0  # 7 mm = 0.276 in -> High
            items.append({"hourly": {
                "time": [t0 + h * 3600 for h in range(hours)],
                "wind_speed_10m": [wind] * hours,
                "rain": [rain] * hours,
                "showers": [0.0] * hours,
                "snowfall": [0.0] * hours,
            }})
        return FakeResponse(200, items if len(items) > 1 else items[0])


def router(tomtom: FakeTomTom, openmeteo: FakeOpenMeteo):
    def get(url, params=None, timeout=None):
        if "open-meteo" in url:
            return openmeteo(url, params, timeout)
        return tomtom(url, params, timeout)
    return get
