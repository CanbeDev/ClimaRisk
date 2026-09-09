import { useMemo } from 'react'
import L from 'leaflet'
import { CircleMarker, GeoJSON, MapContainer, Marker, TileLayer, Tooltip, ZoomControl } from 'react-leaflet'
import {
  ASSET_TIV_LEGEND,
  currency,
  getAssetColor,
  getAssetTier,
  getHazardColor,
  HAZARD_COLORS,
} from '../lib/theme'

const SA_CENTER = [-28.8, 24.7]
const SA_ZOOM = 5.4

const LEGEND_SHAPE = { circle: 'rounded-full', square: 'rounded-[2px]', diamond: 'rounded-[2px] rotate-45' }

// --- Footprint click priority ------------------------------------------------
// Planar shoelace area (deg²) — used ONLY to rank footprints so the smallest
// overlapping one paints LAST (on top of the SVG overlay pane) and therefore
// wins the click. Not a real geographic area; a relative comparison within one
// map is all this needs.
function ringArea(ring) {
  let a = 0
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    a += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1])
  }
  return Math.abs(a) / 2
}
function footprintArea(feature) {
  const g = feature.geometry
  if (!g) return 0
  if (g.type === 'Polygon') return g.coordinates.reduce((s, r) => s + ringArea(r), 0)
  if (g.type === 'MultiPolygon') {
    return g.coordinates.reduce((s, poly) => s + poly.reduce((ss, r) => ss + ringArea(r), 0), 0)
  }
  return 0 // Point-only (centroid) events sort to the top — trivial to click.
}

// One divIcon per TIV tier — a surveyed-node glyph (grey by tier, orange ring)
// for assets that fall inside the selected footprint.
const assetIconCache = new Map()
function assetIcon(tier) {
  if (assetIconCache.has(tier.label)) return assetIconCache.get(tier.label)
  const s = tier.size
  const icon = L.divIcon({
    className: 'asset-node-wrap',
    html: `<span class="asset-node asset-node--${tier.shape}" style="--c:${tier.color};width:${s}px;height:${s}px"></span>`,
    iconSize: [s, s],
    iconAnchor: [s / 2, s / 2],
  })
  assetIconCache.set(tier.label, icon)
  return icon
}

function MapLegend() {
  return (
    <div className="panel absolute bottom-4 left-4 z-[1000] flex flex-col gap-2 rounded-[14px] p-3.5 text-[11px] text-ink backdrop-blur">
      <div>
        <div className="mb-1.5 font-semibold text-muted uppercase tracking-wider text-[10px]">Hazard type</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {Object.entries(HAZARD_COLORS).map(([code, { stroke, label }]) => (
            <div key={code} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: stroke }} />
              {label}
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-hair pt-2">
        <div className="mb-1.5 font-semibold text-muted uppercase tracking-wider text-[10px]">
          Asset TIV <span className="normal-case text-faint">— shape by tier</span>
        </div>
        {ASSET_TIV_LEGEND.map((tier) => (
          <div key={tier.label} className="flex items-center gap-2">
            <span className="flex h-3 w-3 items-center justify-center">
              <span
                className={`h-2 w-2 ${LEGEND_SHAPE[tier.shape]}`}
                style={{ backgroundColor: tier.color }}
              />
            </span>
            {tier.label}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function MapPanel({ hazards, assets, selectedHazardId, exposedAssetIds, onSelectHazard }) {
  const hazardStyle = useMemo(
    () => (feature) => {
      const { event_type: type, hazard_event_id: id, has_footprint } = feature.properties
      const color = getHazardColor(type)
      const isSelected = id === selectedHazardId
      return {
        // Outline stays the hazard-type hue (identity). EVERY footprint carries
        // the orange blueprint crosshatch so "these are hazard footprints" reads
        // at rest; the selected one swaps to the dense pattern and breathes.
        color: color.stroke,
        weight: isSelected ? 2.5 : 1.75,
        fillColor: isSelected ? 'url(#climrisk-hatch)' : 'url(#climrisk-hatch-rest)',
        fillOpacity: 1,
        dashArray: has_footprint ? undefined : '4 4',
        // Leaflet's setStyle re-applies fill/stroke on re-selection but not
        // className, so the "selected" breathe keys off the exact dense-pattern
        // fill (`url(#climrisk-hatch)`) in CSS instead — see index.css.
        className: `hazard-poly hazard-poly--${type}`,
      }
    },
    [selectedHazardId],
  )

  // Largest footprint first, so the smallest paints LAST — on top in the SVG
  // overlay pane. A click inside several overlapping footprints then selects the
  // most specific one, not the big regional flood polygon that engulfs it.
  const orderedFeatures = useMemo(() => {
    const feats = hazards?.features ?? []
    return [...feats].sort((a, b) => footprintArea(b) - footprintArea(a))
  }, [hazards])

  return (
    <div className="relative h-full w-full">
      {/* Pattern defs live in a zero-size SVG in the DOM; Leaflet paths resolve
          fill="url(#…)" against it document-wide. `-rest` is the faint identity
          every footprint carries; the dense one is the selected treatment. */}
      <svg aria-hidden="true" className="pointer-events-none absolute h-0 w-0 overflow-hidden">
        <defs>
          <pattern id="climrisk-hatch" width="9" height="9" patternUnits="userSpaceOnUse">
            <rect width="9" height="9" fill="#ff6a2b" fillOpacity="0.06" />
            <path
              d="M0,0 l9,9 M9,0 l-9,9"
              stroke="#ff6a2b"
              strokeWidth="0.85"
              strokeOpacity="0.5"
              shapeRendering="crispEdges"
            />
          </pattern>
          <pattern id="climrisk-hatch-rest" width="8" height="8" patternUnits="userSpaceOnUse">
            <rect width="8" height="8" fill="#ff6a2b" fillOpacity="0.05" />
            <path
              d="M0,0 l8,8"
              stroke="#ff6a2b"
              strokeWidth="1"
              strokeOpacity="0.4"
              shapeRendering="crispEdges"
            />
          </pattern>
        </defs>
      </svg>

      <MapContainer center={SA_CENTER} zoom={SA_ZOOM} zoomControl={false} className="h-full w-full">
        {/* Esri "Light Gray Canvas" — a muted, keyless light basemap that stays
            out of the way of the hazard/asset overlays. */}
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles &copy; Esri — Esri, HERE, Garmin, © OpenStreetMap contributors"
          maxZoom={16}
        />
        <ZoomControl position="bottomright" />

        {orderedFeatures.map((feature) => (
          <GeoJSON
            key={feature.properties.hazard_event_id}
            data={feature}
            style={hazardStyle}
            eventHandlers={{
              click: () => onSelectHazard(feature.properties.hazard_event_id),
            }}
          />
        ))}

        {assets?.features.map((feature) => {
          const [lng, lat] = feature.geometry.coordinates
          const { id, asset_name, asset_type, total_insured_value } = feature.properties
          const isExposed = exposedAssetIds?.has(id)
          const tooltip = (
            <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
              <div className="text-xs">
                <div className="font-semibold">{asset_name || `Asset #${id}`}</div>
                <div className="text-muted">{asset_type || 'unclassified'}</div>
                <div>TIV: {currency(total_insured_value)}</div>
              </div>
            </Tooltip>
          )

          // Inside the selected footprint → a shaped, tier-scaled surveyed node.
          if (isExposed) {
            return (
              <Marker key={id} position={[lat, lng]} icon={assetIcon(getAssetTier(total_insured_value))}>
                {tooltip}
              </Marker>
            )
          }
          // Otherwise a plain dot in the TIV-tier grey.
          return (
            <CircleMarker
              key={id}
              center={[lat, lng]}
              radius={4.5}
              pathOptions={{
                color: '#ffffff',
                weight: 1.25,
                fillColor: getAssetColor(total_insured_value),
                fillOpacity: 0.9,
                className: 'asset-dot',
              }}
            >
              {tooltip}
            </CircleMarker>
          )
        })}
      </MapContainer>
      <MapLegend />
    </div>
  )
}
