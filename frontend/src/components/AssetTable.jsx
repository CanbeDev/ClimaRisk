import { currency } from '../lib/theme'

export default function AssetTable({ assets }) {
  const sorted = [...assets].sort((a, b) => b.total_insured_value - a.total_insured_value)

  return (
    <div className="overflow-hidden panel rounded-lg">
      <div className="border-b border-hair px-4 py-2.5 text-sm font-semibold text-ink">
        Intersected Assets ({assets.length})
      </div>
      <div className="max-h-64 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-sunken text-[10px] uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Asset</th>
              <th className="px-2 py-2 text-left font-medium">Type</th>
              <th className="px-2 py-2 text-right font-medium">TIV</th>
              <th className="px-2 py-2 text-right font-medium">Insured</th>
              <th className="px-4 py-2 text-right font-medium">Contrib. margin/day</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-hair">
            {sorted.map((asset) => (
              <tr key={asset.id} className="hover:bg-row">
                <td className="px-4 py-2 text-ink">{asset.asset_name || `Asset #${asset.id}`}</td>
                <td className="px-2 py-2 capitalize text-muted">{asset.asset_type || '—'}</td>
                <td className="px-2 py-2 text-right tabular-nums text-ink">
                  {currency(asset.total_insured_value)}
                </td>
                <td
                  className={`px-2 py-2 text-right tabular-nums ${
                    asset.insured_value ? 'text-muted' : 'text-pml'
                  }`}
                >
                  {asset.insured_value ? currency(asset.insured_value) : 'Uninsured'}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
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
