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
import { AlertTriangle, CalendarRange, Layers, Loader2, ShieldOff, TrendingDown } from 'lucide-react'
import { currency, DEFAULT_HAZARD_COLOR, getAlertColor, HAZARD_COLORS } from '../lib/theme'
import MetricCard from './MetricCard'

const EMPTY = []

const AXIS = '#475569' // slate-600
const TICK = { fill: '#94a3b8', fontSize: 11 } // slate-400
const GRID = '#1e293b' // slate-800
const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
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
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </div>
      {subtitle && <div className="mt-0.5 text-[11px] text-slate-600">{subtitle}</div>}
      <div className="mt-3">{children}</div>
    </div>
  )
}

function FinancialTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2 text-slate-200">
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
      <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading hazard history…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-rose-500" />
        <div className="text-sm text-slate-400">{error}</div>
        <button
          onClick={onRetry}
          className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!events.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <CalendarRange className="h-10 w-10 text-slate-700" />
        <div className="max-w-sm text-sm text-slate-500">
          No hazard events ingested yet for {trends?.country || 'this country'}. Run a backfill to
          populate the historical view.
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 overflow-y-auto p-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-200">Historical hazard &amp; exposure trend</h2>
        <p className="text-[11px] text-slate-500">
          Every ingested event for {trends?.country || '—'}, over time. Exposure figures reuse the same
          TIV / PML / Protection-Gap logic as the per-event panel.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard icon={CalendarRange} label="Events" value={summary.total} />
        <MetricCard icon={CalendarRange} label="Span" value={summary.span} />
        <MetricCard
          icon={Layers}
          label="With exposed assets"
          value={summary.withExposure}
          accent="text-cyan-400"
        />
        <MetricCard
          icon={TrendingDown}
          label="Peak event PML"
          value={summary.peakPml ? compactZAR(summary.peakPml.probable_maximum_loss) : '—'}
          accent="text-rose-400"
        />
      </div>

      <ChartCard
        icon={Layers}
        title="Hazard frequency by year"
        subtitle="Event count per year, stacked by GDACS hazard type"
      >
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={byYearType} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="year" stroke={AXIS} tick={TICK} />
            <YAxis
              stroke={AXIS}
              tick={TICK}
              allowDecimals={false}
              domain={[0, countMax]}
              tickCount={countMax + 1}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#1e293b55' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {hazardsPresent.map((code) => (
              <Bar
                key={code}
                dataKey={code}
                stackId="hz"
                maxBarSize={72}
                name={(HAZARD_COLORS[code] || DEFAULT_HAZARD_COLOR).label}
                fill={(HAZARD_COLORS[code] || DEFAULT_HAZARD_COLOR).fill}
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
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="year" stroke={AXIS} tick={TICK} />
              <YAxis
                stroke={AXIS}
                tick={TICK}
                allowDecimals={false}
                domain={[0, countMax]}
                tickCount={countMax + 1}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#1e293b55' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {alertsPresent.map((level) => (
                <Bar
                  key={level}
                  dataKey={level}
                  stackId="al"
                  maxBarSize={72}
                  name={level}
                  fill={getAlertColor(level)}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="py-8 text-center text-xs text-slate-600">No alert levels recorded on these events.</div>
        )}
      </ChartCard>

      <ChartCard
        icon={ShieldOff}
        title="Insured exposure & PML over time"
        subtitle="Per event, oldest to newest — TIV at risk (bar) vs. PML and Protection Gap (lines)"
      >
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={financial} margin={{ top: 4, right: 8, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="date" stroke={AXIS} tick={TICK} />
            <YAxis stroke={AXIS} tick={TICK} tickFormatter={compactZAR} width={64} />
            <Tooltip content={<FinancialTooltip />} cursor={{ fill: '#1e293b55' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="tiv" name="TIV at risk" fill="#22d3ee" fillOpacity={0.55} maxBarSize={72} />
            <Line dataKey="pml" name="PML" stroke="#f43f5e" strokeWidth={2} dot={{ r: 3 }} />
            <Line dataKey="gap" name="Protection gap" stroke="#fb923c" strokeWidth={2} dot={{ r: 3 }} strokeDasharray="4 3" />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="mt-2 text-[10px] leading-relaxed text-slate-600">
          Events with no footprint or no intersecting assets show as zero exposure — they still count
          toward frequency above. PML uses the documented HAZUS-MH/FEMA band midpoint per hazard type
          and alert level, not a per-event vulnerability assessment.
        </div>
      </ChartCard>
    </div>
  )
}
