"""Risk table and load rules - every boundary from the assessment PDF."""
from django.test import SimpleTestCase

from planner.risk import (HIGH, LOW, MODERATE, NO_TRAVEL, SEVERE, apply_load_rules, assess,
                          classify_rain, classify_snow, classify_wind)


class WindThresholds(SimpleTestCase):
    def test_boundaries(self):
        cases = [
            (0, LOW), (24.9, LOW),
            (25, MODERATE), (34, MODERATE), (34.9, MODERATE),
            (35, HIGH), (44, HIGH), (44.9, HIGH),
            (45, SEVERE), (54, SEVERE), (54.9, SEVERE),
            (55, NO_TRAVEL), (80, NO_TRAVEL),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)


class RainThresholds(SimpleTestCase):
    def test_boundaries(self):
        cases = [
            (0, LOW), (0.09, LOW), (0.099, LOW),
            (0.10, MODERATE), (0.249, MODERATE),
            (0.25, HIGH), (0.499, HIGH),
            (0.50, SEVERE), (0.99, SEVERE), (1.00, SEVERE),   # "0.50-1.00" is Severe
            (1.001, NO_TRAVEL), (2.0, NO_TRAVEL),            # "> 1.00" is No Travel
        ]
        for value, expected in cases:
            with self.subTest(rain=value):
                self.assertEqual(classify_rain(value), expected)


class SnowThresholds(SimpleTestCase):
    def test_boundaries(self):
        cases = [
            (0, LOW), (0.49, LOW),
            (0.5, MODERATE), (0.99, MODERATE),
            (1.0, HIGH), (1.99, HIGH),
            (2.0, SEVERE), (2.99, SEVERE), (3.0, SEVERE),   # "2.0-3.0" is Severe
            (3.01, NO_TRAVEL), (5.0, NO_TRAVEL),           # "> 3.0" is No Travel
        ]
        for value, expected in cases:
            with self.subTest(snow=value):
                self.assertEqual(classify_snow(value), expected)


class LoadRules(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        for load in (0, 10_000, 30_000, 80_000):
            self.assertEqual(apply_load_rules(55, load)[0], NO_TRAVEL)

    def test_45_to_54_mph_over_30000_lb_is_no_travel(self):
        for mph in (45, 50, 54, 54.9):
            with self.subTest(mph=mph):
                level, rule = apply_load_rules(mph, 30_001)
                self.assertEqual(level, NO_TRAVEL)
                self.assertIsNotNone(rule)

    def test_45_to_54_mph_at_or_below_30000_lb_stays_severe(self):
        self.assertEqual(apply_load_rules(45, 30_000), (SEVERE, None))
        self.assertEqual(apply_load_rules(54, 20_000), (SEVERE, None))

    def test_35_to_44_mph_over_40000_lb_is_severe(self):
        for mph in (35, 40, 44, 44.9):
            with self.subTest(mph=mph):
                level, rule = apply_load_rules(mph, 40_001)
                self.assertEqual(level, SEVERE)
                self.assertIsNotNone(rule)

    def test_35_to_44_mph_at_or_below_40000_lb_stays_high(self):
        self.assertEqual(apply_load_rules(35, 40_000), (HIGH, None))
        # 30,001-40,000 lb does not trigger either load rule at 35-44 mph
        self.assertEqual(apply_load_rules(44, 35_000), (HIGH, None))

    def test_below_35_mph_load_has_no_effect(self):
        self.assertEqual(apply_load_rules(34.9, 80_000), (MODERATE, None))
        self.assertEqual(apply_load_rules(10, 80_000), (LOW, None))


class CombinedAssessment(SimpleTestCase):
    def test_overall_is_worst_factor(self):
        r = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=0.6, load_lb=10_000)
        self.assertEqual((r.wind_level, r.rain_level, r.snow_level, r.level), (LOW, HIGH, MODERATE, HIGH))
        self.assertEqual(r.level_name, "High")

    def test_load_rule_drives_overall(self):
        r = assess(wind_mph=46, rain_in_hr=0, snow_in_hr=0, load_lb=35_000)
        self.assertEqual(r.level, NO_TRAVEL)
        self.assertIn("30,000", r.load_rule)

    def test_calm_weather_is_low(self):
        self.assertEqual(assess(0, 0, 0, 80_000).level, LOW)
