// Shared risk colours and display formatting.

export const LEVELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']
export const LEVEL_COLORS = ['#2f9e5a', '#e3b505', '#f0802a', '#d93636', '#5b1a6e']
export const ROUTE_COLORS = ['#2563eb', '#7c3aed', '#0e7490']

export const routeColor = (index) => ROUTE_COLORS[index % ROUTE_COLORS.length]

const timeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
})
const timeFmtTz = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

export const fmtTime = (iso) => timeFmt.format(new Date(iso))
export const fmtTimeLong = (iso) => timeFmtTz.format(new Date(iso))

export function fmtDuration(seconds) {
  const mins = Math.round(seconds / 60)
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`
}

export const fmtMiles = (mi) => `${Number(mi).toLocaleString(undefined, { maximumFractionDigits: 1 })} mi`

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}
