import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  KeyRound,
  Loader2,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  Zap,
} from 'lucide-react'
import {
  createTrigger,
  deleteTrigger,
  evaluateAllTriggers,
  getOperatorKey,
  setOperatorKey,
  updateTrigger,
} from '../api'
import { currency, getHazardColor, percent } from '../lib/theme'
import MetricCard from './MetricCard'
import { SkeletonCards, SkeletonRows } from './Skeleton'

const HAZARD_CODES = ['EQ', 'TC', 'FL', 'VO', 'WF', 'DR']
const ALERT_LEVELS = ['Green', 'Orange', 'Red']
const PAYOUT_KINDS = [
  { value: 'fixed', label: 'Fixed amount' },
  { value: 'per_asset', label: 'Per exposed asset' },
  { value: 'tiv_share', label: 'Share of exposed TIV' },
]

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

function basisRiskClass(value) {
  if (value > 0) return 'text-over' // policy overpays vs. modelled loss
  if (value < 0) return 'text-pml' // policy underpays — real shortfall risk
  return 'text-muted'
}

const FIELD = 'rounded border border-hair bg-ground px-2 py-1 text-xs text-ink'
const EMPTY = []

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

export default function ParametricPanel({ summary, triggers, firings, loading, error, onChanged }) {
  const [actionError, setActionError] = useState(null)
  const [evaluating, setEvaluating] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [showRuleForm, setShowRuleForm] = useState(false)

  const rules = triggers ?? EMPTY
  const ledger = firings ?? EMPTY

  const totalPayout = summary?.total_outstanding_payout ?? 0
  const totalBasis = summary?.total_basis_risk ?? 0

  const sortedLedger = useMemo(
    () => [...ledger].sort((a, b) => Math.abs(b.basis_risk) - Math.abs(a.basis_risk)),
    [ledger],
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

  if (loading && !summary) {
    return (
      <div className="mx-auto flex h-full max-w-5xl flex-col gap-5 p-6">
        <SkeletonCards count={4} hero />
        <SkeletonRows rows={3} />
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
            Index-based rules and the payout ledger. Basis risk = payout − modelled PML.
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
        glow={totalBasis > 0 ? '#cd7a12' : totalBasis < 0 ? '#e0454a' : '#ff6a2b'}
      />
      <div className="grid grid-cols-3 gap-3">
        <MetricCard
          icon={ShieldCheck}
          label="Active rules"
          value={`${summary?.active_rule_count ?? 0} / ${summary?.rule_count ?? 0}`}
        />
        <MetricCard
          icon={Zap}
          label="Outstanding payout"
          amount={totalPayout}
          format={currency}
          accent="text-brand"
        />
        <MetricCard
          icon={Play}
          label="Firings"
          amount={summary?.firing_count ?? 0}
          format={(n) => Math.round(n).toString()}
        />
      </div>

      {/* Rules ------------------------------------------------------------- */}
      <div className="overflow-hidden panel rounded-lg">
        <div className="flex items-center justify-between border-b border-hair px-4 py-2.5">
          <span className="text-sm font-semibold text-ink">Rules ({rules.length})</span>
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
        {rules.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-faint">
            No trigger rules yet. Create one to start evaluating events.
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-sunken text-[10px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Rule</th>
                  <th className="px-2 py-2 text-left font-medium">Conditions</th>
                  <th className="px-2 py-2 text-right font-medium">Payout</th>
                  <th className="px-2 py-2 text-center font-medium">Active</th>
                  <th className="px-4 py-2 text-right font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-hair">
                {rules.map((rule) => (
                  <tr key={rule.id} className="hover:bg-row">
                    <td className="px-4 py-2 text-ink">{rule.name}</td>
                    <td className="px-2 py-2 text-muted">{conditionSummary(rule)}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-ink">{payoutSummary(rule)}</td>
                    <td className="px-2 py-2 text-center">
                      <button
                        onClick={() => toggleActive(rule)}
                        disabled={busyId === rule.id}
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          rule.is_active
                            ? 'bg-ok/10 text-ok'
                            : 'bg-sunken text-muted'
                        } disabled:opacity-50`}
                      >
                        {rule.is_active ? 'On' : 'Off'}
                      </button>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => removeRule(rule)}
                        disabled={busyId === rule.id}
                        className="text-faint hover:text-pml disabled:opacity-50"
                        aria-label={`Delete rule ${rule.name}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Payout ledger --------------------------------------------------- */}
      <div className="overflow-hidden panel rounded-lg">
        <div className="border-b border-hair px-4 py-2.5 text-sm font-semibold text-ink">
          Payout ledger ({ledger.length})
        </div>
        {ledger.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-faint">
            No rules currently fire against any stored event.
          </div>
        ) : (
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-sunken text-[10px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Event</th>
                  <th className="px-2 py-2 text-left font-medium">Rule</th>
                  <th className="px-2 py-2 text-right font-medium">Payout</th>
                  <th className="px-2 py-2 text-right font-medium">Modelled loss</th>
                  <th className="px-4 py-2 text-right font-medium">Basis risk</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hair">
                {sortedLedger.map((f) => (
                  <tr key={f.id} className="hover:bg-row">
                    <td className="px-4 py-2 text-ink">
                      {f.event_name || `${f.event_type} ${f.event_id}`}
                      <span className="ml-1 text-faint">#{f.hazard_event_id}</span>
                    </td>
                    <td className="px-2 py-2 text-muted">{f.trigger_name}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-brand">{currency(f.payout_amount)}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{currency(f.modelled_loss)}</td>
                    <td className={`px-4 py-2 text-right tabular-nums ${basisRiskClass(f.basis_risk)}`}>
                      {currency(f.basis_risk)}
                      {f.basis_risk_pct != null && (
                        <span className="ml-1 text-[10px] text-faint">
                          ({f.basis_risk_pct > 0 ? '+' : ''}
                          {percent(f.basis_risk_pct)})
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-hair px-4 py-2 text-[10px] leading-relaxed text-faint">
          Basis risk is payout minus the modelled PML (a HAZUS-MH/FEMA damage-ratio estimate, not a
          measured loss). <span className="text-over">Amber</span> = the policy overpays for that
          event; <span className="text-pml">rose</span> = it underpays.
        </div>
      </div>
    </div>
  )
}
