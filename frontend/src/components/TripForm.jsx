import { useState } from 'react'

const pad = (n) => String(n).padStart(2, '0')
const toLocalInput = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`

function defaultDeparture() {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0)
  return toLocalInput(d)
}

const INTERVALS = [10, 25, 50]

export default function TripForm({ onSubmit, loading }) {
  const [origin, setOrigin] = useState('Denver, CO')
  const [destination, setDestination] = useState('Salt Lake City, UT')
  const [departure, setDeparture] = useState(defaultDeparture)
  const [loadWeight, setLoadWeight] = useState('42000')
  const [interval, setSampleInterval] = useState(25)

  const now = new Date()
  const max = new Date(now.getTime() + 7 * 24 * 3600 * 1000)

  function submit(e) {
    e.preventDefault()
    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      departure: new Date(departure).toISOString(),
      loadWeight: Number(loadWeight),
      interval,
    })
  }

  return (
    <form className="trip-form" onSubmit={submit}>
      <label className="field">
        <span>Origin</span>
        <input value={origin} onChange={(e) => setOrigin(e.target.value)} required maxLength={200}
          placeholder="City, address or lat,lon" autoComplete="off" />
      </label>
      <label className="field">
        <span>Destination</span>
        <input value={destination} onChange={(e) => setDestination(e.target.value)} required maxLength={200}
          placeholder="City, address or lat,lon" autoComplete="off" />
      </label>
      <div className="field-row">
        <label className="field">
          <span>Departure</span>
          <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} required
            min={toLocalInput(new Date(now.getTime() - 10 * 60 * 1000))} max={toLocalInput(max)} />
        </label>
        <label className="field">
          <span>Load weight (lb)</span>
          <input type="number" inputMode="numeric" min="0" max="200000" step="1" value={loadWeight}
            onChange={(e) => setLoadWeight(e.target.value)} required />
        </label>
      </div>
      <fieldset className="field">
        <legend>Weather checkpoint every</legend>
        <div className="segmented" role="radiogroup">
          {INTERVALS.map((mi) => (
            <button type="button" key={mi} role="radio" aria-checked={interval === mi}
              className={interval === mi ? 'active' : ''} onClick={() => setSampleInterval(mi)}>
              {mi} mi
            </button>
          ))}
        </div>
      </fieldset>
      <button className="primary" type="submit" disabled={loading}>
        {loading ? 'Planning routes…' : 'Find safest route'}
      </button>
    </form>
  )
}
