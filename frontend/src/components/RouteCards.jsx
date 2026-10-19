import { useState } from 'react'
import { LEVELS, LEVEL_COLORS, fmtDuration, fmtMiles, fmtTime, fmtTimeLong, routeColor } from '../format.js'

function RiskBar({ milesByLevel, total }) {
  return (
    <div className="risk-bar" aria-label="Miles by risk level">
      {LEVELS.map((name, i) => {
        const mi = milesByLevel[name] || 0
        if (!mi) return null
        return <span key={name} style={{ width: `${(mi / total) * 100}%`, background: LEVEL_COLORS[i] }}
          title={`${name}: ${fmtMiles(mi)}`} />
      })}
    </div>
  )
}

function LevelChip({ level, name }) {
  return <span className={`chip lvl-${level}`}>{name}</span>
}

function CheckpointTable({ checkpoints }) {
  return (
    <div className="cp-table-wrap">
      <table className="cp-table">
        <thead>
          <tr><th>Mile</th><th>ETA</th><th>Wind</th><th>Rain</th><th>Snow</th><th>Risk</th></tr>
        </thead>
        <tbody>
          {checkpoints.map((c) => (
            <tr key={c.index}>
              <td>{c.mile}</td>
              <td>{fmtTime(c.eta)}</td>
              <td>{c.wind_mph} mph</td>
              <td>{c.rain_in_hr.toFixed(2)}″</td>
              <td>{c.snow_in_hr.toFixed(2)}″</td>
              <td><LevelChip level={c.level} name={c.level_name} />{c.load_rule && <span className="load-flag" title={c.load_rule}>⚖</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RouteCard({ route, index, selected, onSelect }) {
  const [open, setOpen] = useState(false)
  const s = route.summary
  return (
    <article className={`route-card${selected ? ' selected' : ''}${route.recommended ? ' recommended' : ''}`}
      style={{ '--route': routeColor(index) }}>
      <button type="button" className="route-card-main" onClick={() => onSelect(route.id)} aria-pressed={selected}>
        <header>
          <span className="route-swatch" />
          <h3>{route.id}</h3>
          {route.recommended && <span className="badge">Recommended</span>}
          <span className="rank">#{route.rank}</span>
        </header>
        <dl className="stats">
          <div><dt>Distance</dt><dd>{fmtMiles(s.distance_miles)}</dd></div>
          <div><dt>Drive time</dt><dd>{fmtDuration(s.duration_seconds)}</dd></div>
          <div><dt>Arrive</dt><dd>{fmtTime(s.arrival)}</dd></div>
          <div><dt>Avg risk</dt><dd>{s.average_risk.toFixed(2)} <small>/ 4</small></dd></div>
        </dl>
        <RiskBar milesByLevel={s.miles_by_level} total={s.distance_miles || 1} />
        <ul className="level-miles">
          {LEVELS.map((name, i) => (
            <li key={name} className={s.miles_by_level[name] ? '' : 'zero'}>
              <i style={{ background: LEVEL_COLORS[i] }} />{name} <b>{fmtMiles(s.miles_by_level[name])}</b>
            </li>
          ))}
        </ul>
      </button>
      <button type="button" className="link" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? 'Hide' : 'Show'} {s.checkpoint_count} checkpoints
      </button>
      {open && <CheckpointTable checkpoints={route.checkpoints} />}
    </article>
  )
}

export default function RouteCards({ plan, selectedId, onSelect }) {
  const rec = plan.routes.find((r) => r.recommended)
  return (
    <section className="results">
      <div className="recommendation">
        <p className="eyebrow">Recommended</p>
        <h2>{rec.id} · {fmtMiles(rec.summary.distance_miles)} · {fmtDuration(rec.summary.duration_seconds)}</h2>
        <p>{plan.recommendation.reason}</p>
        <p className="meta">
          {plan.origin.label} → {plan.destination.label}<br />
          Departs {fmtTimeLong(plan.departure)} · {Number(plan.load_weight_lb).toLocaleString()} lb · checkpoint every {plan.interval_miles} mi
        </p>
      </div>
      {plan.notices.map((n) => <p key={n} className="notice">{n}</p>)}
      <p className="rules-note">Ranked by: fewest Severe miles → fewest High miles → lowest average risk → shortest travel time.</p>
      {plan.routes.map((r, i) => (
        <RouteCard key={r.id} route={r} index={i} selected={r.id === selectedId} onSelect={onSelect} />
      ))}
    </section>
  )
}
