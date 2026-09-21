import { useMemo, useState } from 'react'
import { AlertOctagon, AlertTriangle, KeyRound, Loader2, Play, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import {
  createTrigger,
  deleteTrigger,
  evaluateAllTriggers,
  getOperatorKey,
  setOperatorKey,
  updateTrigger,
} from '../api'
import { ACCENT, compactCurrency, currency, getHazardColor, percent } from '../lib/theme'
import MetricCard from './MetricCard'
import { SkeletonCard, SkeletonRows } from './Skeleton'

const HAZARD_CODES = ['EQ', 'TC', 'FL', 'VO', 'WF', 'DR']
const ALERT_LEVELS = ['Green', 'Orange', 'Red']
const PAYOUT_KINDS = [
  { value: 'fixed', label: 'Fixed amount' },
  { value: 'per_asset', label: 'Per exposed asset' },
  { value: 'tiv_share', label: 'Share of exposed TIV' },
]

// ── Ledger bar scale ───────────────────────────────────────────────────────
// Swappable: 'linear' keeps magnitude honest (a +1063% firing draws ~1.8× a
// +576% one); 'compressed' log-scales so both read as loudly wrong without the
// larger dwarfing the smaller. The header toggle overrides this default.
const LEDGER_SCALE_DEFAULT = 'linear'

// Returns { widthPct: 0–50 (share of the half-track), over: bool } for one firing.
// Sized on vertical_basis_risk — the magnitude component (payout vs. modelled
// loss); horizontal_basis_risk_flag and spatial_basis_risk_pct are shown
// separately (see LedgerRow) since they're different axes, not more magnitude.
function barGeometry(firing, domainMax, mode) {
  const br = firing.vertical_basis_risk ?? 0
  const over = br > 0
  if (br === 0) return { widthPct: 0, over }
  const pct = firing.vertical_basis_risk_pct
  // Undefined ratio (a real payout against zero modelled loss) = unbounded
  // overpay — pin it to the full half-track.
  if (pct == null) return { widthPct: 50, over }
  const mag = Math.abs(pct)
  const dm = Math.max(domainMax, 1e-6)
  const frac = mode === 'compressed' ? Math.log1p(mag) / Math.log1p(dm) : mag / dm
  return { widthPct: Math.max(Math.min(frac, 1) * 50, 3), over }
}

function conditionSummary(t) {
  const parts = []
  parts.push(t.event_type ? getHazardColor(t.event_type).label : 'Any hazard')
  if (t.min_alert_level) parts.push(`alert ≥ ${t.min_alert_level}`)
  if (t.min_severity_value != null) parts.push(`severity ≥ ${t.min_severity_value}`)
  if (t.iso3) parts.push(t.iso3)
  parts.push(t.requires_exposed_assets ? 'must hit an asset' : 'index only')
  return parts.join(' · ')
}

function payoutSummary(t) {
  if (t.payout_kind === 'fixed') return `${currency(t.payout_value)} flat`
  if (t.payout_kind === 'per_asset') return `${currency(t.payout_value)} / asset`
  if (t.payout_kind === 'tiv_share') return `${percent(t.payout_value)} of exposed TIV`
  return `${t.payout_value}`
}

function verticalBasisRiskClass(value) {
  if (value > 0) return 'text-over' // policy overpays vs. modelled loss
  if (value < 0) return 'text-pml' // policy underpays — real shortfall risk
  return 'text-muted'
}

const FIELD = 'rounded border border-hair bg-ground px-2 py-1 text-xs text-ink'
const EMPTY = []

const STARTER_RULE = {
  name: 'Flood · Orange · exposed',
  event_type: 'FL',
  min_alert_level: 'Orange',
  min_severity_value: null,
  requires_exposed_assets: true,
  payout_kind: 'fixed',
  payout_value: 10_000_000,
}

function OperatorKeyStrip({ onChange }) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(getOperatorKey())
  const stored = getOperatorKey()

  return (
    <div className="flex items-center gap-2 text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded border px-2 py-1 ${
          stored ? 'border-ok/40 text-ok' : 'border-hair text-muted'
        } hover:text-ink`}
      >
        <KeyRound className="h-3.5 w-3.5" />
        {stored ? 'Operator key set' : 'Operator key'}
      </button>
      {open && (
        <>
          <input
            type="password"
            value={value}
            placeholder="X-API-Key for writes"
            onChange={(e) => setValue(e.target.value)}
            className={`${FIELD} w-52`}
          />
          <button
            onClick={() => {
              setOperatorKey(value.trim())
              onChange?.()
              setOpen(false)
            }}
            className="rounded border border-hair px-2 py-1 text-ink hover:bg-sunken"
          >
            Save
          </button>
        </>
      )}
    </div>
  )
}

const BLANK_RULE = {
  name: '',
  event_type: '',
  min_alert_level: '',
  min_severity_value: '',
  requires_exposed_assets: true,
  payout_kind: 'fixed',
  payout_value: '',
}

function RuleForm({ onCreated, onError, onCancel }) {
  const [form, setForm] = useState(BLANK_RULE)
  const [saving, setSaving] = useState(false)

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    onError(null)
    try {
      await createTrigger({
        name: form.name.trim(),
        event_type: form.event_type || null,
        min_alert_level: form.min_alert_level || null,
        min_severity_value: form.min_severity_value === '' ? null : Number(form.min_severity_value),
        requires_exposed_assets: form.requires_exposed_assets,
        payout_kind: form.payout_kind,
        payout_value: Number(form.payout_value),
      })
      setForm(BLANK_RULE)
      onCreated()
    } catch (err) {
      onError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 bg-sunken p-3 sm:grid-cols-3">
      <label className="col-span-2 flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted sm:col-span-3">
        Name
        <input required value={form.name} onChange={(e) => set('name', e.target.value)} className={FIELD} />
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
        Hazard type
        <select value={form.event_type} onChange={(e) => set('event_type', e.target.value)} className={FIELD}>
          <option value="">Any</option>
          {HAZARD_CODES.map((c) => (
            <option key={c} value={c}>
              {getHazardColor(c).label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
        Min alert level
        <select value={form.min_alert_level} onChange={(e) => set('min_alert_level', e.target.value)} className={FIELD}>
          <option value="">Any</option>
          {ALERT_LEVELS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
        Min severity (optional)
        <input
          type="number"
          step="any"
          value={form.min_severity_value}
          onChange={(e) => set('min_severity_value', e.target.value)}
          className={FIELD}
        />
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
        Payout kind
        <select value={form.payout_kind} onChange={(e) => set('payout_kind', e.target.value)} className={FIELD}>
          {PAYOUT_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted">
        {form.payout_kind === 'tiv_share' ? 'Payout value (0–1)' : 'Payout value (ZAR)'}
        <input
          required
          type="number"
          step="any"
          min="0"
          value={form.payout_value}
          onChange={(e) => set('payout_value', e.target.value)}
          className={FIELD}
        />
      </label>

      <label className="flex items-center gap-2 self-end text-xs text-ink">
        <input
          type="checkbox"
          checked={form.requires_exposed_assets}
          onChange={(e) => set('requires_exposed_assets', e.target.checked)}
          className="accent-brand"
        />
        Requires an exposed asset
      </label>

      <div className="col-span-2 flex items-center gap-2 sm:col-span-3">
        <button
          type="submit"
          disabled={saving}
          className="flex items-center gap-1.5 rounded bg-brand px-3 py-1 text-xs font-medium text-white hover:bg-brandink disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Create rule
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-hair px-3 py-1 text-xs text-muted hover:bg-sunken"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

// Designed empty state — a real prompt, not a fallback line of grey text.
function StarterRulePrompt({ onCreateStarter, onCustom, creating }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-brandsoft text-brand">
        <ShieldAlert className="h-5 w-5" />
      </div>
      <div>
        <div className="text-sm font-semibold text-ink">No parametric rules yet</div>
        <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted">
          Index-based cover pays a fixed amount the moment a measurable condition on a hazard
          event is met — no loss adjustment. Start with a common one:
        </p>
      </div>
      <div className="w-full max-w-sm rounded-lg border border-hair bg-sunken px-4 py-3 text-left">
        <div className="text-xs font-medium text-ink">Flood · alert ≥ Orange · hits an insured asset</div>
        <div className="mt-0.5 text-[11px] text-muted">→ pays R 10,000,000 flat</div>
        <button
          onClick={onCreateStarter}
          disabled={creating}
          className="mt-2.5 flex items-center gap-1.5 rounded bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brandink disabled:opacity-50"
        >
          {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Create this rule
        </button>
      </div>
      <button
        onClick={onCustom}
        className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
      >
        or build a custom rule
      </button>
    </div>
  )
}

export default function ParametricPanel({ summary, triggers, firings, loading, error, onChanged }) {
  const [actionError, setActionError] = useState(null)
  const [evaluating, setEvaluating] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [showRuleForm, setShowRuleForm] = useState(false)
  const [creatingStarter, setCreatingStarter] = useState(false)
  const [scale, setScale] = useState(LEDGER_SCALE_DEFAULT)

  const rules = triggers ?? EMPTY
  const ledger = firings ?? EMPTY

  const totalPayout = summary?.total_outstanding_payout ?? 0
  const totalBasis = summary?.total_basis_risk ?? 0

  const sortedLedger = useMemo(
    () => [...ledger].sort((a, b) => Math.abs(b.vertical_basis_risk) - Math.abs(a.vertical_basis_risk)),
    [ledger],
  )
  const domainMax = useMemo(
    () => Math.max(0, ...sortedLedger.map((f) => Math.abs(f.vertical_basis_risk_pct ?? 0))),
    [sortedLedger],
  )

  const runEvaluateAll = async () => {
    setEvaluating(true)
    setActionError(null)
    try {
      await evaluateAllTriggers()
      onChanged()
    } catch (err) {
      setActionError(err)
    } finally {
      setEvaluating(false)
    }
  }

  const toggleActive = async (rule) => {
    setBusyId(rule.id)
    setActionError(null)
    try {
      await updateTrigger(rule.id, { is_active: !rule.is_active })
      onChanged()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusyId(null)
    }
  }

  const removeRule = async (rule) => {
    setBusyId(rule.id)
    setActionError(null)
    try {
      await deleteTrigger(rule.id)
      onChanged()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusyId(null)
    }
  }

  const createStarterRule = async () => {
    setCreatingStarter(true)
    setActionError(null)
    try {
      await createTrigger(STARTER_RULE)
      onChanged()
    } catch (err) {
      setActionError(err)
    } finally {
      setCreatingStarter(false)
    }
  }

  if (loading && !summary) {
    return (
      <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
        <SkeletonCard hero />
        <SkeletonRows rows={2} />
        <SkeletonRows rows={4} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-pml" />
        <div className="text-sm text-muted">{error}</div>
        <button
          onClick={onChanged}
          className="rounded border border-hair px-3 py-1.5 text-xs text-ink hover:bg-sunken"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 overflow-y-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Parametric trigger engine</h2>
          <p className="text-[11px] text-muted">
            Index-based rules and the payout ledger. Basis risk splits into magnitude (bar below),
            kind mismatch (<AlertOctagon className="inline h-3 w-3 align-[-1px]" /> badge), and —
            for tiv_share/per_asset payouts — a spatial-sizing component.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <OperatorKeyStrip onChange={onChanged} />
          <button
            onClick={runEvaluateAll}
            disabled={evaluating}
            className="flex items-center gap-1.5 rounded border border-hair px-2.5 py-1 text-xs text-ink hover:bg-sunken disabled:opacity-50"
          >
            {evaluating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            Re-evaluate all events
          </button>
        </div>
      </div>

      {actionError && (
        <div className="flex items-center gap-2 rounded border border-pml/30 bg-pml/10 px-3 py-2 text-xs text-pml">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            {actionError.status === 401
              ? 'This action needs a valid operator key — set it with the key button above.'
              : actionError.message || 'Action failed.'}
          </span>
        </div>
      )}

      <MetricCard
        icon={AlertTriangle}
        label="Net basis risk"
        amount={totalBasis}
        format={currency}
        hero
        glow={totalBasis > 0 ? ACCENT.over : totalBasis < 0 ? ACCENT.pml : ACCENT.brand}
      />

      {/* supporting stats — thin strip, secondary to the ledger below */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-0.5 text-xs text-muted">
        <span>
          Active rules{' '}
          <b className="font-semibold tabular-nums text-ink">
            {summary?.active_rule_count ?? 0}/{summary?.rule_count ?? 0}
          </b>
        </span>
        <span className="text-hair">·</span>
        <span>
          Outstanding payout <b className="font-semibold tabular-nums text-brand">{currency(totalPayout)}</b>
        </span>
        <span className="text-hair">·</span>
        <span>
          Firings <b className="font-semibold tabular-nums text-ink">{summary?.firing_count ?? 0}</b>
        </span>
      </div>

      {/* ── Rules — compact strip ─────────────────────────────────────────── */}
      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-hair px-4 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            Rules ({rules.length})
          </span>
          <button
            onClick={() => {
              setShowRuleForm((v) => !v)
              setActionError(null)
            }}
            className="flex items-center gap-1.5 rounded border border-hair px-2.5 py-1 text-xs text-ink hover:bg-sunken"
          >
            <Plus className={`h-3.5 w-3.5 transition-transform ${showRuleForm ? 'rotate-45' : ''}`} />
            {showRuleForm ? 'Close' : 'New rule'}
          </button>
        </div>
        {showRuleForm && (
          <div className="border-b border-hair">
            <RuleForm
              onCreated={() => {
                setShowRuleForm(false)
                onChanged()
              }}
              onError={setActionError}
              onCancel={() => setShowRuleForm(false)}
            />
          </div>
        )}
        {rules.length === 0 && !showRuleForm ? (
          <StarterRulePrompt
            onCreateStarter={createStarterRule}
            onCustom={() => setShowRuleForm(true)}
            creating={creatingStarter}
          />
        ) : (
          rules.length > 0 && (
            <div className="flex flex-wrap gap-2 p-3">
              {rules.map((rule) => (
                <div
                  key={rule.id}
                  className="flex min-w-[230px] flex-1 flex-col gap-1.5 rounded-lg border border-hair bg-sunken/60 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-medium text-ink">{rule.name}</span>
                    <button
                      onClick={() => removeRule(rule)}
                      disabled={busyId === rule.id}
                      className="shrink-0 text-faint hover:text-pml disabled:opacity-50"
                      aria-label={`Delete rule ${rule.name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="text-[10px] leading-relaxed text-faint">{conditionSummary(rule)}</div>
                  <div className="mt-0.5 flex items-center justify-between">
                    <span className="text-[11px] tabular-nums text-ink">{payoutSummary(rule)}</span>
                    <button
                      onClick={() => toggleActive(rule)}
                      disabled={busyId === rule.id}
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                        rule.is_active ? 'bg-ok/10 text-ok' : 'bg-surface text-muted'
                      } disabled:opacity-50`}
                    >
                      {rule.is_active ? 'On' : 'Off'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>

      {/* ── Payout ledger — the anchor ───────────────────────────────────── */}
      <div className="panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hair px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-ink">Payout ledger</div>
            <div className="text-[11px] text-muted">
              {ledger.length} outstanding {ledger.length === 1 ? 'firing' : 'firings'} ·{' '}
              {currency(totalPayout)} committed
            </div>
          </div>
          {ledger.length > 0 && (
            <div className="flex items-center gap-1 rounded bg-sunken p-0.5 text-[10px] font-medium">
              {[
                ['linear', 'Linear'],
                ['compressed', 'Log'],
              ].map(([m, lbl]) => (
                <button
                  key={m}
                  onClick={() => setScale(m)}
                  className={`rounded px-2 py-0.5 ${
                    scale === m ? 'bg-surface text-brand shadow-sm' : 'text-muted hover:text-ink'
                  }`}
                >
                  {lbl}
                </button>
              ))}
            </div>
          )}
        </div>

        {ledger.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
            <Play className="h-6 w-6 text-faint" />
            <div className="text-xs font-medium text-ink">No rules fire against any stored event</div>
            <p className="max-w-xs text-[11px] text-muted">
              {rules.length} rule{rules.length === 1 ? '' : 's'} defined. Run an evaluation to test
              them against every ingested event.
            </p>
            <button
              onClick={runEvaluateAll}
              disabled={evaluating}
              className="mt-1 flex items-center gap-1.5 rounded bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brandink disabled:opacity-50"
            >
              {evaluating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Re-evaluate all events
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-4 pb-1.5 pt-2.5 text-[10px] text-faint">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-pml/70" />
                underpays — shortfall risk
              </span>
              <span className="font-medium text-muted">modelled loss</span>
              <span className="flex items-center gap-1.5">
                overpays — premium inefficiency
                <span className="h-2 w-3 rounded-sm bg-over/70" />
              </span>
            </div>
            <div className="max-h-[22rem] overflow-y-auto">
              {sortedLedger.map((f) => {
                const g = barGeometry(f, domainMax, scale)
                const tone = verticalBasisRiskClass(f.vertical_basis_risk)
                return (
                  <div
                    key={f.id}
                    className="grid grid-cols-[minmax(0,8.5rem)_1fr_5.75rem] items-center gap-3 border-t border-hair px-4 py-2.5 first:border-t-0 hover:bg-row"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1 truncate text-xs font-medium text-ink">
                        <span className="truncate">{f.event_name || `${f.event_type} ${f.event_id}`}</span>
                        <span className="font-normal text-faint">#{f.hazard_event_id}</span>
                        {f.horizontal_basis_risk_flag && (
                          <AlertOctagon
                            className="h-3 w-3 shrink-0 text-over"
                            aria-label="Kind mismatch"
                            title="Kind mismatch: paid on the index with no real exposure behind it, or real exposure this rule stayed silent on."
                          />
                        )}
                      </div>
                      <div className="truncate text-[10px] text-muted">{f.trigger_name}</div>
                    </div>

                    <div className="min-w-0">
                      <div className="relative h-4 overflow-hidden rounded bg-sunken">
                        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-hair" />
                        <div
                          className={`absolute inset-y-[3px] transition-[width] duration-500 ${
                            g.over ? 'left-1/2 rounded-r bg-over' : 'right-1/2 rounded-l bg-pml'
                          }`}
                          style={{ width: `${g.widthPct}%` }}
                        />
                      </div>
                      <div className="mt-1 flex justify-between text-[10px] text-faint">
                        <span>payout {compactCurrency(f.payout_amount)}</span>
                        <span>modelled loss {compactCurrency(f.modelled_loss)}</span>
                      </div>
                      {f.spatial_basis_risk_pct != null && (
                        <div
                          className="mt-0.5 truncate text-[10px] text-faint"
                          title="Share of the gap attributable to sizing off flat TIV/asset count rather than where the exposed assets actually sit."
                        >
                          spatial {f.spatial_basis_risk_pct > 0 ? '+' : ''}
                          {percent(f.spatial_basis_risk_pct)}
                        </div>
                      )}
                    </div>

                    <div className="text-right">
                      <div className={`text-xs font-semibold tabular-nums ${tone}`}>
                        {f.vertical_basis_risk > 0 ? '+' : ''}
                        {compactCurrency(f.vertical_basis_risk)}
                      </div>
                      <div className="text-[10px] tabular-nums text-faint">
                        {f.vertical_basis_risk_pct != null
                          ? `${f.vertical_basis_risk_pct > 0 ? '+' : ''}${percent(f.vertical_basis_risk_pct)}`
                          : 'no modelled loss'}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}

        <div className="border-t border-hair px-4 py-2.5 text-[10px] leading-relaxed text-faint">
          Bars scale by vertical basis-risk % (payout vs. modelled PML, itself a distance-decayed
          HAZUS-MH/FEMA band estimate, not a measured loss){' '}
          {scale === 'compressed'
            ? '(log-compressed, so extreme values stay on-scale)'
            : '(linear — the largest fills the half-track)'}
          . <span className="text-over">Amber</span> overpays, <span className="text-pml">rose</span>{' '}
          underpays. <AlertOctagon className="inline h-3 w-3 align-[-1px] text-over" /> flags a kind
          mismatch (paid on no exposure, or exposure with no payout); "spatial" shows how much of a
          tiv_share/per_asset payout's gap owes to ignoring where assets sit, not just their TIV.
        </div>
      </div>
    </div>
  )
}
