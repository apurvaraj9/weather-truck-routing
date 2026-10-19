"""Geometry helpers: distances, checkpoint sampling along a route, ETAs, simplification."""
import math
from bisect import bisect_right
from dataclasses import dataclass

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_mi(points: list[LatLon]) -> list[float]:
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine_mi(points[i - 1], points[i]))
    return out


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation; xs must be non-decreasing. Clamps outside the range."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    x0, x1 = xs[i], xs[i + 1]
    if x1 == x0:
        return ys[i + 1]
    t = (x - x0) / (x1 - x0)
    return ys[i] + t * (ys[i + 1] - ys[i])


def point_at(points: list[LatLon], cum: list[float], d: float) -> LatLon:
    """Point located d miles (polyline distance) along the polyline."""
    if d <= 0:
        return points[0]
    if d >= cum[-1]:
        return points[-1]
    i = bisect_right(cum, d) - 1
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg == 0 else (d - cum[i]) / seg
    (la0, lo0), (la1, lo1) = points[i], points[i + 1]
    return (la0 + t * (la1 - la0), lo0 + t * (lo1 - lo0))


class RouteProfile:
    """Maps "route miles" (the routing provider's distance) to a position and travel time.

    The provider gives anchor points (polyline index -> distance from start, travel time
    from start). Between anchors we interpolate linearly along the polyline. This lets us
    find the position and the estimated arrival time at any distance along the route.
    """

    def __init__(self, points: list[LatLon], total_miles: float, total_seconds: float,
                 anchors: list[tuple[int, float, float]] | None = None):
        if len(points) < 2:
            raise ValueError("A route needs at least two points")
        self.points = points
        self.poly_cum = cumulative_mi(points)
        self.total_miles = float(total_miles)
        self.total_seconds = float(total_seconds)
        poly_total = self.poly_cum[-1]

        # anchors: (point_index, route_miles, seconds)
        rows = [(0.0, 0.0, 0.0)]
        for idx, miles, secs in sorted(anchors or []):
            idx = max(0, min(int(idx), len(points) - 1))
            rows.append((self.poly_cum[idx], float(miles), float(secs)))
        rows.append((poly_total, self.total_miles, self.total_seconds))

        # Keep the three columns monotonic (guards against provider rounding quirks).
        self._route_mi, self._poly_mi, self._secs = [], [], []
        for poly_mi, route_mi, secs in rows:
            if self._route_mi:
                route_mi = max(route_mi, self._route_mi[-1])
                poly_mi = max(poly_mi, self._poly_mi[-1])
                secs = max(secs, self._secs[-1])
            route_mi = min(route_mi, self.total_miles)
            secs = min(secs, self.total_seconds)
            self._route_mi.append(route_mi)
            self._poly_mi.append(poly_mi)
            self._secs.append(secs)

    def position_at(self, route_miles: float) -> LatLon:
        poly_mi = _interp(route_miles, self._route_mi, self._poly_mi)
        return point_at(self.points, self.poly_cum, poly_mi)

    def seconds_at(self, route_miles: float) -> float:
        return _interp(route_miles, self._route_mi, self._secs)


@dataclass(frozen=True)
class Checkpoint:
    index: int
    mile: float          # route miles from origin
    lat: float
    lon: float
    seconds: float       # estimated travel time from departure
    covered_miles: float  # route miles this checkpoint represents (for "Severe miles" etc.)


def checkpoint_miles(total_miles: float, interval: float) -> list[float]:
    """0, interval, 2*interval, ... and the destination (always included)."""
    if interval <= 0:
        raise ValueError("interval must be positive")
    miles, m = [], 0.0
    # Skip a sample that would sit within 0.05 mi of the destination (avoids near-duplicates).
    while m < total_miles - 0.05 or not miles:
        miles.append(round(m, 6))
        m += interval
    miles.append(round(total_miles, 6))
    return miles


def coverage(miles: list[float]) -> list[float]:
    """Each checkpoint represents the stretch halfway to its neighbours.

    The coverages add up exactly to the route length, so "Severe miles" etc. are
    expressed in real route miles.
    """
    n = len(miles)
    if n == 1:
        return [0.0]
    out = []
    for i in range(n):
        left = (miles[i] - miles[i - 1]) / 2 if i > 0 else 0.0
        right = (miles[i + 1] - miles[i]) / 2 if i < n - 1 else 0.0
        out.append(left + right)
    return out


def sample_checkpoints(profile: RouteProfile, interval_miles: float) -> list[Checkpoint]:
    miles = checkpoint_miles(profile.total_miles, interval_miles)
    cover = coverage(miles)
    result = []
    for i, (m, c) in enumerate(zip(miles, cover)):
        lat, lon = profile.position_at(m)
        result.append(Checkpoint(i, m, lat, lon, profile.seconds_at(m), c))
    return result


def simplify(points: list[LatLon], tolerance_deg: float = 0.0002) -> list[LatLon]:
    """Ramer-Douglas-Peucker simplification (iterative) to keep map payloads small."""
    n = len(points)
    if n <= 2:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_deg * tolerance_deg
    while stack:
        s, e = stack.pop()
        (ys, xs), (ye, xe) = points[s], points[e]
        dx, dy = xe - xs, ye - ys
        seg2 = dx * dx + dy * dy
        best_i, best_d = -1, -1.0
        for i in range(s + 1, e):
            py, px = points[i]
            if seg2 == 0:
                d2 = (px - xs) ** 2 + (py - ys) ** 2
            else:
                t = max(0.0, min(1.0, ((px - xs) * dx + (py - ys) * dy) / seg2))
                d2 = (px - xs - t * dx) ** 2 + (py - ys - t * dy) ** 2
            if d2 > best_d:
                best_i, best_d = i, d2
        if best_d > tol2:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    return [p for p, k in zip(points, keep) if k]


def downsample(points: list[LatLon], max_points: int) -> list[LatLon]:
    if len(points) <= max_points:
        return list(points)
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def overlap_fraction(candidate: list[LatLon], reference: list[LatLon], threshold_mi: float = 0.6) -> float:
    """Share of the candidate route lying within threshold_mi of the reference route."""
    cand = downsample(candidate, 60)
    ref = downsample(reference, 600)
    near = 0
    for p in cand:
        if any(haversine_mi(p, q) <= threshold_mi for q in ref):
            near += 1
    return near / len(cand)


def offset_point(a: LatLon, b: LatLon, fraction: float) -> LatLon:
    """Point at the midpoint of a-b pushed sideways by `fraction` of the a-b distance."""
    lat_m = (a[0] + b[0]) / 2
    lon_m = (a[1] + b[1]) / 2
    kx = math.cos(math.radians(lat_m))
    # vector a->b in a locally flat frame (x = east, y = north), in degrees of latitude
    dx = (b[1] - a[1]) * kx
    dy = b[0] - a[0]
    # perpendicular (rotate +90 degrees), scaled
    px, py = -dy * fraction, dx * fraction
    return (lat_m + py, lon_m + (px / kx if kx else 0.0))
