"""Open-Meteo request description, parsing, unit conversion and hour selection at ETA."""
from datetime import datetime, timezone

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


class Parsing(SimpleTestCase):
    def test_units_are_converted_to_inches(self):
        s = openmeteo.parse_hourly(om_item(wind=[30, 30, 30, 30], rain=[0, 2.0, 0, 0],
                                           showers=[0, 0.54, 0, 0], snow=[0, 0, 2.54, 0])["hourly"])
        self.assertAlmostEqual(s.rain_in[1], 0.1)   # (2.0 + 0.54) mm = 0.1 in
        self.assertAlmostEqual(s.snow_in[2], 1.0)   # 2.54 cm = 1.0 in
        self.assertEqual(s.wind_mph[0], 30)

    def test_rain_boundary_survives_unit_conversion(self):
        # 2.54 mm/h must classify as exactly 0.10 in/h (Moderate), not 0.0999...
        s = openmeteo.parse_hourly(om_item(rain=[0, 2.54, 0, 0])["hourly"])
        self.assertEqual(s.at(T0 + 30 * 60)["rain_in_hr"], 0.1)


class ValueAtEta(SimpleTestCase):
    def setUp(self):
        self.s = openmeteo.parse_hourly(om_item(
            wind=[10, 20, 30, 40], rain=[0, 2.54, 5.08, 0], snow=[0, 0, 0, 2.54])["hourly"])

    def test_wind_uses_nearest_hour(self):
        self.assertEqual(self.s.at(T0 + 20 * 60)["wind_mph"], 10)
        self.assertEqual(self.s.at(T0 + 40 * 60)["wind_mph"], 20)

    def test_precipitation_uses_the_hour_containing_the_eta(self):
        # Open-Meteo stamps precipitation at the END of its hour: value at T0+1h covers T0..T0+1h.
        self.assertEqual(self.s.at(T0 + 10 * 60)["rain_in_hr"], 0.1)
        self.assertEqual(self.s.at(T0 + 3600 + 59 * 60)["rain_in_hr"], 0.2)
        self.assertEqual(self.s.at(T0 + 2 * 3600 + 1)["snow_in_hr"], 1.0)

    def test_missing_values_are_flagged(self):
        s = openmeteo.parse_hourly(om_item(wind=[None, None, None, None])["hourly"])
        self.assertTrue(s.at(T0)["missing"])
        self.assertFalse(self.s.at(T0)["missing"])


class BrowserQuery(SimpleTestCase):
    """The server describes the Open-Meteo request; the browser sends it."""

    def setUp(self):
        self.start = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)
        self.end = datetime(2026, 10, 20, 2, 10, tzinfo=timezone.utc)

    def test_deduplicates_nearby_points_and_covers_the_window(self):
        pts = [(35.001, -100.001), (35.002, -100.002), (36.0, -101.0)]
        q, index = openmeteo.build_query(pts, self.start, self.end)
        self.assertEqual(len(q["points"]), 2)                # same 0.05-degree cell -> one lookup
        self.assertEqual(index, [0, 0, 1])
        self.assertEqual(q["params"]["start_hour"], "2026-10-20T00:00")
        self.assertEqual(q["params"]["end_hour"], "2026-10-20T03:00")
        self.assertEqual(q["params"]["wind_speed_unit"], "mph")
        self.assertEqual(q["params"]["timezone"], "GMT")
        self.assertEqual(q["params"]["hourly"], "wind_speed_10m,rain,showers,snowfall")
        self.assertEqual(q["batch_size"], 100)

    def test_rejects_malformed_posted_weather(self):
        good = om_item()["hourly"]
        for bad in [None, {}, {"time": []}, dict(good, rain=[0.0]), dict(good, wind_speed_10m=["x"] * 4),
                    dict(good, snowfall=[float("inf")] * 4)]:
            with self.subTest(bad=bad):
                with self.assertRaises(ProviderError):
                    openmeteo.parse_hourly(bad)
        with self.assertRaises(ProviderError):
            openmeteo.parse_many([good], 2)
