import { LEVELS, LEVEL_COLORS, fmtTimeLong } from '../format.js'

export function Legend() {
  return (
    <div className="legend" aria-label="Risk legend">
      {LEVELS.map((name, i) => (
        <span key={name}><i style={{ background: LEVEL_COLORS[i] }} />{name}</span>
      ))}
    </div>
  )
}

export default function HeatmapControl({ status, error, forecast, hour, setHour, show, setShow }) {
  const maxHour = forecast?.hours ?? 48
  const at = forecast ? new Date(new Date(forecast.start).getTime() + hour * 3600 * 1000).toISOString() : null
  return (
    <div className="heat-control">
      <div className="heat-head">
        <label className="toggle">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          Weather heatmap
        </label>
        <span className="heat-time">
          {status === 'loading' && 'Loading corridor forecast…'}
          {status === 'error' && <span className="error-text">{error}</span>}
          {status === 'ready' && <>+{hour} h · {fmtTimeLong(at)}</>}
        </span>
      </div>
      <input
        type="range"
        min="0"
        max={maxHour}
        step="1"
        value={hour}
        disabled={status !== 'ready' || !show}
        onChange={(e) => setHour(Number(e.target.value))}
        aria-label="Forecast hour after departure"
      />
      <div className="heat-scale"><span>Departure (0 h)</span><span>24 h</span><span>48 h</span></div>
      <Legend />
    </div>
  )
}
