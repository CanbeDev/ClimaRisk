import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, CalendarRange, Layers, ShieldOff, TrendingDown } from 'lucide-react'
import { currency, DEFAULT_HAZARD_COLOR, getAlertColor, HAZARD_COLORS } from '../lib/theme'
import MetricCard from './MetricCard'
import { SkeletonCards, SkeletonChart } from './Skeleton'

const EMPTY = []

const AXIS = '#c9c1b5' // warm hairline
const TICK = { fill: '#8c8278', fontSize: 11 } // warm grey
const GRID = '#ece5db' // hair
const TOOLTIP_STYLE = {
  backgroundColor: '#ffffff',
  border: '1px solid #e7e0d7',
  borderRadius: 10,
  boxShadow: '0 6px 20px -6px rgba(40,28,16,0.18)',
  color: '#211d18',
  fontSize: 12,
}

const HAZARD_CODES = Object.keys(HAZARD_COLORS)
const ALERT_LEVELS = ['Red', 'Orange', 'Green']

function compactZAR(value) {
  if (value == null) return '—'
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `R${(value / 1_000).toFixed(0)}k`
  return `R${value.toFixed(0)}`
}

function yearOf(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.getFullYear()
}

function ChartCard({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="panel rounded-[14px] p-5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </div>
      {subtitle && <div className="mt-0.5 text-[11px] text-faint">{subtitle}</div>}
      <div className="mt-3">{children}</div>
    </div>
  )
}

function FinancialTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2 text-ink">
      <div className="mb-1 font-semibold">{label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center justify-between gap-4">
          <span style={{ color: entry.color }}>{entry.name}</span>
          <span className="tabular-nums">{currency(entry.value)}</span>
        </div>
      ))}
    </div>
  )
}

export default function TrendsPanel({ trends, loading, error, onRetry }) {
  const events = trends?.events ?? EMPTY

  const { byYearType, byYearAlert, financial, years, hazardsPresent, alertsPresent, countMax } = useMemo(() => {
    const yearMap = new Map()
    for (const ev of events) {
      const y = yearOf(ev.from_date)
      if (y == null) continue
      if (!yearMap.has(y)) yearMap.set(y, { year: y, _type: {}, _alert: {} })
      const bucket = yearMap.get(y)
      bucket._type[ev.event_type] = (bucket._type[ev.event_type] || 0) + 1
      if (ev.alert_level) bucket._alert[ev.alert_level] = (bucket._alert[ev.alert_level] || 0) + 1
    }
    const sortedYears = [...yearMap.keys()].sort((a, b) => a - b)

    const typesSeen = new Set()
    const alertsSeen = new Set()
    events.forEach((ev) => {
      typesSeen.add(ev.event_type)
      if (ev.alert_level) alertsSeen.add(ev.alert_level)
    })
    const hz = HAZARD_CODES.filter((c) => typesSeen.has(c))
    HAZARD_CODES.forEach((c) => typesSeen.delete(c))
    const hzList = [...hz, ...typesSeen] // known codes first, then any unrecognised
    const alertList = ALERT_LEVELS.filter((a) => alertsSeen.has(a))

    const fill = (rows, keys, sub) =>
      rows.map((y) => {
        const row = { year: String(y.year) }
        keys.forEach((k) => {
          row[k] = yearMap.get(y.year)[sub][k] || 0
        })
        return row
      })

    const yearRows = sortedYears.map((y) => yearMap.get(y))
    const byYearType = fill(yearRows, hzList, '_type')
    const byYearAlert = fill(yearRows, alertList, '_alert')

    // Tight integer ceiling for the count charts — without this recharts
    // widens the domain to 0–4 just to land 5 whole-number ticks, which
    // flattens single-event years into slivers.
    const stackMax = (rows, keys) =>
      rows.reduce((m, r) => Math.max(m, keys.reduce((s, k) => s + (r[k] || 0), 0)), 0)
    // Floor of 2 keeps a lone-event year from rendering as a full-bleed block.
    const countMax = Math.max(stackMax(byYearType, hzList), stackMax(byYearAlert, alertList), 2)

    return {
      years: sortedYears,
      hazardsPresent: hzList,
      alertsPresent: alertList,
      countMax,
      byYearType,
      byYearAlert,
      financial: events
        .filter((ev) => ev.from_date)
        .slice()
        .sort((a, b) => new Date(a.from_date) - new Date(b.from_date))
        .map((ev) => ({
          label: ev.event_name || `${ev.event_type} ${ev.event_id}`,
          date: new Date(ev.from_date).toLocaleDateString('en-ZA', { year: 'numeric', month: 'short' }),
          tiv: ev.tiv_at_risk,
          pml: ev.probable_maximum_loss,
          gap: ev.protection_gap,
        })),
    }
  }, [events])

  const summary = useMemo(() => {
    const withExposure = events.filter((e) => e.asset_count > 0)
    const peak = events.reduce(
      (acc, e) => (e.probable_maximum_loss > (acc?.probable_maximum_loss ?? -1) ? e : acc),
      null,
    )
    return {
      total: events.length,
      span: years.length ? `${years[0]}–${years[years.length - 1]}` : '—',
      withExposure: withExposure.length,
      peakPml: peak && peak.probable_maximum_loss > 0 ? peak : null,
    }
  }, [events, years])

  if (loading) {
    return (
      <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
        <SkeletonCards count={4} hero />
        <SkeletonChart height={200} />
        <SkeletonChart height={180} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-pml" />
        <div className="text-sm text-muted">{error}</div>
        <button
          onClick={onRetry}
          className="rounded border border-hair px-3 py-1.5 text-xs text-ink hover:bg-sunken"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!events.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <CalendarRange className="h-10 w-10 text-faint" />
        <div className="max-w-sm text-sm text-muted">
          No hazard events ingested yet for {trends?.country || 'this country'}. Run a backfill to
          populate the historical view.
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 overflow-y-auto p-6">
      <div>
        <h2 className="text-sm font-semibold text-ink">Historical hazard &amp; exposure trend</h2>
        <p className="text-[11px] text-muted">
          Every ingested event for {trends?.country || '—'}, over time. Exposure figures reuse the same
          TIV / PML / Protection-Gap logic as the per-event panel.
        </p>
      </div>

      <MetricCard
        icon={TrendingDown}
        label="Peak event PML"
        hero
        glow="#e0454a"
        {...(summary.peakPml
          ? { amount: summary.peakPml.probable_maximum_loss, format: compactZAR }
          : { value: '—' })}
      />
      <div className="grid grid-cols-3 gap-3">
        <MetricCard icon={CalendarRange} label="Events" amount={summary.total} format={(n) => Math.round(n).toString()} />
        <MetricCard icon={CalendarRange} label="Span" value={summary.span} />
        <MetricCard
          icon={Layers}
          label="With exposed assets"
          amount={summary.withExposure}
          format={(n) => Math.round(n).toString()}
          accent="text-brand"
        />
      </div>

      <ChartCard
        icon={Layers}
        title="Hazard frequency by year"
        subtitle="Event count per year, stacked by GDACS hazard type"
      >
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={byYearType} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <defs>
              {hazardsPresent.map((code) => {
                const c = (HAZARD_COLORS[code] || DEFAULT_HAZARD_COLOR).fill
                return (
                  <linearGradient key={code} id={`bar-hz-${code}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={c} stopOpacity={0.95} />
                    <stop offset="100%" stopColor={c} stopOpacity={0.28} />
                  </linearGradient>
                )
              })}
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="year" stroke={AXIS} tick={TICK} />
            <YAxis
              stroke={AXIS}
              tick={TICK}
              allowDecimals={false}
              domain={[0, countMax]}
              tickCount={countMax + 1}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#00000008' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {hazardsPresent.map((code) => (
              <Bar
                key={code}
                dataKey={code}
                stackId="hz"
                maxBarSize={72}
                name={(HAZARD_COLORS[code] || DEFAULT_HAZARD_COLOR).label}
                fill={`url(#bar-hz-${code})`}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard
        icon={AlertTriangle}
        title="Alert level mix by year"
        subtitle="GDACS Green / Orange / Red classification of each year's events"
      >
        {alertsPresent.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byYearAlert} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
              <defs>
                {alertsPresent.map((level) => {
                  const c = getAlertColor(level)
                  return (
                    <linearGradient key={level} id={`bar-al-${level}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={c} stopOpacity={0.95} />
                      <stop offset="100%" stopColor={c} stopOpacity={0.28} />
                    </linearGradient>
                  )
                })}
              </defs>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="year" stroke={AXIS} tick={TICK} />
              <YAxis
                stroke={AXIS}
                tick={TICK}
                allowDecimals={false}
                domain={[0, countMax]}
                tickCount={countMax + 1}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#00000008' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {alertsPresent.map((level) => (
                <Bar
                  key={level}
                  dataKey={level}
                  stackId="al"
                  maxBarSize={72}
                  name={level}
                  fill={`url(#bar-al-${level})`}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="py-8 text-center text-xs text-faint">No alert levels recorded on these events.</div>
        )}
      </ChartCard>

      <ChartCard
        icon={ShieldOff}
        title="Insured exposure & PML over time"
        subtitle="Per event, oldest to newest — TIV at risk (bar) vs. PML and Protection Gap (lines)"
      >
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={financial} margin={{ top: 4, right: 8, bottom: 0, left: 4 }}>
            <defs>
              <linearGradient id="bar-tiv" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff6a2b" stopOpacity={0.7} />
                <stop offset="100%" stopColor="#ff6a2b" stopOpacity={0.14} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="date" stroke={AXIS} tick={TICK} />
            <YAxis stroke={AXIS} tick={TICK} tickFormatter={compactZAR} width={64} />
            <Tooltip content={<FinancialTooltip />} cursor={{ fill: '#00000008' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="tiv" name="TIV at risk" fill="url(#bar-tiv)" maxBarSize={72} />
            <Line dataKey="pml" name="PML" stroke="#e0454a" strokeWidth={2} dot={{ r: 3 }} />
            <Line dataKey="gap" name="Protection gap" stroke="#9a6b1e" strokeWidth={2} dot={{ r: 3 }} strokeDasharray="4 3" />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="mt-2 text-[10px] leading-relaxed text-faint">
          Events with no footprint or no intersecting assets show as zero exposure — they still count
          toward frequency above. PML uses the documented HAZUS-MH/FEMA band midpoint per hazard type
          and alert level, not a per-event vulnerability assessment.
        </div>
      </ChartCard>
    </div>
  )
}
