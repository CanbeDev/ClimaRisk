// Semantic accent tokens — mirror the CSS custom properties in index.css so JS
// (recharts, Leaflet path options, inline styles) can reference the same values.
// Orange is the primary brand; the rest are re-mapped so nothing clashes with it.
export const ACCENT = {
  brand: '#ff6a2b', // exposure / TIV — primary
  pml: '#e0454a', // loss / PML / basis-risk underpay
  gap: '#9a6b1e', // protection gap — muted gold, distinct from brand
  over: '#cd7a12', // basis-risk overpay — amber
  ok: '#157f43', // active / healthy — emerald for white bg
  ink: '#211d18',
  muted: '#6b6258',
  faint: '#8c8278',
  hair: '#e7e0d7',
  surface: '#ffffff',
}

// GDACS event_type -> color. A categorical set spread across the wheel and
// held clear of the semantic accents above — in particular WF is a dark
// burnt-rust (NOT pml's bright rose-red) and DR is a bright lemon (NOT gap's
// muted olive-gold), so a hazard dot on the map never reads like a loss figure.
export const HAZARD_COLORS = {
  FL: { stroke: '#2563eb', fill: '#2563eb', label: 'Flood' }, // blue
  TC: { stroke: '#7c3aed', fill: '#7c3aed', label: 'Cyclone' }, // violet
  EQ: { stroke: '#0f766e', fill: '#0f766e', label: 'Earthquake' }, // teal
  VO: { stroke: '#db2777', fill: '#db2777', label: 'Volcano' }, // magenta
  WF: { stroke: '#7c2d12', fill: '#7c2d12', label: 'Wildfire' }, // burnt rust
  DR: { stroke: '#eab308', fill: '#eab308', label: 'Drought' }, // bright yellow
}

export const DEFAULT_HAZARD_COLOR = { stroke: '#78716c', fill: '#78716c', label: 'Other' }

export function getHazardColor(eventType) {
  return HAZARD_COLORS[eventType] || DEFAULT_HAZARD_COLOR
}

// GDACS alert level -> color (traffic-light scale), tuned for a light background.
export const ALERT_COLORS = {
  Red: '#dc2626',
  Orange: '#d97706',
  Green: '#16a34a',
}
export const DEFAULT_ALERT_COLOR = '#78716c'

export function getAlertColor(level) {
  return ALERT_COLORS[level] || DEFAULT_ALERT_COLOR
}

// Asset marker by Total Insured Value tier. A warm-grey → near-black ramp
// (darker = more valuable): a monochrome scale reads as "magnitude", stays
// visible on the light basemap, and never collides with the categorical hazard
// hues or the semantic accents. Each tier also has a distinct shape + size, so
// an exposed asset inside a selected footprint reads as a surveyed node, not a
// dot — see MapPanel's <Marker> / divIcon rendering.
const TIV_TIERS = [
  { min: 10_000_000, color: '#1b1712', shape: 'diamond', size: 17, label: 'Critical (R10M+)' },
  { min: 5_000_000, color: '#57534e', shape: 'square', size: 14, label: 'High (R5M–10M)' },
  { min: 1_000_000, color: '#8a827a', shape: 'circle', size: 12, label: 'Medium (R1M–5M)' },
  { min: 0, color: '#b7afa4', shape: 'circle', size: 10, label: 'Low (<R1M)' },
]

export function getAssetTier(totalInsuredValue) {
  const tiv = totalInsuredValue ?? 0
  return TIV_TIERS.find((tier) => tiv >= tier.min)
}

export function getAssetColor(totalInsuredValue) {
  return getAssetTier(totalInsuredValue).color
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
