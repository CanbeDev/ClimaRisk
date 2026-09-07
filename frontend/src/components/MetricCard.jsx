export default function MetricCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1.5 truncate text-xl font-semibold tabular-nums ${accent ?? 'text-slate-100'}`}>
        {value}
      </div>
    </div>
  )
}
