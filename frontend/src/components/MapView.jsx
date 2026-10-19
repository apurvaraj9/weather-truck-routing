import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { LEVELS, LEVEL_COLORS, escapeHtml, fmtDuration, fmtMiles, fmtTimeLong, routeColor } from '../format.js'

// Leaflet is driven imperatively (layers are created once per plan and restyled in place),
// which keeps slider scrubbing and route selection smooth even with hundreds of shapes.

// OpenStreetMap standard tiles: free, no key, attribution required (tile usage policy:
// https://operations.osmfoundation.org/policies/tiles/).
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

function checkpointPopup(route, c) {
  const row = (label, value, level) =>
    `<tr><th>${label}</th><td>${value}</td><td><span class="chip lvl-${LEVELS.indexOf(level)}">${level}</span></td></tr>`
  return `
    <div class="popup">
      <strong>${escapeHtml(route.id)} · mile ${c.mile}</strong>
      <div class="popup-sub">ETA ${escapeHtml(fmtTimeLong(c.eta))}<br>${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}</div>
      <table>
        ${row('Wind', `${c.wind_mph} mph`, c.wind_level)}
        ${row('Rain', `${c.rain_in_hr.toFixed(2)} in/hr`, c.rain_level)}
        ${row('Snow', `${c.snow_in_hr.toFixed(2)} in/hr`, c.snow_level)}
      </table>
      <div class="popup-risk">Checkpoint risk: <span class="chip lvl-${c.level}">${c.level_name}</span></div>
      ${c.load_rule ? `<div class="popup-note">Load rule applied: ${escapeHtml(c.load_rule)}</div>` : ''}
    </div>`
}

function routePopup(route) {
  const s = route.summary
  const levels = LEVELS.map((n) => `<li>${n}: <b>${fmtMiles(s.miles_by_level[n])}</b></li>`).join('')
  return `
    <div class="popup">
      <strong>${escapeHtml(route.id)}${route.recommended ? ' · Recommended' : ''}</strong>
      <div class="popup-sub">${fmtMiles(s.distance_miles)} · ${fmtDuration(s.duration_seconds)} · arrive ${escapeHtml(fmtTimeLong(s.arrival))}</div>
      <ul class="popup-levels">${levels}</ul>
      <div>Average risk ${s.average_risk.toFixed(2)} / 4 · worst ${s.max_level_name}</div>
    </div>`
}

function endpointIcon(label, cls) {
  return L.divIcon({ className: `endpoint ${cls}`, html: `<span>${label}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] })
}

export default function MapView({ plan, selectedId, onSelect, forecast, hour, showHeatmap }) {
  const el = useRef(null)
  const map = useRef(null)
  const layers = useRef({ routes: [], checkpoints: [], cells: [], other: [] })
  const forecastRef = useRef({ forecast, hour })
  forecastRef.current = { forecast, hour }

  // Create the map once.
  useEffect(() => {
    const m = L.map(el.current, { preferCanvas: true, zoomControl: false }).setView([39.5, -98.35], 4)
    L.control.zoom({ position: 'topright' }).addTo(m)
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(m)
    map.current = m
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      m.remove()
    }
  }, [])

  // Draw everything for a new plan.
  useEffect(() => {
    const m = map.current
    const store = layers.current
    Object.values(store).flat().forEach((l) => l.remove())
    store.routes = []
    store.checkpoints = []
    store.cells = []
    store.other = []
    if (!plan) return

    // One shared canvas: Leaflet only hit-tests the top-most canvas element, so separate
    // canvases would block clicks/hover on lower layers. Draw order = add order.
    const renderer = L.canvas({ tolerance: 5 })

    plan.heatmap_grid.cells.forEach((c, i) => {
      const rect = L.rectangle(
        [[c.lat - c.dlat / 2, c.lon - c.dlon / 2], [c.lat + c.dlat / 2, c.lon + c.dlon / 2]],
        { renderer, stroke: false, fillOpacity: 0, interactive: true },
      )
      rect.bindTooltip(() => {
        const { forecast: f, hour: h } = forecastRef.current
        const cell = f?.cells?.[i]
        if (!cell) return 'Forecast loading…'
        const lvl = cell.level[h]
        return `<b>${LEVELS[lvl]}</b> · +${h} h<br>Wind ${cell.wind[h]} mph · Rain ${cell.rain[h].toFixed(2)} in/hr · Snow ${cell.snow[h].toFixed(2)} in/hr`
      }, { sticky: true, direction: 'top', opacity: 0.95 })
      rect.addTo(m)
      store.cells.push(rect)
    })

    plan.routes.forEach((route, i) => {
      const casing = L.polyline(route.geometry, { renderer, color: '#fff', weight: 9, opacity: 0.9, interactive: false })
      const line = L.polyline(route.geometry, { renderer, color: routeColor(i), weight: 5, opacity: 0.95 })
      line.bindPopup(routePopup(route), { maxWidth: 280 })
      line.on('click', () => onSelect(route.id))
      casing.addTo(m)
      line.addTo(m)
      store.routes.push({ id: route.id, casing, line })
    })

    plan.routes.forEach((route, i) => {
      route.checkpoints.forEach((c) => {
        const marker = L.circleMarker([c.lat, c.lon], {
          renderer, radius: 5, weight: 2,
          color: routeColor(i), fillColor: LEVEL_COLORS[c.level], fillOpacity: 1,
        })
        marker.bindPopup(checkpointPopup(route, c), { maxWidth: 280 })
        marker.on('click', () => onSelect(route.id))
        marker.routeId = route.id
        marker.addTo(m)
        store.checkpoints.push(marker)
      })
    })

    store.other.push(
      L.marker([plan.origin.lat, plan.origin.lon], { icon: endpointIcon('A', 'origin'), title: plan.origin.label, zIndexOffset: 1000 }).addTo(m),
      L.marker([plan.destination.lat, plan.destination.lon], { icon: endpointIcon('B', 'destination'), title: plan.destination.label, zIndexOffset: 1000 }).addTo(m),
    )
    const bounds = L.latLngBounds(plan.routes.flatMap((r) => r.geometry))
    m.fitBounds(bounds, { padding: [40, 40] })
  }, [plan, onSelect])

  // Emphasise the selected route.
  useEffect(() => {
    const store = layers.current
    store.routes.forEach(({ id, casing, line }) => {
      const sel = id === selectedId
      line.setStyle({ weight: sel ? 7 : 4, opacity: sel ? 1 : 0.45 })
      casing.setStyle({ weight: sel ? 11 : 7, opacity: sel ? 0.95 : 0.5 })
    })
    store.routes.filter((r) => r.id === selectedId).forEach(({ casing, line }) => {
      casing.bringToFront()
      line.bringToFront()
    })
    // Checkpoints stay above every line; the selected route's checkpoints on top.
    store.checkpoints.forEach((mk) => {
      const sel = mk.routeId === selectedId
      mk.setStyle({ radius: sel ? 6.5 : 4, opacity: sel ? 1 : 0.55, fillOpacity: sel ? 1 : 0.6 })
      if (!sel) mk.bringToFront()
    })
    store.checkpoints.forEach((mk) => mk.routeId === selectedId && mk.bringToFront())
  }, [selectedId, plan])

  // Recolour the heatmap for the selected forecast hour.
  useEffect(() => {
    const cells = layers.current.cells
    cells.forEach((rect, i) => {
      const lvl = forecast?.cells?.[i]?.level?.[hour]
      if (!showHeatmap || lvl === undefined) {
        rect.setStyle({ fillOpacity: 0 })
      } else {
        rect.setStyle({ fillColor: LEVEL_COLORS[lvl], fillOpacity: lvl === 0 ? 0.14 : 0.42 })
      }
    })
  }, [forecast, hour, showHeatmap, plan])

  return <div ref={el} className="map" role="region" aria-label="Route map" />
}
