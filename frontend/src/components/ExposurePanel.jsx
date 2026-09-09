import { AlertTriangle, Building2, DollarSign, MapPinOff, Radar, ShieldOff, TrendingDown, Zap } from 'lucide-react'
import { currency, getAlert, getHazardColor, percent } from '../lib/theme'
import AssetTable from './AssetTable'
import BiCalculator from './BiCalculator'
import MetricCard from './MetricCard'
import { SkeletonCard, SkeletonRows } from './Skeleton'

function AlertBadge({ level }) {
  if (!level) return null
  return (
    <span
      className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${getAlert(level).chip}`}
    >
      {level} alert
    </span>
  )
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <Radar className="h-10 w-10 text-faint" />
      <div className="max-w-xs text-sm text-muted">
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
      <div className="panel p-4">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color.stroke }} />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">{color.label}</span>
          <AlertBadge level={selectedHazardMeta.alert_level} />
        </div>
        <h2 className="mt-1.5 text-lg font-semibold leading-tight text-ink">
          {selectedHazardMeta.event_name || `${selectedHazardMeta.event_type} ${selectedHazardMeta.event_id}`}
        </h2>
        <div className="mt-1 flex items-center gap-2 text-xs text-muted">
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
          <span className={selectedHazardMeta.has_footprint ? 'text-ok' : 'text-over'}>
            {selectedHazardMeta.has_footprint ? 'Footprint mapped' : 'Point only — no footprint yet'}
          </span>
        </div>
      </div>

      {loading && (
        <>
          <SkeletonCard hero />
          <div className="grid grid-cols-2 gap-3">
            <SkeletonCard />
            <SkeletonCard />
          </div>
          <SkeletonRows rows={4} />
        </>
      )}

      {error && !loading && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
          <AlertTriangle className="h-8 w-8 text-pml" />
          <div className="text-sm text-muted">{error}</div>
          <button
            onClick={onRetry}
            className="rounded border border-hair px-3 py-1.5 text-xs text-ink hover:bg-sunken"
          >
            Retry
          </button>
        </div>
      )}

      {intersection && !loading && !error && (
        <>
          <MetricCard
            icon={DollarSign}
            label="TIV at risk"
            amount={intersection.total_insured_value}
            format={currency}
            hero
          />
          <div className="grid grid-cols-2 gap-3">
            <MetricCard
              icon={Building2}
              label="Assets"
              amount={intersection.asset_count}
              format={(n) => Math.round(n).toString()}
            />
            <MetricCard
              icon={Zap}
              label="Daily net revenue"
              amount={intersection.total_daily_net_revenue}
              format={currency}
              accent="text-over"
            />
          </div>

          {intersection.asset_count > 0 && (
            <div className="space-y-1.5">
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  icon={TrendingDown}
                  label={`PML (${percent(intersection.damage_ratio)} damage ratio)`}
                  amount={intersection.probable_maximum_loss}
                  format={currency}
                  accent="text-pml"
                />
                <MetricCard
                  icon={ShieldOff}
                  label={`Protection gap (${percent(intersection.protection_gap_pct)})`}
                  amount={intersection.protection_gap}
                  format={currency}
                  accent="text-gap"
                />
              </div>
              <div className="text-[10px] leading-relaxed text-faint">
                PML = TIV at risk × a HAZUS-MH/FEMA band midpoint for this hazard type and GDACS alert
                level — a documented approximation, not a per-event vulnerability assessment. Protection
                gap assumes an asset with no declared insured value is fully uninsured.
              </div>
            </div>
          )}

          {intersection.asset_count === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-hair px-6 py-8 text-center">
              <MapPinOff className="h-6 w-6 text-faint" />
              <div className="text-sm text-muted">No insured assets fall within this event's footprint.</div>
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
