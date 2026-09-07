import { useMemo, useState } from 'react'
import { Info } from 'lucide-react'
import { currency } from '../lib/theme'

export default function BiCalculator({ assets, totalInsuredValue }) {
  const [days, setDays] = useState(14)

  const { biLoss, uncoveredCount } = useMemo(() => {
    let loss = 0
    let uncovered = 0
    for (const asset of assets) {
      if (asset.daily_net_revenue != null && asset.variable_cost_ratio != null) {
        loss += asset.daily_net_revenue * asset.variable_cost_ratio * days
      } else {
        uncovered += 1
      }
    }
    return { biLoss: loss, uncoveredCount: uncovered }
  }, [assets, days])

  const totalEstimatedLoss = biLoss + totalInsuredValue

  return (
    <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Business Interruption Estimator</h3>
        <span className="text-xs text-slate-500">
          {days} day{days === 1 ? '' : 's'} outage
        </span>
      </div>

      <input
        type="range"
        min={1}
        max={90}
        value={days}
        onChange={(event) => setDays(Number(event.target.value))}
        className="w-full accent-cyan-400"
        aria-label="Assumed outage duration in days"
      />
      <div className="flex justify-between text-[10px] text-slate-600">
        <span>1 day</span>
        <span>90 days</span>
      </div>

      <div className="grid grid-cols-2 gap-3 pt-1">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Projected BI loss</div>
          <div className="text-lg font-semibold tabular-nums text-amber-400">{currency(biLoss)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Property + BI total</div>
          <div className="text-lg font-semibold tabular-nums text-rose-400">{currency(totalEstimatedLoss)}</div>
        </div>
      </div>

      {uncoveredCount > 0 && (
        <div className="flex items-start gap-1.5 pt-1 text-[11px] text-slate-500">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {uncoveredCount} of {assets.length} assets lack BI parameters and are excluded from the BI figure.
          </span>
        </div>
      )}

      <div className="border-t border-slate-800 pt-2 text-[10px] leading-relaxed text-slate-600">
        BI loss = Σ (daily net revenue × variable cost ratio) × outage days. The property figure is full TIV at
        risk, not a probabilistic damage estimate — no damage-ratio curve is modeled yet.
      </div>
    </div>
  )
}
