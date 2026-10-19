// Client for the Django API.
//
// Forecasts are fetched by the browser, not the server: Open-Meteo's free tier is
// limited per IP address, and free hosting platforms share a few IP addresses between
// many apps. The server describes the exact Open-Meteo request (points, hours,
// variables, units); this file sends it and posts the raw results back. All weather
// interpretation, risk rules and the recommendation stay on the server.

async function post(path, body) {
  let res
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.')
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    throw new Error(data?.error || `Server error (HTTP ${res.status}).`)
  }
  return data
}

async function fetchForecastBatch(url, params, batch) {
  const qs = new URLSearchParams({
    ...params,
    latitude: batch.map((p) => p[0]).join(','),
    longitude: batch.map((p) => p[1]).join(','),
  })
  let res
  try {
    res = await fetch(`${url}?${qs}`)
  } catch {
    throw new Error('Could not reach the weather service (Open-Meteo). Check your connection and try again.')
  }
  if (res.status === 429) {
    throw new Error('The free weather service (Open-Meteo) limit was reached for your network. Please wait a minute and try again.')
  }
  if (!res.ok) {
    throw new Error(`The weather service (Open-Meteo) returned an error (HTTP ${res.status}). Please try again.`)
  }
  const data = await res.json()
  const items = Array.isArray(data) ? data : [data]
  if (items.length !== batch.length) throw new Error('The weather service returned incomplete data. Please try again.')
  return items.map((item) => item.hourly)
}

// Sends the server-described Open-Meteo request; returns one raw `hourly` block per point, in order.
export async function fetchForecasts({ url, params, points, batch_size: size }) {
  const batches = []
  for (let i = 0; i < points.length; i += size) batches.push(points.slice(i, i + size))
  const results = await Promise.all(batches.map((b) => fetchForecastBatch(url, params, b)))
  return results.flat()
}

export async function planTrip({ origin, destination, departure, loadWeight, interval }) {
  // 1. Routes, checkpoints and ETAs (server, TomTom)
  const trip = await post('/api/routes/', {
    origin,
    destination,
    departure,
    load_weight_lb: loadWeight,
    interval_miles: interval,
  })
  // 2. Forecasts for every checkpoint (browser, Open-Meteo)
  const weather = await fetchForecasts(trip.weather_query)
  // 3. Weather at each ETA, risk levels, summaries and recommendation (server)
  const scored = await post('/api/plan/', {
    departure: trip.departure,
    load_weight_lb: trip.load_weight_lb,
    routes: trip.routes.map(({ geometry, ...rest }) => rest),
    weather,
  })
  const geometry = Object.fromEntries(trip.routes.map((r) => [r.id, r.geometry]))
  return {
    ...trip,
    routes: scored.routes.map((r) => ({ ...r, geometry: geometry[r.id] })),
    recommendation: scored.recommendation,
    notices: [...trip.notices, ...scored.notices],
  }
}

export async function corridorForecast(plan) {
  const q = plan.heatmap_query
  const weather = await fetchForecasts(q)
  return post('/api/heatmap/', {
    start: q.start,
    load_weight_lb: plan.load_weight_lb,
    cell_point: q.cell_point,
    weather,
  })
}
