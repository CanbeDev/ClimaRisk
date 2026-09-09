/** Shaped placeholders for loading states — shimmer over the real layout. */

export function SkeletonCard({ hero = false }) {
  return (
    <div className="panel p-3">
      <div className="skeleton h-2.5 w-20" />
      <div className={`skeleton mt-2.5 ${hero ? 'h-7 w-40' : 'h-6 w-28'}`} />
    </div>
  )
}

export function SkeletonCards({ count = 4, hero = false }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} hero={hero && i === 0} />
      ))}
    </div>
  )
}

export function SkeletonRows({ rows = 6, title = true }) {
  return (
    <div className="panel overflow-hidden">
      {title ? (
        <div className="border-b border-hair px-4 py-2.5">
          <div className="skeleton h-3 w-40" />
        </div>
      ) : null}
      <div className="divide-y divide-hair">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-2.5">
            <div className="skeleton h-3" style={{ width: `${28 + ((i * 13) % 24)}%` }} />
            <div className="skeleton h-3 w-14" />
            <div className="skeleton ml-auto h-3 w-20" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function SkeletonChart({ height = 220 }) {
  return (
    <div className="panel p-4">
      <div className="skeleton h-2.5 w-44" />
      <div className="skeleton mt-3 w-full rounded-md" style={{ height }} />
    </div>
  )
}
