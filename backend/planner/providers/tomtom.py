"""TomTom Search (geocoding) and Routing APIs.

Docs: https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route
      https://docs.tomtom.com/search-api/documentation/geocoding-service/geocode
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import requests
from django.conf import settings

from . import ProviderError
from ..geo import METERS_PER_MILE, LatLon

log = logging.getLogger(__name__)

BASE = "https://api.tomtom.com"
LATLON_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


@dataclass
class Place:
    query: str
    label: str
    lat: float
    lon: float


@dataclass
class RawRoute:
    points: list[LatLon]
    length_miles: float
    travel_seconds: float
    # (point_index, route_miles, seconds_from_start) from TomTom's "progress" array
    anchors: list[tuple[int, float, float]]
    source: str  # "primary", "alternative" or "via-point"


def _key() -> str:
    if not settings.TOMTOM_API_KEY:
        raise ProviderError("TOMTOM_API_KEY is not configured on the server.", status=500)
    return settings.TOMTOM_API_KEY


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=params, timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ProviderError(f"Could not reach TomTom: {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise ProviderError("TomTom rejected the API key (check TOMTOM_API_KEY).", status=500)
    if resp.status_code == 429:
        raise ProviderError("TomTom rate limit reached. Please wait a moment and try again.", status=503)
    if resp.status_code == 400:
        detail = ""
        try:
            detail = resp.json().get("detailedError", {}).get("message", "")
        except ValueError:
            pass
        raise ProviderError(f"TomTom could not compute this route. {detail}".strip(), status=422)
    if resp.status_code != 200:
        raise ProviderError(f"TomTom returned HTTP {resp.status_code}.")
    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError("TomTom returned an invalid response.") from exc


def geocode(query: str) -> Place:
    """Resolve free text (or a "lat,lon" pair) to a single place."""
    m = LATLON_RE.match(query)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return Place(query, f"{lat:.5f}, {lon:.5f}", lat, lon)
    data = _get(f"{BASE}/search/2/geocode/{quote(query, safe='')}.json", {"key": _key(), "limit": 1})
    results = data.get("results") or []
    if not results:
        raise ProviderError(f'Could not find a location for "{query}".', status=422)
    r = results[0]
    pos = r["position"]
    label = r.get("address", {}).get("freeformAddress") or query
    return Place(query, label, float(pos["lat"]), float(pos["lon"]))


def _parse_route(route: dict, source: str) -> RawRoute:
    points: list[LatLon] = []
    for leg in route.get("legs", []):
        points.extend((p["latitude"], p["longitude"]) for p in leg.get("points", []))
    summary = route["summary"]
    anchors = []
    for p in route.get("progress", []) or []:
        if "pointIndex" in p and "distanceInMeters" in p and "travelTimeInSeconds" in p:
            anchors.append((int(p["pointIndex"]), p["distanceInMeters"] / METERS_PER_MILE,
                            float(p["travelTimeInSeconds"])))
    if len(points) < 2:
        raise ProviderError("TomTom returned a route without geometry.")
    return RawRoute(
        points=points,
        length_miles=summary["lengthInMeters"] / METERS_PER_MILE,
        travel_seconds=float(summary["travelTimeInSeconds"]),
        anchors=anchors,
        source=source,
    )


def calculate_routes(origin: LatLon, destination: LatLon, depart: datetime | None,
                     max_alternatives: int = 2, via: LatLon | None = None,
                     via_radius_m: int = 0) -> list[RawRoute]:
    """Truck routes from origin to destination.

    depart=None means "now". `via` (optional) forces the route through a circle
    around a point; used only to obtain extra distinct routes when TomTom
    returns fewer than three.
    """
    locs = [f"{origin[0]:.6f},{origin[1]:.6f}"]
    if via:
        locs.append(f"circle({via[0]:.6f},{via[1]:.6f},{int(via_radius_m)})")
    locs.append(f"{destination[0]:.6f},{destination[1]:.6f}")
    params = {
        "key": _key(),
        "travelMode": "truck",
        "routeType": "fastest",
        "traffic": "true",
        "routeRepresentation": "polyline",
        "extendedRouteRepresentation": ["distance", "travelTime"],
        "maxAlternatives": max_alternatives,
        "departAt": depart.isoformat(timespec="seconds") if depart else "now",
    }
    data = _get(f"{BASE}/routing/1/calculateRoute/{':'.join(locs)}/json", params)
    routes = data.get("routes") or []
    if not routes:
        raise ProviderError("TomTom found no route between these locations.", status=422)
    out = []
    for i, r in enumerate(routes):
        source = "via-point" if via else ("primary" if i == 0 else "alternative")
        out.append(_parse_route(r, source))
    return out
