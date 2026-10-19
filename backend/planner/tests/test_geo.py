"""Checkpoint sampling, mileage coverage, ETA interpolation and geometry helpers."""
from django.test import SimpleTestCase

from planner.geo import (RouteProfile, checkpoint_miles, coverage, cumulative_mi, haversine_mi,
                         offset_point, overlap_fraction, sample_checkpoints, simplify)


def straight_line(n=101, lat=35.0, lon0=-100.0, lon1=-99.0):
    return [(lat, lon0 + (lon1 - lon0) * i / (n - 1)) for i in range(n)]


class CheckpointSpacing(SimpleTestCase):
    def test_every_interval_plus_destination(self):
        self.assertEqual(checkpoint_miles(100, 25), [0, 25, 50, 75, 100])
        self.assertEqual(checkpoint_miles(105, 25), [0, 25, 50, 75, 100, 105])
        self.assertEqual(checkpoint_miles(105, 50), [0, 50, 100, 105])
        self.assertEqual(checkpoint_miles(32, 10), [0, 10, 20, 30, 32])

    def test_short_route_has_origin_and_destination(self):
        self.assertEqual(checkpoint_miles(7, 10), [0, 7])

    def test_no_near_duplicate_at_destination(self):
        self.assertEqual(checkpoint_miles(100.02, 25), [0, 25, 50, 75, 100.02])

    def test_coverage_sums_to_route_length(self):
        for total, step in [(100, 25), (105, 50), (32, 10), (7, 10), (1234.5, 10)]:
            miles = checkpoint_miles(total, step)
            self.assertAlmostEqual(sum(coverage(miles)), total, places=6)

    def test_coverage_is_half_way_to_neighbours(self):
        self.assertEqual(coverage([0, 10, 20, 25]), [5, 10, 7.5, 2.5])


class RouteProfileEta(SimpleTestCase):
    def test_linear_without_anchors(self):
        pts = straight_line()
        prof = RouteProfile(pts, total_miles=60, total_seconds=3600)
        self.assertAlmostEqual(prof.seconds_at(30), 1800)
        self.assertAlmostEqual(prof.seconds_at(60), 3600)
        self.assertEqual(prof.position_at(0), pts[0])
        self.assertEqual(prof.position_at(60), pts[-1])

    def test_uses_provider_progress_anchors(self):
        # First half of the route is slow (city), second half fast (highway):
        # 30 mi in 3600 s, then 30 mi in 1800 s.
        pts = straight_line()
        prof = RouteProfile(pts, 60, 5400, anchors=[(50, 30.0, 3600.0)])
        self.assertAlmostEqual(prof.seconds_at(15), 1800)
        self.assertAlmostEqual(prof.seconds_at(30), 3600)
        self.assertAlmostEqual(prof.seconds_at(45), 4500)
        lat, lon = prof.position_at(30)
        self.assertAlmostEqual(lon, pts[50][1], places=6)

    def test_sample_checkpoints_have_eta_and_coverage(self):
        pts = straight_line()
        prof = RouteProfile(pts, 60, 3600)
        cps = sample_checkpoints(prof, 25)
        self.assertEqual([c.mile for c in cps], [0, 25, 50, 60])
        self.assertEqual([round(c.seconds) for c in cps], [0, 1500, 3000, 3600])
        self.assertAlmostEqual(sum(c.covered_miles for c in cps), 60)


class GeometryHelpers(SimpleTestCase):
    def test_haversine_one_degree_latitude(self):
        self.assertAlmostEqual(haversine_mi((0, 0), (1, 0)), 69.09, places=1)

    def test_simplify_keeps_ends_and_drops_collinear(self):
        pts = straight_line(1000)
        out = simplify(pts)
        self.assertEqual(out, [pts[0], pts[-1]])
        bent = pts[:500] + [(35.5, pts[500][1])] + pts[501:]
        self.assertIn((35.5, pts[500][1]), simplify(bent))

    def test_overlap(self):
        a = straight_line()
        b = [(lat + 1.0, lon) for lat, lon in a]  # ~69 miles north
        self.assertEqual(overlap_fraction(a, a), 1.0)
        self.assertEqual(overlap_fraction(a, b), 0.0)

    def test_offset_point_is_perpendicular_to_the_side(self):
        a, b = (35.0, -100.0), (35.0, -99.0)  # due east
        north = offset_point(a, b, 0.2)
        south = offset_point(a, b, -0.2)
        self.assertGreater(north[0], 35.0)
        self.assertLess(south[0], 35.0)
        self.assertAlmostEqual(north[1], -99.5, places=6)
        dist = haversine_mi(a, b)
        self.assertAlmostEqual(haversine_mi((35.0, -99.5), north), 0.2 * dist, delta=0.5)

    def test_cumulative(self):
        cum = cumulative_mi(straight_line(11))
        self.assertEqual(cum[0], 0)
        self.assertEqual(len(cum), 11)
        self.assertTrue(all(b > a for a, b in zip(cum, cum[1:])))
