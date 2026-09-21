import { useEffect, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { AlertTriangle, Globe as GlobeIcon, X } from 'lucide-react'
import { ACCENT, getAlert, getHazardColor, HAZARD_COLORS } from '../lib/theme'
import { SkeletonCards, SkeletonChart } from './Skeleton'

// Alert level -> point size (world radius units). Red events read as visibly
// larger on the globe, matching the alert badge's semantic weight elsewhere.
const ALERT_POINT_SIZE = { Red: 0.55, Orange: 0.42, Green: 0.32 }
const DEFAULT_POINT_SIZE = 0.32

// GDACS gives a footprint polygon only for the country-scoped subset that's
// had polygon enrichment run (see docs/architecture.md, "Polygon enrichment
// stays country-scoped") — every other worldwide event is a bare Point. This
// resolves either shape to one [lat, lng] pair: the coordinate directly for a
// Point, a cheap vertex-average of the first ring for a Polygon/MultiPolygon
// (a marker position, not a financial computation — no need for a true
// area centroid here).
function pointFromGeometry(geometry) {
  if (!geometry) return null
  if (geometry.type === 'Point') {
    const [lng, lat] = geometry.coordinates
    return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null
  }
  const ring =
    geometry.type === 'Polygon'
      ? geometry.coordinates[0]
      : geometry.type === 'MultiPolygon'
        ? geometry.coordinates[0]?.[0]
        : null
  if (!ring || ring.length === 0) return null
  const [sumLng, sumLat] = ring.reduce(([sLng, sLat], [lng, lat]) => [sLng + lng, sLat + lat], [0, 0])
  const lat = sumLat / ring.length
  const lng = sumLng / ring.length
  return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null
}

function pointLabelHtml(p) {
  const date = p.from_date
    ? new Date(p.from_date).toLocaleDateString('en-ZA', { year: 'numeric', month: 'short', day: 'numeric' })
    : 'Date unknown'
  return `
    <div style="font:12px -apple-system,sans-serif;background:${ACCENT.surface};color:${ACCENT.ink};
                border:1px solid ${ACCENT.hair};border-radius:8px;padding:8px 10px;
                box-shadow:0 6px 20px -6px rgba(40,28,16,0.28);max-width:220px;">
      <div style="font-weight:600;">${p.event_name || `${p.event_type} ${p.event_id}`}</div>
      <div style="color:${ACCENT.muted};margin-top:2px;">
        ${getHazardColor(p.event_type).label} · ${p.iso3 || 'unknown'} · ${date}
      </div>
    </div>
  `
}

function GlobeLegend() {
  return (
    <div className="panel absolute bottom-4 left-4 z-10 flex flex-col gap-1.5 p-3.5 text-[11px] text-ink backdrop-blur">
      <div className="mb-0.5 font-semibold text-muted uppercase tracking-wider text-[10px]">Hazard type</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        {Object.entries(HAZARD_COLORS).map(([code, { stroke, label }]) => (
          <div key={code} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: stroke }} />
            {label}
          </div>
        ))}
      </div>
      <div className="mt-1 border-t border-hair pt-1.5 text-[10px] text-faint">
        Point size by alert level · drag to rotate, scroll to zoom
      </div>
    </div>
  )
}

function SelectedEventCard({ point, onClose }) {
  if (!point) return null
  const color = getHazardColor(point.event_type)
  const alert = getAlert(point.alert_level)
  return (
    <div className="panel absolute right-4 top-4 z-10 w-64 p-3.5 text-ink">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color.stroke }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{color.label}</span>
        </div>
        <button onClick={onClose} className="text-faint hover:text-ink" aria-label="Close">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-1 text-sm font-semibold leading-tight">
        {point.event_name || `${point.event_type} ${point.event_id}`}
      </div>
      <div className="mt-2 space-y-1 text-xs text-muted">
        <div className="flex justify-between">
          <span>Country</span>
          <span className="text-ink">{point.iso3 || 'unknown'}</span>
        </div>
        <div className="flex justify-between">
          <span>Alert level</span>
          <span className={alert.text}>{point.alert_level || '—'}</span>
        </div>
        <div className="flex justify-between">
          <span>Date</span>
          <span className="text-ink">
            {point.from_date ? new Date(point.from_date).toLocaleDateString('en-ZA') : '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Footprint</span>
          <span className={point.has_footprint ? 'text-ok' : 'text-faint'}>
            {point.has_footprint ? 'Mapped' : 'Point only'}
          </span>
        </div>
      </div>
    </div>
  )
}

export default function GlobePanel({ hazards, loading, error, onRetry }) {
  const containerRef = useRef(null)
  const globeRef = useRef(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width, height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const points = useMemo(() => {
    if (!hazards) return []
    return hazards.features
      .map((feature) => {
        const coords = pointFromGeometry(feature.geometry)
        if (!coords) return null
        const [lat, lng] = coords
        const p = feature.properties
        return {
          lat,
          lng,
          color: getHazardColor(p.event_type).stroke,
          pointSize: ALERT_POINT_SIZE[p.alert_level] ?? DEFAULT_POINT_SIZE,
          ...p,
        }
      })
      .filter(Boolean)
  }, [hazards])

  const stats = useMemo(() => {
    if (!hazards) return null
    const countries = new Set(hazards.features.map((f) => f.properties.iso3).filter(Boolean))
    const types = new Set(hazards.features.map((f) => f.properties.event_type))
    return { eventCount: hazards.features.length, countryCount: countries.size, typeCount: types.size }
  }, [hazards])

  if (loading && !hazards) {
    return (
      <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
        <SkeletonCards count={3} hero />
        <SkeletonChart height={420} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-pml" />
        <div className="text-sm text-muted">{error}</div>
        <button onClick={onRetry} className="rounded border border-hair px-3 py-1.5 text-xs text-ink hover:bg-sunken">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
            <GlobeIcon className="h-4 w-4 text-brand" />
            Worldwide hazard activity
          </h2>
          <p className="text-[11px] text-muted">
            Every GDACS event ever ingested, not just South Africa — the pooled-climate dataset
            behind the country-scoped views elsewhere in this app.
          </p>
        </div>
        {stats && (
          <div className="flex items-center gap-x-4 text-xs text-muted">
            <span>
              <b className="font-semibold tabular-nums text-ink">{stats.eventCount}</b> events
            </span>
            <span className="text-hair">·</span>
            <span>
              <b className="font-semibold tabular-nums text-ink">{stats.countryCount}</b> countries
            </span>
            <span className="text-hair">·</span>
            <span>
              <b className="font-semibold tabular-nums text-ink">{stats.typeCount}</b> hazard types
            </span>
          </div>
        )}
      </div>

      <div ref={containerRef} className="relative min-h-0 flex-1 overflow-hidden rounded-panel bg-[#05070d]">
        {size.width > 0 && (
          <Globe
            ref={globeRef}
            width={size.width}
            height={size.height}
            globeImageUrl="https://unpkg.com/three-globe/example/img/earth-night.jpg"
            backgroundImageUrl="https://unpkg.com/three-globe/example/img/night-sky.png"
            pointsData={points}
            pointLat="lat"
            pointLng="lng"
            pointColor="color"
            pointRadius="pointSize"
            pointAltitude={0.01}
            pointLabel={pointLabelHtml}
            pointsTransitionDuration={0}
            onPointClick={(p) => setSelected(p)}
            atmosphereColor={ACCENT.brand}
            atmosphereAltitude={0.18}
          />
        )}
        <GlobeLegend />
        <SelectedEventCard point={selected} onClose={() => setSelected(null)} />
        {points.length === 0 && !loading && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted/70">
            No worldwide events ingested yet.
          </div>
        )}
      </div>

      <p className="px-1 text-[10px] leading-relaxed text-faint">
        Footprint polygons only exist for the South Africa–scoped subset (polygon enrichment stays
        country-scoped — see docs/architecture.md); every other event is plotted at its GDACS
        marker point, not a true footprint centroid.
      </p>
    </div>
  )
}
