"""End-to-end API tests.

The HTTP layer of TomTom is replaced by a fake; the browser's Open-Meteo step is
simulated with the same fake forecast data, exactly as the frontend performs it
(server-described query -> raw `hourly` blocks posted back).
"""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase, override_settings

from planner.tests.fakes import FakeOpenMeteo, FakeTomTom, browser_fetch


def future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def server_get(tomtom):
    """requests.get for the server: TomTom only. Any Open-Meteo call from the server fails the test."""
    def get(url, params=None, timeout=None):
        if "open-meteo" in url:
            raise AssertionError("The server must not call Open-Meteo (the browser does).")
        return tomtom(url, params, timeout)
    return get


class Flow(SimpleTestCase):
    def setUp(self):
        self.tomtom = FakeTomTom()
        self.weather = FakeOpenMeteo()

    def post(self, path, body):
        with mock.patch("requests.get", side_effect=server_get(self.tomtom)):
            return self.client.post(path, json.dumps(body), content_type="application/json")

    def get_routes(self, **overrides):
        body = {"origin": "Origin City", "destination": "Dest City", "departure": future(),
                "load_weight_lb": 20000, "interval_miles": 25}
        body.update(overrides)
        return self.post("/api/routes/", body)

    def plan(self, **overrides):
        """Full trip as the frontend runs it: routes -> browser weather fetch -> scoring."""
        res = self.get_routes(**overrides)
        self.assertEqual(res.status_code, 200, res.content)
        trip = res.json()
        weather = browser_fetch(trip["weather_query"], self.weather)
        scored = self.post("/api/plan/", {
            "departure": trip["departure"],
            "load_weight_lb": trip["load_weight_lb"],
            "routes": [{k: v for k, v in r.items() if k != "geometry"} for r in trip["routes"]],
            "weather": weather,
        })
        self.assertEqual(scored.status_code, 200, scored.content)
        return trip, scored.json()


@override_settings(TOMTOM_API_KEY="test-key")
class RoutesAndPlan(Flow):
    def test_routes_step_returns_three_routes_checkpoints_etas_and_weather_query(self):
        trip = self.get_routes().json()
        self.assertEqual([r["id"] for r in trip["routes"]], ["Route A", "Route B", "Route C"])
        dep = datetime.fromisoformat(trip["departure"])
        q = trip["weather_query"]
        self.assertEqual(q["url"], "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(q["params"]["wind_speed_unit"], "mph")
        for r in trip["routes"]:
            self.assertGreater(len(r["geometry"]), 1)
            cps = r["checkpoints"]
            miles = [c["mile"] for c in cps]
            self.assertEqual(miles[0], 0)
            self.assertEqual(miles[-1], r["distance_miles"])
            self.assertTrue(all(abs((b - a) - 25) < 0.11 for a, b in zip(miles[:-2], miles[1:-1])))
            etas = [datetime.fromisoformat(c["eta"]) for c in cps]
            self.assertEqual(etas[0], dep)
            self.assertEqual(etas, sorted(etas))
            self.assertTrue(all(0 <= c["point"] < len(q["points"]) for c in cps))
        call = self.tomtom.route_calls[0]
        self.assertEqual((call["maxAlternatives"], call["travelMode"]), (2, "truck"))
        self.assertNotEqual(call["departAt"], "now")

    def test_full_plan_risk_and_levels(self):
        trip, plan = self.plan()
        self.assertEqual(len(plan["routes"]), 3)
        for r in plan["routes"]:
            for c in r["checkpoints"]:
                self.assertIn(c["level_name"], ["Low", "Moderate", "High", "Severe", "No Travel"])
            total = sum(r["summary"]["miles_by_level"].values())
            self.assertAlmostEqual(total, r["summary"]["distance_miles"], delta=0.3)

    def test_eta_reflects_travel_time(self):
        trip, plan = self.plan()
        a = plan["routes"][0]
        dep = datetime.fromisoformat(trip["departure"])
        last = a["checkpoints"][-1]
        # Fake route A drives 60 s per mile.
        self.assertAlmostEqual((datetime.fromisoformat(last["eta"]) - dep).total_seconds(), last["mile"] * 60, delta=90)
        self.assertEqual(datetime.fromisoformat(a["summary"]["arrival"]), datetime.fromisoformat(last["eta"]))

    def test_weather_risk_and_recommendation(self):
        _, plan = self.plan()
        routes = {r["id"]: r for r in plan["routes"]}
        # North route (B) is windy (40 mph = High), south route (C) has 0.28 in/hr rain (High).
        self.assertGreater(routes["Route B"]["summary"]["miles_by_level"]["High"], 0)
        self.assertGreater(routes["Route C"]["summary"]["miles_by_level"]["High"], 0)
        self.assertEqual(routes["Route A"]["summary"]["max_level_name"], "Low")
        self.assertEqual(plan["recommendation"]["route_id"], "Route A")
        self.assertTrue(routes["Route A"]["recommended"])
        self.assertIn("High miles", plan["recommendation"]["reason"])

    def test_heavy_load_turns_high_wind_into_severe(self):
        _, plan = self.plan(load_weight_lb=45000)
        north = next(r for r in plan["routes"] if r["id"] == "Route B")
        self.assertGreater(north["summary"]["miles_by_level"]["Severe"], 0)
        windy = [c for c in north["checkpoints"] if c["wind_mph"] >= 35]
        self.assertTrue(windy)
        self.assertTrue(all(c["level_name"] == "Severe" and c["load_rule"] for c in windy))

    def test_sampling_interval_changes_checkpoint_count(self):
        counts = {i: len(self.get_routes(interval_miles=i).json()["routes"][0]["checkpoints"]) for i in (10, 25, 50)}
        self.assertGreater(counts[10], counts[25])
        self.assertGreater(counts[25], counts[50])

    def test_fills_missing_alternatives_with_distinct_via_routes(self):
        self.tomtom = FakeTomTom(routes_returned=1)
        trip = self.get_routes().json()
        self.assertEqual([r["source"] for r in trip["routes"]], ["primary", "via-point", "via-point"])
        self.assertTrue(any("fewer than 3" in n for n in trip["notices"]))

    def test_heatmap_grid_and_query_are_returned(self):
        trip = self.get_routes().json()
        cells = trip["heatmap_grid"]["cells"]
        self.assertGreater(len(cells), 10)
        self.assertLessEqual(len(cells), 160)
        q = trip["heatmap_query"]
        self.assertEqual(len(q["cell_point"]), len(cells))
        start = datetime.fromisoformat(q["params"]["start_hour"] + "+00:00")
        end = datetime.fromisoformat(q["params"]["end_hour"] + "+00:00")
        self.assertEqual(end - start, timedelta(hours=49))

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
                res = self.get_routes(**overrides)
                self.assertEqual(res.status_code, 400)
                self.assertIn(message, res.json()["error"])

    def test_plan_rejects_bad_weather_or_route_data(self):
        trip = self.get_routes().json()
        weather = browser_fetch(trip["weather_query"], self.weather)
        routes = [{k: v for k, v in r.items() if k != "geometry"} for r in trip["routes"]]
        base = {"departure": trip["departure"], "load_weight_lb": 20000, "routes": routes, "weather": weather}
        bad = [
            dict(base, weather=weather[:-1] if len(weather) > 1 else []),        # missing a location
            dict(base, weather=[{"time": "x"}] * len(weather)),                    # not Open-Meteo format
            dict(base, routes=[]),
            dict(base, load_weight_lb=-1),
        ]
        broken = json.loads(json.dumps(routes))
        broken[0]["checkpoints"][0]["point"] = 10_000
        bad.append(dict(base, routes=broken))
        for body in bad:
            with self.subTest(body=list(body)):
                self.assertEqual(self.post("/api/plan/", body).status_code, 400)

    def test_unknown_place(self):
        res = self.get_routes(destination="Nowhere")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Could not find", res.json()["error"])

    @override_settings(TOMTOM_API_KEY="")
    def test_missing_api_key(self):
        res = self.get_routes()
        self.assertEqual(res.status_code, 500)
        self.assertIn("TOMTOM_API_KEY", res.json()["error"])


@override_settings(TOMTOM_API_KEY="test-key")
class HeatmapEndpoint(Flow):
    def heat(self, cells, load):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        from planner import heatmap
        q = heatmap.forecast_query([{"lat": la, "lon": lo} for la, lo in cells], start)
        weather = browser_fetch(q, self.weather)
        return self.post("/api/heatmap/", {"start": q["start"], "load_weight_lb": load,
                                           "cell_point": q["cell_point"], "weather": weather})

    def test_returns_49_hourly_values_per_cell(self):
        res = self.heat([(35.6, -99.0), (34.4, -99.0), (35.0, -99.0)], 45000)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["hours"], 48)
        self.assertEqual(len(data["cells"]), 3)
        for cell in data["cells"]:
            self.assertEqual(len(cell["level"]), 49)
        self.assertEqual(set(data["cells"][0]["level"]), {3})  # 40 mph + 45,000 lb -> Severe
        self.assertEqual(set(data["cells"][1]["level"]), {2})  # 0.28 in/hr rain -> High
        self.assertEqual(set(data["cells"][2]["level"]), {0})

    def test_rejects_bad_cell_index(self):
        res = self.post("/api/heatmap/", {"start": future(1), "load_weight_lb": 0,
                                          "cell_point": [5], "weather": [{"time": [0], "wind_speed_10m": [1]}]})
        self.assertEqual(res.status_code, 400)


class Health(SimpleTestCase):
    def test_ok(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})

    def test_referrer_policy_lets_map_tiles_load(self):
        # OpenStreetMap blocks tile requests that arrive without a Referer.
        res = self.client.get("/api/health/")
        self.assertEqual(res["Referrer-Policy"], "strict-origin-when-cross-origin")
