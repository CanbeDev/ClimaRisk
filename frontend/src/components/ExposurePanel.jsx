import { AlertTriangle, DollarSign, MapPinOff, Radar, Repeat } from 'lucide-react'
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

// The one domain-specific viz: TIV at risk is the whole bar; it splits into the
// insured slice and the protection gap, with the modelled loss (PML) pinned
// against it. Replaces what used to be two lookalike metric tiles.
function CoverageBar({ intersection }) {
  const tiv = intersection.total_insured_value || 0
  const declared = intersection.total_declared_insured_value || 0
  const gap = intersection.protection_gap || 0
  const pml = intersection.probable_maximum_loss || 0
  const asPct = (n) => (tiv > 0 ? Math.max(0, Math.min(100, (n / tiv) * 100)) : 0)
  const declaredPct = asPct(declared)
  const gapPct = Math.max(0, 100 - declaredPct)
  const pmlPct = asPct(pml)

  return (
    <div className="panel p-4">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">
        Coverage vs. exposure at risk
      </div>

      <div className="relative mt-6 h-8">
        <div
          className="absolute -top-4 z-10 -translate-x-1/2 whitespace-nowrap text-[9px] font-semibold text-pml"
          style={{ left: `${pmlPct}%` }}
        >
          PML
        </div>
        <div className="flex h-full overflow-hidden rounded bg-sunken">
          {declaredPct > 0 && <div className="h-full bg-ok/80" style={{ width: `${declaredPct}%` }} />}
          <div className="h-full bg-gap/70" style={{ width: `${gapPct}%` }} />
        </div>
        <div className="absolute inset-y-0 z-10" style={{ left: `${pmlPct}%` }}>
          <div className="h-full w-0.5 -translate-x-1/2 bg-pml" />
        </div>
        <div className="absolute -bottom-4 right-0 text-[9px] uppercase tracking-wide text-faint">
          = TIV at risk
        </div>
      </div>

      <div className="mt-8 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <div className="flex items-center gap-1 text-muted">
            <span className="h-2 w-2 rounded-sm bg-ok/80" />
            Insured
          </div>
          <div className="mt-0.5 tabular-nums text-ink">{currency(declared)}</div>
        </div>
        <div>
          <div className="flex items-center gap-1 text-muted">
            <span className="h-2 w-2 rounded-sm bg-gap/70" />
            Protection gap
          </div>
          <div className="mt-0.5 tabular-nums text-gap">
            {currency(gap)}{' '}
            <span className="text-faint">({percent(intersection.protection_gap_pct)})</span>
          </div>
        </div>
        <div>
          <div className="flex items-center gap-1 text-muted">
            <span className="h-2.5 w-0.5 bg-pml" />
            Modelled loss (PML)
          </div>
          <div className="mt-0.5 tabular-nums text-pml">
            {currency(pml)} <span className="text-faint">({percent(intersection.damage_ratio)})</span>
          </div>
        </div>
      </div>

      <div className="mt-3 border-t border-hair pt-2 text-[10px] leading-relaxed text-faint">
        The bar is TIV at risk. PML = TIV × a HAZUS-MH/FEMA band ratio for this hazard type and
        GDACS alert level, interpolated by each asset's distance from the footprint's centroid —
        a documented approximation, not a per-event vulnerability assessment. Protection gap
        treats any asset with no declared insured value as fully uninsured.
      </div>
    </div>
  )
}

function PortfolioMasthead({ portfolio }) {
  return (
    <div className="flex h-full flex-col gap-4 p-4">
      {portfolio ? (
        <>
          <MetricCard icon={DollarSign} label="Portfolio TIV" amount={portfolio.tiv} format={currency} hero />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-0.5 text-xs text-muted">
            <span>
              <b className="font-semibold tabular-nums text-ink">{portfolio.assetCount}</b> insured{' '}
              {portfolio.assetCount === 1 ? 'asset' : 'assets'}
            </span>
            <span className="text-hair">·</span>
            <span>
              <b className="font-semibold tabular-nums text-ink">{portfolio.eventCount}</b> events in view
            </span>
          </div>
        </>
      ) : (
        <>
          <SkeletonCard hero />
          <div className="skeleton h-3 w-40" />
        </>
      )}
      <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-hair px-6 text-center">
        <Radar className="h-8 w-8 text-faint" />
        <div className="max-w-xs text-sm text-muted">
          Select a hazard event on the map to see the exposure and coverage it puts at risk.
        </div>
      </div>
    </div>
  )
}

export default function ExposurePanel({ selectedHazardMeta, intersection, portfolio, loading, error, onRetry }) {
  if (!selectedHazardMeta) {
    return <PortfolioMasthead portfolio={portfolio} />
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
          <div className="skeleton h-3 w-48" />
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

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-0.5 text-xs text-muted">
            <span>
              <b className="font-semibold tabular-nums text-ink">{intersection.asset_count}</b>{' '}
              {intersection.asset_count === 1 ? 'asset' : 'assets'} exposed
            </span>
            <span className="text-hair">·</span>
            <span>
              Daily net revenue{' '}
              <b className="font-semibold tabular-nums text-over">
                {currency(intersection.total_daily_net_revenue)}
              </b>
            </span>
            {intersection.assets.some((a) => a.is_compound_loss) && (
              <>
                <span className="text-hair">·</span>
                <span className="flex items-center gap-1 text-pml" title="Already hit by another event within the compounding window — their damage ratio is escalated.">
                  <Repeat className="h-3 w-3" />
                  <b className="font-semibold tabular-nums">
                    {intersection.assets.filter((a) => a.is_compound_loss).length}
                  </b>{' '}
                  compound loss{intersection.assets.filter((a) => a.is_compound_loss).length === 1 ? '' : 'es'}
                </span>
              </>
            )}
          </div>

          {intersection.asset_count > 0 ? (
            <>
              <CoverageBar intersection={intersection} />
              <BiCalculator assets={intersection.assets} totalInsuredValue={intersection.total_insured_value} />
              <AssetTable assets={intersection.assets} />
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-hair px-6 py-8 text-center">
              <MapPinOff className="h-6 w-6 text-faint" />
              <div className="text-sm text-muted">No insured assets fall within this event's footprint.</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
