import { useCallback, useRef, useState } from 'react'
import { corridorForecast, planTrip } from './api.js'
import TripForm from './components/TripForm.jsx'
import RouteCards from './components/RouteCards.jsx'
import MapView from './components/MapView.jsx'
import HeatmapControl from './components/HeatmapControl.jsx'

export default function App() {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [heatStatus, setHeatStatus] = useState('idle')
  const [heatError, setHeatError] = useState('')
  const [hour, setHour] = useState(0)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const requestId = useRef(0)

  const loadForecast = useCallback(async (p, id) => {
    setHeatStatus('loading')
    try {
      const f = await corridorForecast(p)
      if (requestId.current !== id) return
      setForecast(f)
      setHeatStatus('ready')
    } catch (err) {
      if (requestId.current !== id) return
      setHeatError(err.message)
      setHeatStatus('error')
    }
  }, [])

  async function handleSubmit(input) {
    const id = ++requestId.current
    setLoading(true)
    setError('')
    setPlan(null) // never show a previous trip's results next to a new search or its error
    setSelectedId(null)
    setForecast(null)
    setHeatStatus('idle')
    setHour(0)
    try {
      const p = await planTrip(input)
      if (requestId.current !== id) return
      setPlan(p)
      setSelectedId(p.recommendation.route_id)
      loadForecast(p, id)
    } catch (err) {
      if (requestId.current === id) setError(err.message)
    } finally {
      if (requestId.current === id) setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" /><path d="M7 20h12v-8h4l3 4v4h-2" /><circle cx="11" cy="22" r="2.4" /><circle cx="22" cy="22" r="2.4" /></svg>
          <h1>Weather-Aware Truck Routing</h1>
        </div>
        <p>Safest route by weather at each checkpoint's ETA, load weight and travel time</p>
      </header>
      <aside className="sidebar">
        <TripForm onSubmit={handleSubmit} loading={loading} />
        {error && <p className="error" role="alert">{error}</p>}
        {loading && <p className="hint">Fetching 3 truck routes and the forecast at every checkpoint…</p>}
        {plan && !loading && <RouteCards plan={plan} selectedId={selectedId} onSelect={setSelectedId} />}
        {!plan && !loading && !error && (
          <p className="hint">Enter a trip to compare three routes. Weather is sampled along each route at the time the truck is expected to arrive there.</p>
        )}
      </aside>
      <main className="map-area">
        <MapView plan={plan} selectedId={selectedId} onSelect={setSelectedId}
          forecast={forecast} hour={hour} showHeatmap={showHeatmap} />
        {plan && (
          <HeatmapControl status={heatStatus} error={heatError} forecast={forecast} hour={hour}
            setHour={setHour} show={showHeatmap} setShow={setShowHeatmap} />
        )}
      </main>
    </div>
  )
}
