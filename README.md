# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route based on
**weather, load weight and travel time**.

The driver enters origin, destination, departure date/time, load weight and a
checkpoint spacing (10 / 25 / 50 miles). The app:

1. gets **3 truck route options** from the TomTom Routing API,
2. places a **weather checkpoint every 10 / 25 / 50 miles** along each route and
   computes the truck's **estimated arrival time (ETA)** at each one,
3. reads the **hourly forecast at that ETA** (Open-Meteo) and classifies each checkpoint
   with the assessment's **risk table and load rules**,
4. **recommends** a route using the assessment's preference order
   (fewest Severe miles → fewest High miles → lowest average risk → shortest travel time),
5. shows all routes, checkpoints, risk levels, ETAs and route summaries **on a map**, and
6. shows a **weather heatmap along the trip corridor** with a **0–48 hour forecast slider**.

---

## Requirement → implementation map

| Assessment requirement | Where it lives |
| --- | --- |
| Inputs: origin & destination, departure date/time, load weight | `frontend/src/components/TripForm.jsx`, validated in `backend/planner/views.py` |
| 3 route options from a routing API | `planner/service.py::get_three_routes`, `planner/providers/tomtom.py` |
| Weather every 10 / 25 / 50 miles at the truck's ETA | `planner/geo.py` (sampling + ETA), `planner/providers/openmeteo.py` (`HourlySeries.at`) |
| Risk thresholds (wind / rain / snow) | `planner/risk.py` |
| Load rules | `planner/risk.py::apply_load_rules` |
| Recommendation (Severe → High → average risk → time) | `planner/recommend.py` |
| Routes, checkpoints, risk levels, ETAs, summaries on a map | `frontend/src/components/MapView.jsx`, `RouteCards.jsx` |
| Corridor weather heatmap with 0–48 h slider | `planner/heatmap.py`, `frontend/src/components/HeatmapControl.jsx`, `MapView.jsx` |

## Architecture

```
React (Vite, Leaflet)  ──POST /api/plan/────▶  Django ──▶ TomTom Search (geocode)
       │                                         │   └──▶ TomTom Routing (truck, 3 routes)
       └────────────POST /api/heatmap/───────▶  │   └──▶ Open-Meteo hourly forecast
```

* **One deployable service.** In production Django (via WhiteNoise) serves the built React
  app at `/` and the JSON API at `/api/`. No database is needed: the app is stateless.
* **`POST /api/plan/`** returns the 3 routes (simplified geometry), every checkpoint with
  ETA, weather values, per-factor and overall risk, route summaries, the recommendation and
  the heatmap grid cells.
* **`POST /api/heatmap/`** returns hours 0–48 of wind / rain / snow and the risk level for every
  corridor cell. It is loaded right after the plan, and the whole 49-hour block arrives at
  once, so the slider recolours the map instantly with no further network calls.
* **`GET /api/health/`** – liveness check used by the host.

### Third-party services

| Service | Used for | Key | Free tier (checked Oct 2026) |
| --- | --- | --- | --- |
| TomTom Routing + Search APIs | geocoding, truck routes with traffic-aware travel times and per-point travel time (`progress`) | **Required** (`TOMTOM_API_KEY`) | Freemium: 2,500 non-tile requests/day, no credit card, usage above the cap is blocked rather than billed |
| Open-Meteo forecast API | hourly wind (mph), rain + showers, snowfall | None | Non-commercial: 10,000 calls/day, 5,000/hour, 600/minute; each location in a multi-location request counts as one call |
| OpenStreetMap standard tiles | basemap | None | Free for light interactive use under the OSM tile usage policy; attribution shown on the map |

A single trip plan uses 2 geocoding calls + 1 routing call (+ up to 4 extra routing calls when
TomTom returns fewer than 3 alternatives).

## Run it locally (Windows, macOS or Linux)

Prerequisites: **Python 3.11+** and **Node.js 20+**.

1. Copy `.env.example` to `.env` (project root) and put your TomTom key in `TOMTOM_API_KEY`.
2. Backend (terminal 1):

   ```bash
   cd backend
   python -m venv .venv
   # Windows PowerShell:  .venv\Scripts\Activate.ps1      macOS/Linux:  source .venv/bin/activate
   pip install -r requirements.txt
   python manage.py runserver
   ```

3. Frontend (terminal 2):

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. Open http://localhost:5173 (Vite forwards `/api` calls to Django on port 8000).

To run it the way production does, run `npm run build` in `frontend`, then open
http://localhost:8000 – Django serves the built app.

## Tests

```bash
cd backend
python manage.py test planner -v 2
```

55 automated tests cover every risk-table boundary, all load rules, checkpoint spacing and
mileage coverage, ETA interpolation, unit conversion and hour selection of the forecast,
the recommendation order (each rule in isolation), input validation, and the full
`/api/plan/` and `/api/heatmap/` flows with TomTom and Open-Meteo replaced by deterministic
fakes at the HTTP layer. Manual browser checks are described in **[TESTING.md](TESTING.md)**.

## Deployment

The repository includes a `Dockerfile` (builds React, then runs Django with gunicorn) and a
`render.yaml` Blueprint for one free Render web service. Set `TOMTOM_API_KEY` in the host's
environment settings; `DJANGO_SECRET_KEY` is generated by Render. Health check: `/api/health/`.

## Assumptions (where the PDF is silent)

* **Band boundaries.** Lower bounds are inclusive (wind 35.0 mph → High; rain 0.25 in/hr → High;
  snow 1.0 in/hr → High). "No Travel" for rain and snow is strictly `> 1.00` and `> 3.0` as written,
  so exactly 1.00 in/hr rain / 3.0 in/hr snow is Severe. Wind bands are continuous (34.9 → Moderate).
  Load limits are strict (`> 30,000 lb`, `> 40,000 lb`).
* **Checkpoint risk** = the worst of wind (after load rules), rain and snow.
* **"Severe miles" / "High miles".** Checkpoints are placed at mile 0, every N miles, and at the
  destination. Each checkpoint represents the route stretch halfway to its neighbours, so the
  miles at each level add up exactly to the route length.
* **Average risk** = distance-weighted mean of checkpoint levels on a 0–4 scale
  (Low 0, Moderate 1, High 2, Severe 3, No Travel 4).
* **No Travel in the ranking.** The PDF's preference list does not mention No Travel. Because
  No Travel is worse than Severe, "fewest No Travel miles" is applied before "fewest Severe miles".
  When no route has No Travel miles (the usual case) the ranking is exactly the PDF's.
* **Weather at ETA.** Wind uses the nearest forecast hour. Rain/snow use the forecast for the hour
  that contains the ETA (Open-Meteo reports precipitation over the preceding hour). Rain = rain + showers.
  Values are converted from mm and cm to inches.
* **ETA.** Departure time + TomTom's traffic-aware travel time to that point (TomTom's per-point
  `progress` data, interpolated between points). Driver rest breaks are not modelled because the
  routing API does not include them.
* **Third route.** TomTom returns up to 2 alternatives. If it returns fewer than 3 distinct routes
  (common on short trips), extra routes are requested through an area offset to the side of the trip,
  and kept only if they are genuinely different and no more than 2× the length of the fastest route.
  The UI says when this happened.
* **Heatmap.** Shows the checkpoint risk level (same rules, including load) for grid cells within
  25 miles of any route, from the departure hour to +48 h. Grid spacing grows with trip length so
  the corridor uses at most 160 weather lookups.
* **Departure window.** Now (15-minute grace) up to 7 days ahead, which keeps the trip and the
  48-hour slider inside the forecast range. A departure in the past few minutes is treated as "now".
* **Units.** US units throughout (mph, in/hr, lb, miles), matching the PDF.

## Known limitations

* Weather is a forecast, sampled at points; conditions between checkpoints are not observed.
* Open-Meteo's free tier allows 600 location lookups per minute. Lookups are de-duplicated on a
  ~3-mile (0.05°) grid and cached for 15 minutes, but a very long trip at 10-mile spacing
  (e.g. coast to coast) can need several hundred lookups and may hit the per-minute limit if
  repeated quickly; the app then shows a clear "wait a minute and retry" message.
* Free hosting plans that sleep when idle (such as Render's free web services) make the first
  request after a quiet period slow while the service wakes up.
