"""JSON API.

POST /api/plan/     -> 3 route options with checkpoints, weather at ETA, risk, recommendation
POST /api/heatmap/  -> 0-48 h forecast risk for the corridor grid returned by /api/plan/
GET  /api/health/   -> liveness check

The API is stateless (no cookies, sessions or auth), so CSRF protection is not used.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import heatmap
from .providers import ProviderError
from .service import build_plan

log = logging.getLogger(__name__)

INTERVALS = (10, 25, 50)
MAX_LOAD_LB = 200_000
MAX_DAYS_AHEAD = 7
PAST_GRACE = timedelta(minutes=15)


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


def parse_departure(value) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError("Departure date/time is required.")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError("Departure must be an ISO 8601 date/time.")
    if dt.tzinfo is None:
        raise ValidationError("Departure must include a time zone (e.g. 2026-10-20T08:00:00Z).")
    dt = dt.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if dt < now - PAST_GRACE:
        raise ValidationError("Departure time is in the past.")
    if dt > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError(f"Departure must be within the next {MAX_DAYS_AHEAD} days (weather forecast range).")
    return dt


def parse_load(value) -> float:
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


@require_GET
def health(_request):
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def plan(request):
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
        return JsonResponse(build_plan(origin, destination, departure, load, interval))
    except ProviderError as exc:
        log.warning("plan failed: %s", exc)
        return _error(str(exc), exc.status)


@csrf_exempt
@require_POST
def heatmap_view(request):
    try:
        data = _body(request)
        start = parse_departure(data.get("start"))
        load = parse_load(data.get("load_weight_lb"))
        cells = data.get("cells")
        if not isinstance(cells, list) or not cells or len(cells) > 400:
            raise ValidationError("cells must be a non-empty list of up to 400 [lat, lon] pairs.")
        coords = []
        for c in cells:
            if (not isinstance(c, (list, tuple)) or len(c) != 2
                    or not all(isinstance(v, (int, float)) for v in c)
                    or not (-90 <= c[0] <= 90 and -180 <= c[1] <= 180)):
                raise ValidationError("Each cell must be a [lat, lon] pair.")
            coords.append((float(c[0]), float(c[1])))
    except ValidationError as exc:
        return _error(str(exc), 400)

    try:
        return JsonResponse(heatmap.hourly_risk(coords, max(start, datetime.now(timezone.utc)), load))
    except ProviderError as exc:
        log.warning("heatmap failed: %s", exc)
        return _error(str(exc), exc.status)
