import { AlertTriangle, Building2, DollarSign, Loader2, MapPinOff, Radar, ShieldOff, TrendingDown, Zap } from 'lucide-react'
import { currency, getHazardColor, percent } from '../lib/theme'
import AssetTable from './AssetTable'
import BiCalculator from './BiCalculator'
import MetricCard from './MetricCard'

const ALERT_STYLES = {
  Red: 'border-rose-500/30 bg-rose-500/15 text-rose-400',
  Orange: 'border-amber-500/30 bg-amber-500/15 text-amber-400',
  Green: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400',
}

function AlertBadge({ level }) {
  if (!level) return null
  return (
    <span
      className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        ALERT_STYLES[level] || 'border-slate-500/30 bg-slate-500/15 text-slate-400'
      }`}
    >
      {level} alert
    </span>
  )
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <Radar className="h-10 w-10 text-slate-700" />
      <div className="max-w-xs text-sm text-slate-500">
        Select a hazard event on the map to view its underwriting exposure.
      </div>
    </div>
  )
}

export default function ExposurePanel({ selectedHazardMeta, intersection, loading, error, onRetry }) {
  if (!selectedHazardMeta) {
    return <EmptyState />
  }

  const color = getHazardColor(selectedHazardMeta.event_type)

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color.stroke }} />
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{color.label}</span>
          <AlertBadge level={selectedHazardMeta.alert_level} />
        </div>
        <h2 className="mt-1.5 text-lg font-semibold leading-tight text-slate-100">
          {selectedHazardMeta.event_name || `${selectedHazardMeta.event_type} ${selectedHazardMeta.event_id}`}
        </h2>
        <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
          <span>
            {selectedHazardMeta.from_date
              ? new Date(selectedHazardMeta.from_date).toLocaleDateString('en-ZA', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })
              : 'Date unknown'}
          </span>
          <span>•</span>
          <span className={selectedHazardMeta.has_footprint ? 'text-emerald-500' : 'text-amber-500'}>
            {selectedHazardMeta.has_footprint ? 'Footprint mapped' : 'Point only — no footprint yet'}
          </span>
        </div>
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Computing spatial exposure…
        </div>
      )}

      {error && !loading && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
          <AlertTriangle className="h-8 w-8 text-rose-500" />
          <div className="text-sm text-slate-400">{error}</div>
          <button
            onClick={onRetry}
            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Retry
          </button>
        </div>
      )}

      {intersection && !loading && !error && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard icon={Building2} label="Assets" value={intersection.asset_count} />
            <MetricCard
              icon={DollarSign}
              label="TIV at risk"
              value={currency(intersection.total_insured_value)}
              accent="text-cyan-400"
            />
            <MetricCard
              icon={Zap}
              label="Daily net revenue"
              value={currency(intersection.total_daily_net_revenue)}
              accent="text-amber-400"
            />
          </div>

          {intersection.asset_count > 0 && (
            <div className="space-y-1.5">
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  icon={TrendingDown}
                  label={`PML (${percent(intersection.damage_ratio)} damage ratio)`}
                  value={currency(intersection.probable_maximum_loss)}
                  accent="text-rose-400"
                />
                <MetricCard
                  icon={ShieldOff}
                  label={`Protection gap (${percent(intersection.protection_gap_pct)})`}
                  value={currency(intersection.protection_gap)}
                  accent="text-orange-400"
                />
              </div>
              <div className="text-[10px] leading-relaxed text-slate-600">
                PML = TIV at risk × a HAZUS-MH/FEMA band midpoint for this hazard type and GDACS alert
                level — a documented approximation, not a per-event vulnerability assessment. Protection
                gap assumes an asset with no declared insured value is fully uninsured.
              </div>
            </div>
          )}

          {intersection.asset_count === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-800 px-6 py-8 text-center">
              <MapPinOff className="h-6 w-6 text-slate-700" />
              <div className="text-sm text-slate-500">No insured assets fall within this event's footprint.</div>
            </div>
          ) : (
            <>
              <BiCalculator assets={intersection.assets} totalInsuredValue={intersection.total_insured_value} />
              <AssetTable assets={intersection.assets} />
            </>
          )}
        </>
      )}
    </div>
  )
}
