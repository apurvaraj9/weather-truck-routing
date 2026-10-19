"""Open-Meteo parsing, unit conversion, hour selection at ETA, batching and errors."""
from datetime import datetime, timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from planner.providers import ProviderError, openmeteo

T0 = int(datetime(2026, 10, 20, 0, tzinfo=timezone.utc).timestamp())


def om_item(hours=4, wind=None, rain=None, showers=None, snow=None):
    return {"hourly": {
        "time": [T0 + h * 3600 for h in range(hours)],
        "wind_speed_10m": wind or [0.0] * hours,
        "rain": rain or [0.0] * hours,
        "showers": showers or [0.0] * hours,
        "snowfall": snow or [0.0] * hours,
    }}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class Parsing(SimpleTestCase):
    def test_units_are_converted_to_inches(self):
        s = openmeteo._parse_location(om_item(wind=[30, 30, 30, 30], rain=[0, 2.0, 0, 0],
                                              showers=[0, 0.54, 0, 0], snow=[0, 0, 2.54, 0]))
        self.assertAlmostEqual(s.rain_in[1], 0.1)   # (2.0 + 0.54) mm = 0.1 in
        self.assertAlmostEqual(s.snow_in[2], 1.0)   # 2.54 cm = 1.0 in
        self.assertEqual(s.wind_mph[0], 30)

    def test_rain_boundary_survives_unit_conversion(self):
        # 2.54 mm/h must classify as exactly 0.10 in/h (Moderate), not 0.0999...
        s = openmeteo._parse_location(om_item(rain=[0, 2.54, 0, 0]))
        self.assertEqual(s.at(T0 + 30 * 60)["rain_in_hr"], 0.1)


class ValueAtEta(SimpleTestCase):
    def setUp(self):
        self.s = openmeteo._parse_location(om_item(
            wind=[10, 20, 30, 40], rain=[0, 2.54, 5.08, 0], snow=[0, 0, 0, 2.54]))

    def test_wind_uses_nearest_hour(self):
        self.assertEqual(self.s.at(T0 + 20 * 60)["wind_mph"], 10)
        self.assertEqual(self.s.at(T0 + 40 * 60)["wind_mph"], 20)

    def test_precipitation_uses_the_hour_containing_the_eta(self):
        # Open-Meteo stamps precipitation at the END of its hour: value at T0+1h covers T0..T0+1h.
        self.assertEqual(self.s.at(T0 + 10 * 60)["rain_in_hr"], 0.1)
        self.assertEqual(self.s.at(T0 + 3600 + 59 * 60)["rain_in_hr"], 0.2)
        self.assertEqual(self.s.at(T0 + 2 * 3600 + 1)["snow_in_hr"], 1.0)

    def test_missing_values_are_flagged(self):
        s = openmeteo._parse_location(om_item(wind=[None, None, None, None]))
        self.assertTrue(s.at(T0)["missing"])
        self.assertFalse(self.s.at(T0)["missing"])


class Fetching(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.start = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)
        self.end = datetime(2026, 10, 20, 2, 10, tzinfo=timezone.utc)

    def test_deduplicates_nearby_points_and_requests_correct_window(self):
        calls = []

        def fake_get(url, params, timeout):
            calls.append(params)
            n = len(params["latitude"].split(","))
            return FakeResponse(200, [om_item() for _ in range(n)] if n > 1 else om_item())

        pts = [(35.001, -100.001), (35.002, -100.002), (36.0, -101.0)]
        with mock.patch("planner.providers.openmeteo.requests.get", side_effect=fake_get):
            out = openmeteo.fetch_hourly(pts, self.start, self.end)
        self.assertEqual(len(out), 3)
        self.assertIs(out[0], out[1])                    # same 0.05-degree cell -> one lookup
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["latitude"].split(",")), 2)
        self.assertEqual(calls[0]["start_hour"], "2026-10-20T00:00")
        self.assertEqual(calls[0]["end_hour"], "2026-10-20T03:00")
        self.assertEqual(calls[0]["wind_speed_unit"], "mph")

        # Second identical request is served from cache.
        with mock.patch("planner.providers.openmeteo.requests.get", side_effect=AssertionError):
            openmeteo.fetch_hourly(pts, self.start, self.end)

    def test_batches_large_requests(self):
        calls = []

        def fake_get(url, params, timeout):
            n = len(params["latitude"].split(","))
            calls.append(n)
            return FakeResponse(200, [om_item() for _ in range(n)])

        pts = [(30 + i * 0.1, -100.0) for i in range(250)]
        with mock.patch("planner.providers.openmeteo.requests.get", side_effect=fake_get):
            out = openmeteo.fetch_hourly(pts, self.start, self.end)
        self.assertEqual(len(out), 250)
        self.assertEqual(sorted(calls), [50, 100, 100])

    def test_rate_limit_is_reported_clearly(self):
        with mock.patch("planner.providers.openmeteo.requests.get",
                        return_value=FakeResponse(429, {"reason": "limit"})):
            with self.assertRaises(ProviderError) as ctx:
                openmeteo.fetch_hourly([(35, -100)], self.start, self.end)
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("rate limit", str(ctx.exception))
