# Testing guide

How to verify the app against every requirement in the assessment PDF.
Part A is automated (runs in seconds). Part B is manual and needs a browser, a real
TomTom key and internet access. Part C repeats the key checks on the hosted app.

Record each result as **Pass**, **Fail** or **Not run** in the table at the end.

---

## Part A — Automated tests

```bash
cd backend
python manage.py test planner -v 2
```

**Expected:** `Ran 57 tests ... OK`. **Evidence to keep:** the last 5 lines of the output.

| PDF requirement | Test file | What is checked |
| --- | --- | --- |
| Wind thresholds | `test_risk.py::WindThresholds` | 0, 24.9 → Low; 25, 34, 34.9 → Moderate; 35, 44, 44.9 → High; 45, 54, 54.9 → Severe; 55, 80 → No Travel |
| Rain thresholds | `test_risk.py::RainThresholds` | 0.099 → Low; 0.10 → Moderate; 0.25 → High; 0.50 and 1.00 → Severe; 1.001 → No Travel |
| Snow thresholds | `test_risk.py::SnowThresholds` | 0.49 → Low; 0.5 → Moderate; 1.0 → High; 2.0 and 3.0 → Severe; 3.01 → No Travel |
| Load rule: ≥55 mph → No Travel any load | `test_risk.py::LoadRules` | loads 0 / 10k / 30k / 80k at 55 mph |
| Load rule: 45–54 mph + >30,000 lb → No Travel | `test_risk.py::LoadRules` | 45, 50, 54, 54.9 mph at 30,001 lb → No Travel; 30,000 lb exactly → Severe |
| Load rule: 35–44 mph + >40,000 lb → Severe | `test_risk.py::LoadRules` | 35, 40, 44, 44.9 mph at 40,001 lb → Severe; 40,000 lb exactly → High; <35 mph unaffected |
| Checkpoint risk = worst factor | `test_risk.py::CombinedAssessment` | wind/rain/snow combined |
| Sample every 10/25/50 mi | `test_geo.py::CheckpointSpacing`, `test_api.py::test_sampling_interval_changes_checkpoint_count` | 0, N, 2N … + destination; mileage coverage sums to route length |
| ETA at each checkpoint | `test_geo.py::RouteProfileEta`, `test_api.py::test_eta_reflects_travel_time` | uses the routing API's per-point travel time; non-uniform speeds |
| Weather at ETA | `test_weather.py::ValueAtEta` | nearest hour for wind; hour containing the ETA for rain/snow; mm/cm → inches without boundary rounding errors |
| 3 route options | `test_api.py::test_routes_step_returns_three_routes...`, `test_fills_missing_alternatives...` | 3 routes; fallback when the API returns only 1 |
| Recommendation order | `test_recommend.py::Ranking` | each of the 4 rules decides on its own; No Travel never preferred |
| Heatmap 0–48 h | `test_api.py::HeatmapEndpoint` | 49 hourly levels per cell, load rule applied |
| Input validation | `test_api.py::test_validation_errors`, `test_plan_rejects_bad_weather_or_route_data`, `test_weather.py::BrowserQuery` | empty place, past/too-far departure, bad load, bad interval; malformed forecasts or route data posted by the browser |
| Weather fetched by the browser, not the server | `test_api.py` (every test) | the server's HTTP client fails the test if it ever calls Open-Meteo |

---

## Part B — Manual checks in the browser (local or hosted)

Use the same trip for B1–B8 unless told otherwise:
**Origin** `Denver, CO`, **Destination** `Salt Lake City, UT`, **Departure** about 1 hour from now,
**Load** `42000`, **Checkpoint every** `25 mi`. Click **Find safest route**.

| ID | PDF requirement | Action | Expected result | How to judge | Evidence |
| --- | --- | --- | --- | --- | --- |
| B1 | User enters origin, destination, departure, load | Look at the form | Four inputs plus the 10/25/50 mi selector | All present and editable | Screenshot of the form |
| B2 | 3 route options from a routing API | Submit the trip | Within ~15 s three cards "Route A/B/C" and three coloured lines on the map | Lines follow real roads; distances/times are plausible (Denver→SLC ≈ 520 mi, ≈ 8 h) | Full-page screenshot |
| B3 | Sample every 10 / 25 / 50 miles | Open "Show N checkpoints" on a card; repeat the trip with 10 mi and 50 mi | Mile column is 0, 25, 50 … and the last row equals the route distance. With 10 mi there are ~2.5× as many rows; with 50 mi about half | Count of rows ≈ distance ÷ interval + 2 | Screenshot of the table for 10 and 50 |
| B4 | Weather at the truck's ETA | In the table, check ETA of mile 0 and the last row | Mile 0 = departure time; last ETA = card's "Arrive" time; ETAs increase down the table | Compare with the card | Screenshot |
| B5 | Weather values are real | Click a checkpoint dot on the map; note the lat/lon and ETA shown in the popup | Values in the popup match Open-Meteo for that place and hour | Open `https://api.open-meteo.com/v1/forecast?latitude=LAT&longitude=LON&hourly=wind_speed_10m,rain,showers,snowfall&wind_speed_unit=mph&timezone=GMT` and compare the hour (times in that JSON are UTC; wind = nearest hour, rain/snow = the hour that ends just after the ETA; rain + showers in mm ÷ 25.4; snowfall in cm ÷ 2.54). Small differences come from the ~3-mile location grid | Popup screenshot + the matching JSON hour |
| B6 | Risk rules | In the same popup, check each factor's level against the PDF table | Each chip matches the table; the overall level is the worst of the three | Use the table in the PDF | Same screenshot |
| B7 | Load rules | Re-run the same trip with load `30000`, then `45000` | Only checkpoints with wind ≥ 35 mph change: at 45,000 lb, 35–44 mph becomes **Severe** and 45–54 mph becomes **No Travel** (popup says "Load rule applied"). If no checkpoint has wind ≥ 35 mph today, results are identical — this is correct; the rule is covered by Part A | Compare cards/popups between runs | Two screenshots |
| B8 | Recommendation | Read the three cards | The "Recommended" card is #1. Compare cards in order: Severe miles, then High miles, then Avg risk, then Drive time — the first one that differs decides | The reason sentence names the deciding rule and the numbers | Screenshot of the cards |
| B9 | Show routes, checkpoints, risk levels, ETAs and summaries on a map | Click a route line; click a checkpoint dot; click a card | Route popup: distance, time, arrival, miles per level, average risk. Checkpoint popup: mile, ETA, wind/rain/snow with levels, overall risk. Clicking a card highlights that route | Everything visible on the map | Two popup screenshots |
| B10 | Weather heatmap along the corridor | Look at the shaded cells around the routes | Cells cover a band around all three routes, coloured by risk (legend shown) | Hover a cell: tooltip shows level and wind/rain/snow | Screenshot with tooltip |
| B11 | 0–48 h forecast slider | Drag the slider from 0 to 48 | Label shows +0 h … +48 h with the date/time; cell colours change immediately with no loading | Smooth, no lag or flicker | Short screen recording or two screenshots (0 h and 48 h) |
| B12 | Error handling | Destination `qwertyuiopasdf`; then departure in the past; then load `-1` | Clear red message, no crash | Message explains the problem | Screenshot |
| B13 | Short trip still gives 3 routes | Origin `Dallas, TX`, Destination `Fort Worth, TX` | Three routes; possibly a yellow note saying extra routes were generated | 3 cards | Screenshot |
| B14 | Phone layout | Open the app on a phone (or browser dev-tools phone view) | Map on top, form and cards below, slider usable | Nothing cut off | Screenshot |

## Part C — Hosted application

Repeat **B2, B5, B9, B10 and B11** on the public URL, in a private/incognito window (proves no
login or local state is needed). Also open `https://<your-app>/api/health/` — expected `{"status": "ok"}`.

---

## Results record

| ID | Result (Pass / Fail / Not run) | Notes / evidence |
| --- | --- | --- |
| Part A | | |
| B1 | | |
| B2 | | |
| B3 | | |
| B4 | | |
| B5 | | |
| B6 | | |
| B7 | | |
| B8 | | |
| B9 | | |
| B10 | | |
| B11 | | |
| B12 | | |
| B13 | | |
| B14 | | |
| Part C | | |
