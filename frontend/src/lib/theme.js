// GDACS event_type -> color, matching the codes used throughout the backend
// (app/config.py's GDACS_EVENT_TYPES: EQ;TC;FL;VO;WF;DR).
export const HAZARD_COLORS = {
  FL: { stroke: '#22d3ee', fill: '#22d3ee', label: 'Flood' }, // cyan
  TC: { stroke: '#f59e0b', fill: '#f59e0b', label: 'Cyclone' }, // amber
  EQ: { stroke: '#f43f5e', fill: '#f43f5e', label: 'Earthquake' }, // rose
  VO: { stroke: '#fb923c', fill: '#fb923c', label: 'Volcano' }, // orange
  WF: { stroke: '#ef4444', fill: '#ef4444', label: 'Wildfire' }, // red
  DR: { stroke: '#eab308', fill: '#eab308', label: 'Drought' }, // yellow
}

export const DEFAULT_HAZARD_COLOR = { stroke: '#94a3b8', fill: '#94a3b8', label: 'Other' }

export function getHazardColor(eventType) {
  return HAZARD_COLORS[eventType] || DEFAULT_HAZARD_COLOR
}

// GDACS alert level -> color, reused for the trend view's alert-level chart and
// any alert badges. Matches the rose/amber/emerald already used for alert
// styling in ExposurePanel, kept here so the trend charts don't re-invent it.
export const ALERT_COLORS = {
  Red: '#f43f5e',
  Orange: '#f59e0b',
  Green: '#22c55e',
}
export const DEFAULT_ALERT_COLOR = '#64748b'

export function getAlertColor(level) {
  return ALERT_COLORS[level] || DEFAULT_ALERT_COLOR
}

// Asset marker color by Total Insured Value tier. Deliberately a distinct
// violet/indigo ramp — not reusing any HAZARD_COLORS hue — so hazard
// polygons and asset markers never collide on color alone, only on shape.
const TIV_TIERS = [
  { min: 10_000_000, color: '#d946ef', label: 'Critical (R10M+)' }, // fuchsia
  { min: 5_000_000, color: '#8b5cf6', label: 'High (R5M–10M)' }, // violet
  { min: 1_000_000, color: '#6366f1', label: 'Medium (R1M–5M)' }, // indigo
  { min: 0, color: '#64748b', label: 'Low (<R1M)' }, // slate
]

export function getAssetColor(totalInsuredValue) {
  const tiv = totalInsuredValue ?? 0
  return TIV_TIERS.find((tier) => tiv >= tier.min).color
}

export const ASSET_TIV_LEGEND = TIV_TIERS

export const currency = (value) => {
  if (value == null) return '—'
  return value.toLocaleString('en-ZA', {
    style: 'currency',
    currency: 'ZAR',
    maximumFractionDigits: 0,
  })
}

export const percent = (value) => {
  if (value == null) return '—'
  return value.toLocaleString('en-ZA', {
    style: 'percent',
    maximumFractionDigits: 0,
  })
}
