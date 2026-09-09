import AnimatedNumber from './AnimatedNumber'

/**
 * The universal stat primitive.
 *
 *  - `value`  — a ready-formatted string/node (default path)
 *  - `amount` + `format` — a raw number that counts up on change
 *  - `hero`   — the one near-black callout per view: a big, light-weight
 *               display number in the brand orange over a small tracked label
 *  - `accent` — text colour class for a standard card's value
 *  - `glow`   — override colour for the hero number + underglow (default brand)
 */
export default function MetricCard({ icon: Icon, label, value, amount, format, accent, hero, glow }) {
  const showAmount = amount !== undefined && amount !== null
  const body = showAmount ? <AnimatedNumber value={amount} format={format} /> : value

  if (hero) {
    return (
      <div className="hero-metric shrink-0 px-6 py-5" style={glow ? { '--glow': glow } : undefined}>
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-darkmuted">
          {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
          {label}
        </div>
        <div className="hero-value relative mt-2 truncate tabular-nums">{body}</div>
      </div>
    )
  }

  return (
    <div className="panel panel-hover p-4">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
        {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
        {label}
      </div>
      <div className={`mt-2 truncate text-[22px] font-normal tabular-nums ${accent ?? 'text-ink'}`}>
        {body}
      </div>
    </div>
  )
}
