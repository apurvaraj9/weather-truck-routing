"""JSON API.

A trip is planned in two calls, because the browser (not the server) fetches the
forecasts from Open-Meteo (see providers/openmeteo.py for why):

POST /api/routes/   -> 3 route options, checkpoints with ETAs, and the forecast request
                       the browser must send to Open-Meteo
POST /api/plan/     -> weather at each checkpoint's ETA, risk levels, route summaries
                       and the recommendation, from the forecasts the browser fetched
POST /api/heatmap/  -> 0-48 h risk for the corridor cells, from browser-fetched forecasts
GET  /api/health/   -> liveness check

The API is stateless (no cookies, sessions or auth), so CSRF protection is not used.
"""
import json
import logging
import math
from datetime import datetime, timedelta, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import heatmap
from .providers import ProviderError, openmeteo
from .service import plan_routes, score_routes

log = logging.getLogger(__name__)

INTERVALS = (10, 25, 50)
MAX_LOAD_LB = 200_000
MAX_DAYS_AHEAD = 7
PAST_GRACE = timedelta(minutes=15)
MAX_ROUTES = 3
MAX_CHECKPOINTS = 2_000      # per route (a 10-mile spacing covers 20,000 miles)
MAX_WEATHER_POINTS = 6_000


class ValidationError(Exception):
    pass


def _error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    return data


def parse_datetime(value, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} is required.")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must be an ISO 8601 date/time.")
    if dt.tzinfo is None:
        raise ValidationError(f"{name} must include a time zone (e.g. 2026-10-20T08:00:00Z).")
    return dt.astimezone(timezone.utc)


def parse_departure(value) -> datetime:
    dt = parse_datetime(value, "Departure date/time")
    now = datetime.now(timezone.utc)
    if dt < now - PAST_GRACE:
        raise ValidationError("Departure time is in the past.")
    if dt > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError(f"Departure must be within the next {MAX_DAYS_AHEAD} days (weather forecast range).")
    return dt


def parse_load(value) -> float:
    if isinstance(value, bool):
        raise ValidationError("Load weight must be a number of pounds.")
    try:
        load = float(value)
    except (TypeError, ValueError):
        raise ValidationError("Load weight must be a number of pounds.")
    if not 0 <= load <= MAX_LOAD_LB:
        raise ValidationError(f"Load weight must be between 0 and {MAX_LOAD_LB:,} lb.")
    return load


def parse_place(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} is required.")
    if len(value) > 200:
        raise ValidationError(f"{name} is too long.")
    return value.strip()


def _num(value, name: str, lo: float = -math.inf, hi: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not lo <= value <= hi:
        raise ValidationError(f"Invalid route data: {name}.")
    return value


def parse_scoring_routes(value, weather_count: int) -> list[dict]:
    """Validate the routes returned by /api/routes/ and posted back for scoring."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ROUTES:
        raise ValidationError("Invalid route data: routes.")
    routes = []
    for r in value:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or len(r["id"]) > 20:
            raise ValidationError("Invalid route data: id.")
        cps = r.get("checkpoints")
        if not isinstance(cps, list) or not 1 <= len(cps) <= MAX_CHECKPOINTS:
            raise ValidationError("Invalid route data: checkpoints.")
        clean = []
        for cp in cps:
            if not isinstance(cp, dict):
                raise ValidationError("Invalid route data: checkpoint.")
            point = cp.get("point")
            if isinstance(point, bool) or not isinstance(point, int) or not 0 <= point < weather_count:
                raise ValidationError("Invalid route data: checkpoint weather index.")
            clean.append({
                "index": int(_num(cp.get("index"), "index", 0)),
                "mile": _num(cp.get("mile"), "mile", 0),
                "lat": _num(cp.get("lat"), "lat", -90, 90),
                "lon": _num(cp.get("lon"), "lon", -180, 180),
                "eta": parse_datetime(cp.get("eta"), "Checkpoint ETA").isoformat(timespec="minutes"),
                "covered_miles": _num(cp.get("covered_miles"), "covered_miles", 0),
                "point": point,
            })
        routes.append({
            "id": r["id"],
            "source": str(r.get("source", ""))[:20],
            "distance_miles": _num(r.get("distance_miles"), "distance_miles", 0),
            "duration_seconds": _num(r.get("duration_seconds"), "duration_seconds", 0),
            "checkpoints": clean,
        })
    return routes


def parse_weather(value) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_WEATHER_POINTS:
        raise ValidationError("Weather data must be a list with one entry per forecast location.")
    try:
        return openmeteo.parse_many(value, len(value))
    except ProviderError as exc:
        raise ValidationError(str(exc))


@require_GET
def health(_request):
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def routes(request):
    try:
        data = _body(request)
        origin = parse_place(data.get("origin"), "Origin")
        destination = parse_place(data.get("destination"), "Destination")
        departure = parse_departure(data.get("departure"))
        load = parse_load(data.get("load_weight_lb"))
        try:
            interval = int(data.get("interval_miles", 25))
        except (TypeError, ValueError):
            interval = -1
        if interval not in INTERVALS:
            raise ValidationError("Sampling interval must be 10, 25 or 50 miles.")
    except ValidationError as exc:
        return _error(str(exc), 400)

    try:
        return JsonResponse(plan_routes(origin, destination, departure, load, interval))
    except ProviderError as exc:
        log.warning("routes failed: %s", exc)
        return _error(str(exc), exc.status)


@csrf_exempt
@require_POST
def plan(request):
    try:
        data = _body(request)
        departure = parse_datetime(data.get("departure"), "Departure date/time")
        load = parse_load(data.get("load_weight_lb"))
        series = parse_weather(data.get("weather"))
        route_list = parse_scoring_routes(data.get("routes"), len(series))
    except ValidationError as exc:
        return _error(str(exc), 400)
    return JsonResponse(score_routes(departure, load, route_list, series))


@csrf_exempt
@require_POST
def heatmap_view(request):
    try:
        data = _body(request)
        start = parse_datetime(data.get("start"), "start")
        load = parse_load(data.get("load_weight_lb"))
        series = parse_weather(data.get("weather"))
        cell_point = data.get("cell_point")
        if not isinstance(cell_point, list) or not 1 <= len(cell_point) <= 400 or any(
                isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < len(series) for p in cell_point):
            raise ValidationError("cell_point must list, for each cell, the index of its weather entry.")
    except ValidationError as exc:
        return _error(str(exc), 400)
    return JsonResponse(heatmap.hourly_risk(series, cell_point, start, load))
