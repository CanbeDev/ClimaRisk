import { useMemo } from 'react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, ZoomControl } from 'react-leaflet'
import { ASSET_TIV_LEGEND, currency, getAssetColor, getHazardColor, HAZARD_COLORS } from '../lib/theme'

const SA_CENTER = [-28.8, 24.7]
const SA_ZOOM = 5.4

function MapLegend() {
  return (
    <div className="absolute bottom-4 left-4 z-[1000] flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/90 p-3 text-[11px] text-slate-300 backdrop-blur">
      <div>
        <div className="mb-1 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Hazard type</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {Object.entries(HAZARD_COLORS).map(([code, { stroke, label }]) => (
            <div key={code} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: stroke }} />
              {label}
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-slate-800 pt-2">
        <div className="mb-1 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Asset TIV</div>
        {ASSET_TIV_LEGEND.map((tier) => (
          <div key={tier.label} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tier.color }} />
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
      const color = getHazardColor(feature.properties.event_type)
      const isSelected = feature.properties.hazard_event_id === selectedHazardId
      return {
        color: color.stroke,
        weight: isSelected ? 3 : 1.5,
        fillColor: color.fill,
        fillOpacity: isSelected ? 0.35 : 0.15,
        dashArray: feature.properties.has_footprint ? undefined : '4 4',
      }
    },
    [selectedHazardId],
  )

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={SA_CENTER}
        zoom={SA_ZOOM}
        zoomControl={false}
        preferCanvas
        className="h-full w-full"
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_matter/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        />
        <ZoomControl position="bottomright" />

        {hazards?.features.map((feature) => (
          <GeoJSON
            key={feature.properties.hazard_event_id}
            data={feature}
            style={hazardStyle}
            eventHandlers={{
              click: () => onSelectHazard(feature.properties.hazard_event_id),
            }}
          >
          </GeoJSON>
        ))}

        {assets?.features.map((feature) => {
          const [lng, lat] = feature.geometry.coordinates
          const isExposed = exposedAssetIds?.has(feature.properties.id)
          const color = getAssetColor(feature.properties.total_insured_value)
          return (
            <CircleMarker
              key={feature.properties.id}
              center={[lat, lng]}
              radius={isExposed ? 8 : 5}
              pathOptions={{
                color: isExposed ? '#f8fafc' : color,
                weight: isExposed ? 2.5 : 1,
                fillColor: color,
                fillOpacity: isExposed ? 0.95 : 0.75,
              }}
            >
              <Tooltip direction="top" offset={[0, -6]} opacity={0.95}>
                <div className="text-xs">
                  <div className="font-semibold">{feature.properties.asset_name || `Asset #${feature.properties.id}`}</div>
                  <div className="text-slate-400">{feature.properties.asset_type || 'unclassified'}</div>
                  <div>TIV: {currency(feature.properties.total_insured_value)}</div>
                </div>
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <MapLegend />
    </div>
  )
}
