// Thin client for the Django API. Errors are surfaced with the server's message.

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

export function planTrip({ origin, destination, departure, loadWeight, interval }) {
  return post('/api/plan/', {
    origin,
    destination,
    departure,
    load_weight_lb: loadWeight,
    interval_miles: interval,
  })
}

export function corridorForecast({ cells, start, loadWeight }) {
  return post('/api/heatmap/', {
    cells: cells.map((c) => [c.lat, c.lon]),
    start,
    load_weight_lb: loadWeight,
  })
}
