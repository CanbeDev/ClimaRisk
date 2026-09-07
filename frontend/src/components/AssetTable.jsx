import { currency } from '../lib/theme'

export default function AssetTable({ assets }) {
  const sorted = [...assets].sort((a, b) => b.total_insured_value - a.total_insured_value)

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60">
      <div className="border-b border-slate-800 px-4 py-2.5 text-sm font-semibold text-slate-200">
        Intersected Assets ({assets.length})
      </div>
      <div className="max-h-64 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-900 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Asset</th>
              <th className="px-2 py-2 text-left font-medium">Type</th>
              <th className="px-2 py-2 text-right font-medium">TIV</th>
              <th className="px-2 py-2 text-right font-medium">Insured</th>
              <th className="px-4 py-2 text-right font-medium">Contrib. margin/day</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {sorted.map((asset) => (
              <tr key={asset.id} className="hover:bg-slate-800/40">
                <td className="px-4 py-2 text-slate-200">{asset.asset_name || `Asset #${asset.id}`}</td>
                <td className="px-2 py-2 capitalize text-slate-400">{asset.asset_type || '—'}</td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-200">
                  {currency(asset.total_insured_value)}
                </td>
                <td
                  className={`px-2 py-2 text-right tabular-nums ${
                    asset.insured_value ? 'text-slate-400' : 'text-rose-400'
                  }`}
                >
                  {asset.insured_value ? currency(asset.insured_value) : 'Uninsured'}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-slate-400">
                  {currency(asset.contribution_margin)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
