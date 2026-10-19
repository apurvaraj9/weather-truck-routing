"""Recommendation order: Severe miles, High miles, average risk, travel time."""
from django.test import SimpleTestCase

from planner.recommend import rank, summarize
from planner.risk import HIGH, LOW, MODERATE, NO_TRAVEL, SEVERE


def route(rid, seconds, levels, miles_each=10.0):
    return summarize(rid, miles_each * len(levels), seconds, [(lv, miles_each) for lv in levels])


class Summaries(SimpleTestCase):
    def test_miles_by_level_and_average(self):
        s = summarize("A", 40, 3600, [(LOW, 10), (HIGH, 20), (SEVERE, 10)])
        self.assertEqual(s.miles_by_level, {"Low": 10, "Moderate": 0, "High": 20, "Severe": 10, "No Travel": 0})
        self.assertAlmostEqual(s.average_risk, (0 * 10 + 2 * 20 + 3 * 10) / 40)
        self.assertEqual(s.max_level, SEVERE)

    def test_average_is_distance_weighted(self):
        s = summarize("A", 100, 1, [(SEVERE, 1), (LOW, 99)])
        self.assertAlmostEqual(s.average_risk, 0.03)


class Ranking(SimpleTestCase):
    def test_rule1_fewest_severe_miles_beats_everything_else(self):
        a = route("A", 1000, [SEVERE, LOW, LOW])        # fastest, but 10 Severe miles
        b = route("B", 9000, [HIGH, HIGH, HIGH])        # slow, many High miles, no Severe
        ordered, reason = rank([a, b])
        self.assertEqual(ordered[0].route_id, "B")
        self.assertIn("fewest Severe miles", reason)

    def test_rule2_fewest_high_miles_when_severe_tied(self):
        a = route("A", 1000, [HIGH, HIGH, LOW])
        b = route("B", 2000, [HIGH, MODERATE, MODERATE])
        ordered, reason = rank([a, b])
        self.assertEqual(ordered[0].route_id, "B")
        self.assertIn("fewest High miles", reason)

    def test_rule3_lowest_average_risk_when_severe_and_high_tied(self):
        a = route("A", 1000, [MODERATE, MODERATE, LOW])
        b = route("B", 2000, [MODERATE, LOW, LOW])
        ordered, reason = rank([a, b])
        self.assertEqual(ordered[0].route_id, "B")
        self.assertIn("lowest average risk", reason)

    def test_rule4_shortest_time_when_all_risk_tied(self):
        a = route("A", 2000, [LOW, LOW])
        b = route("B", 1500, [LOW, LOW])
        c = route("C", 1800, [LOW, LOW])
        ordered, reason = rank([a, b, c])
        self.assertEqual([s.route_id for s in ordered], ["B", "C", "A"])
        self.assertIn("shortest travel time", reason)

    def test_no_travel_is_never_preferred_over_severe(self):
        a = route("A", 1000, [NO_TRAVEL, LOW, LOW])
        b = route("B", 2000, [SEVERE, SEVERE, SEVERE])
        self.assertEqual(rank([a, b])[0][0].route_id, "B")

    def test_three_routes_full_order(self):
        a = route("A", 1000, [SEVERE, LOW])
        b = route("B", 3000, [LOW, LOW])
        c = route("C", 2000, [HIGH, LOW])
        ordered, _ = rank([a, b, c])
        self.assertEqual([s.route_id for s in ordered], ["B", "C", "A"])

    def test_single_route(self):
        ordered, reason = rank([route("A", 1, [LOW])])
        self.assertEqual(ordered[0].route_id, "A")
        self.assertIn("only", reason)
