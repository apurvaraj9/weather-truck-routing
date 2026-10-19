"""End-to-end API tests with the HTTP layer of TomTom/Open-Meteo replaced by fakes."""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from planner.tests.fakes import FakeOpenMeteo, FakeTomTom, router


def future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


@override_settings(TOMTOM_API_KEY="test-key")
class PlanEndpoint(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.tomtom = FakeTomTom()
        self.weather = FakeOpenMeteo()

    def post(self, path="/api/plan/", **overrides):
        body = {"origin": "Origin City", "destination": "Dest City", "departure": future(),
                "load_weight_lb": 20000, "interval_miles": 25}
        body.update(overrides)
        with mock.patch("requests.get", side_effect=router(self.tomtom, self.weather)):
            return self.client.post(path, json.dumps(body), content_type="application/json")

    def test_returns_three_routes_with_checkpoints_eta_and_risk(self):
        res = self.post()
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual([r["id"] for r in data["routes"]], ["Route A", "Route B", "Route C"])
        dep = datetime.fromisoformat(data["departure"])
        for r in data["routes"]:
            cps = r["checkpoints"]
            miles = [c["mile"] for c in cps]
            self.assertEqual(miles[0], 0)
            self.assertEqual(miles[-1], r["summary"]["distance_miles"])
            # every 25 miles
            self.assertTrue(all(abs((b - a) - 25) < 0.11 for a, b in zip(miles[:-2], miles[1:-1])))
            # ETAs are increasing and start at departure
            etas = [datetime.fromisoformat(c["eta"]) for c in cps]
            self.assertEqual(etas[0], dep)
            self.assertEqual(etas, sorted(etas))
            for c in cps:
                self.assertIn(c["level_name"], ["Low", "Moderate", "High", "Severe", "No Travel"])
            total = sum(r["summary"]["miles_by_level"].values())
            self.assertAlmostEqual(total, r["summary"]["distance_miles"], delta=0.3)
        # The tomtom call asked for 2 alternatives with truck mode and the departure time.
        call = self.tomtom.route_calls[0]
        self.assertEqual(call["maxAlternatives"], 2)
        self.assertEqual(call["travelMode"], "truck")
        self.assertNotEqual(call["departAt"], "now")

    def test_eta_reflects_travel_time(self):
        data = self.post().json()
        a = data["routes"][0]
        dep = datetime.fromisoformat(data["departure"])
        last = a["checkpoints"][-1]
        eta = datetime.fromisoformat(last["eta"])
        # Fake route A drives 60 s per mile.
        self.assertAlmostEqual((eta - dep).total_seconds(), last["mile"] * 60, delta=90)

    def test_weather_risk_and_recommendation(self):
        data = self.post().json()
        routes = {r["id"]: r for r in data["routes"]}
        # North route (B) is windy (40 mph = High), south route (C) has 0.28 in/hr rain (High).
        self.assertGreater(routes["Route B"]["summary"]["miles_by_level"]["High"], 0)
        self.assertGreater(routes["Route C"]["summary"]["miles_by_level"]["High"], 0)
        self.assertEqual(routes["Route A"]["summary"]["max_level_name"], "Low")
        self.assertEqual(data["recommendation"]["route_id"], "Route A")
        self.assertTrue(routes["Route A"]["recommended"])
        self.assertIn("High miles", data["recommendation"]["reason"])

    def test_heavy_load_turns_high_wind_into_severe(self):
        data = self.post(load_weight_lb=45000).json()
        north = next(r for r in data["routes"] if r["id"] == "Route B")
        self.assertGreater(north["summary"]["miles_by_level"]["Severe"], 0)
        windy = [c for c in north["checkpoints"] if c["wind_mph"] >= 35]
        self.assertTrue(windy)
        self.assertTrue(all(c["level_name"] == "Severe" and c["load_rule"] for c in windy))

    def test_sampling_interval_changes_checkpoint_count(self):
        counts = {}
        for interval in (10, 25, 50):
            cache.clear()
            data = self.post(interval_miles=interval).json()
            counts[interval] = len(data["routes"][0]["checkpoints"])
        self.assertGreater(counts[10], counts[25])
        self.assertGreater(counts[25], counts[50])

    def test_fills_missing_alternatives_with_distinct_via_routes(self):
        self.tomtom = FakeTomTom(routes_returned=1)
        data = self.post().json()
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual([r["source"] for r in data["routes"]], ["primary", "via-point", "via-point"])
        self.assertTrue(any("fewer than 3" in n for n in data["notices"]))

    def test_heatmap_grid_is_returned(self):
        grid = self.post().json()["heatmap_grid"]
        self.assertGreater(len(grid["cells"]), 10)
        self.assertLessEqual(len(grid["cells"]), 160)

    def test_validation_errors(self):
        cases = [
            ({"origin": ""}, "Origin is required"),
            ({"departure": "2020-01-01T00:00:00Z"}, "in the past"),
            ({"departure": future(24 * 8)}, "within the next 7 days"),
            ({"departure": "2030-01-01T00:00:00"}, "time zone"),
            ({"load_weight_lb": -5}, "Load weight"),
            ({"load_weight_lb": "heavy"}, "Load weight"),
            ({"interval_miles": 15}, "10, 25 or 50"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                res = self.post(**overrides)
                self.assertEqual(res.status_code, 400)
                self.assertIn(message, res.json()["error"])

    def test_unknown_place(self):
        res = self.post(destination="Nowhere")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Could not find", res.json()["error"])

    @override_settings(TOMTOM_API_KEY="")
    def test_missing_api_key(self):
        res = self.post()
        self.assertEqual(res.status_code, 500)
        self.assertIn("TOMTOM_API_KEY", res.json()["error"])


class HeatmapEndpoint(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def post(self, body):
        with mock.patch("requests.get", side_effect=router(FakeTomTom(), FakeOpenMeteo())):
            return self.client.post("/api/heatmap/", json.dumps(body), content_type="application/json")

    def test_returns_49_hourly_values_per_cell(self):
        res = self.post({"cells": [[35.6, -99.0], [34.4, -99.0], [35.0, -99.0]],
                         "start": future(1), "load_weight_lb": 45000})
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["hours"], 48)
        self.assertEqual(len(data["cells"]), 3)
        for cell in data["cells"]:
            self.assertEqual(len(cell["level"]), 49)
        self.assertEqual(set(data["cells"][0]["level"]), {3})  # 40 mph + 45,000 lb -> Severe
        self.assertEqual(set(data["cells"][1]["level"]), {2})  # 0.28 in/hr rain -> High
        self.assertEqual(set(data["cells"][2]["level"]), {0})

    def test_rejects_bad_cells(self):
        res = self.post({"cells": [[200, 0]], "start": future(1), "load_weight_lb": 0})
        self.assertEqual(res.status_code, 400)


class Health(SimpleTestCase):
    def test_ok(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})
