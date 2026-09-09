import { useEffect, useState } from 'react'
import { AlertTriangle, Building2, CalendarRange, ExternalLink, ShieldOff, TrendingDown } from 'lucide-react'
import { disclosureHtmlUrl } from '../api'
import { currency, getAlert, getHazardColor, percent } from '../lib/theme'
import MetricCard from './MetricCard'
import { SkeletonCards, SkeletonRows } from './Skeleton'

const FIELD = 'rounded border border-hair bg-ground px-2 py-1 text-xs text-ink'

export default function ReportPanel({ report, loading, error, onReload }) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  // Seed the date inputs from the server-resolved period once it arrives.
  useEffect(() => {
    if (report && !from && !to) {
      setFrom(report.period_start)
      setTo(report.period_end)
    }
  }, [report, from, to])

  if (loading && !report) {
    return (
      <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
        <SkeletonCards count={6} hero />
        <SkeletonRows rows={5} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-pml" />
        <div className="text-sm text-muted">{error}</div>
        <button
          onClick={() => onReload(from || undefined, to || undefined)}
          className="rounded border border-hair px-3 py-1.5 text-xs text-ink hover:bg-sunken"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!report) return null

  const pf = report.portfolio
  const hx = report.hazard_exposure
  const pm = report.parametric_position
  const peak = hx.peak_event
  const coverRatio = pf.total_insured_value ? pf.declared_insured_value / pf.total_insured_value : null

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 overflow-y-auto p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Climate risk disclosure</h2>
          <p className="text-[11px] text-muted">
            {report.org_name} · hazard scope {report.iso3} · TCFD-style export
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={FIELD} />
          </label>
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
            To
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={FIELD} />
          </label>
          <button
            onClick={() => onReload(from || undefined, to || undefined)}
            className="rounded border border-hair px-2.5 py-1 text-xs text-ink hover:bg-sunken"
          >
            Update
          </button>
          <a
            href={disclosureHtmlUrl(from || undefined, to || undefined)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded bg-brand px-2.5 py-1 text-xs font-medium text-white hover:bg-brandink"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Printable report
          </a>
        </div>
      </div>

      <p className="text-[11px] text-muted">
        Reporting period{' '}
        <span className="text-ink">
          {report.period_start} → {report.period_end}
        </span>{' '}
        · generated {new Date(report.generated_at).toLocaleString('en-ZA')}
      </p>

      {/* Portfolio + exposure headline ---------------------------------- */}
      <MetricCard
        icon={CalendarRange}
        label="Distinct TIV exposed in period"
        amount={hx.distinct_tiv_exposed}
        format={currency}
        hero
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCard
          icon={Building2}
          label="Insured assets"
          amount={pf.asset_count}
          format={(n) => Math.round(n).toString()}
        />
        <MetricCard icon={Building2} label="Portfolio TIV" amount={pf.total_insured_value} format={currency} />
        <MetricCard
          icon={ShieldOff}
          label="Declared cover"
          value={coverRatio == null ? '—' : percent(coverRatio)}
          accent={coverRatio ? 'text-ink' : 'text-pml'}
        />
        <MetricCard
          icon={CalendarRange}
          label="Distinct assets exposed"
          amount={hx.distinct_assets_exposed}
          format={(n) => Math.round(n).toString()}
          accent="text-brand"
        />
        <MetricCard
          icon={TrendingDown}
          label="Peak event PML"
          accent="text-pml"
          {...(peak ? { amount: peak.probable_maximum_loss, format: currency } : { value: '—' })}
        />
      </div>

      {/* Events table ------------------------------------------------------ */}
      <div className="overflow-hidden panel">
        <div className="border-b border-hair px-4 py-2.5 text-sm font-semibold text-ink">
          Hazard events in period ({hx.event_count})
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-sunken text-[10px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Event</th>
                <th className="px-2 py-2 text-left font-medium">Date</th>
                <th className="px-2 py-2 text-left font-medium">Alert</th>
                <th className="px-2 py-2 text-right font-medium">Assets</th>
                <th className="px-2 py-2 text-right font-medium">TIV at risk</th>
                <th className="px-2 py-2 text-right font-medium">PML</th>
                <th className="px-4 py-2 text-right font-medium">Protection gap</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hair">
              {hx.events.map((e) => (
                <tr key={e.hazard_event_id} className="hover:bg-row">
                  <td className="px-4 py-2 text-ink">
                    <span
                      className="mr-1.5 inline-block h-2 w-2 rounded-sm align-middle"
                      style={{ backgroundColor: getHazardColor(e.event_type).stroke }}
                    />
                    {e.event_name || `${e.event_type} ${e.event_id}`}
                  </td>
                  <td className="px-2 py-2 text-muted">
                    {e.from_date ? new Date(e.from_date).toLocaleDateString('en-ZA') : '—'}
                  </td>
                  <td className={`px-2 py-2 ${getAlert(e.alert_level).text}`}>
                    {e.alert_level || '—'}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-ink">{e.asset_count}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-ink">{currency(e.tiv_at_risk)}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-pml">{currency(e.probable_maximum_loss)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-gap">{currency(e.protection_gap)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border-t border-hair px-4 py-2 text-[10px] leading-relaxed text-faint">
          Gross Σ across events (double-counts assets hit more than once): TIV at risk{' '}
          {currency(hx.gross_tiv_at_risk)}, PML {currency(hx.gross_probable_maximum_loss)}. The
          "distinct" cards above de-duplicate.
        </div>
      </div>

      {/* Parametric position -------------------------------------------- */}
      <div className="panel p-5">
        <div className="text-sm font-semibold text-ink">Parametric coverage position</div>
        <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
          <div className="flex justify-between">
            <span className="text-muted">Active rules</span>
            <span className="tabular-nums text-ink">
              {pm.active_rule_count ?? 0} / {pm.rule_count ?? 0}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Firings</span>
            <span className="tabular-nums text-ink">{pm.firing_count ?? 0}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Outstanding payout</span>
            <span className="tabular-nums text-brand">{currency(pm.total_outstanding_payout ?? 0)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Net basis risk</span>
            <span
              className={`tabular-nums ${
                (pm.total_basis_risk ?? 0) > 0
                  ? 'text-over'
                  : (pm.total_basis_risk ?? 0) < 0
                    ? 'text-pml'
                    : 'text-ink'
              }`}
            >
              {currency(pm.total_basis_risk ?? 0)}
            </span>
          </div>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-faint">
          The printable report also carries a methodology &amp; limitations section (damage-ratio
          approximation, protection-gap and basis-risk caveats, footprint and scope notes).
        </p>
      </div>
    </div>
  )
}
