const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// The /ingest/* and /parametric/* write + evaluate routes are gated by an
// optional shared secret. The dashboard keeps the operator's key in
// localStorage and sends it only on those mutating calls.
const OP_KEY_STORAGE = 'climrisk.operatorKey'

export function getOperatorKey() {
  try {
    return localStorage.getItem(OP_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setOperatorKey(value) {
  try {
    if (value) localStorage.setItem(OP_KEY_STORAGE, value)
    else localStorage.removeItem(OP_KEY_STORAGE)
  } catch {
    // storage unavailable (private window etc.) — key just won't persist
  }
}

async function request(path, { method = 'GET', body, auth = false } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const key = getOperatorKey()
    if (key) headers['X-API-Key'] = key
  }

  let res
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    const err = new Error('Could not reach the ClimRisk API — is the backend running?')
    err.status = 0
    throw err
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const parsed = await res.json()
      detail = parsed.detail || detail
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    const err = new Error(typeof detail === 'string' ? detail : 'Request failed')
    err.status = res.status
    throw err
  }

  if (res.status === 204) return null
  return res.json()
}

export const fetchHazards = () => request('/hazards')
export const fetchAssets = () => request('/assets')
export const fetchIntersection = (hazardEventId) => request(`/exposure/intersect/${hazardEventId}`)
export const fetchTrends = () => request('/trends/hazards')

// --- Parametric triggers --------------------------------------------------- //

export const fetchParametricSummary = () => request('/parametric/summary')
export const fetchTriggers = () => request('/parametric/triggers')
export const fetchFirings = () => request('/parametric/firings')

export const createTrigger = (rule) =>
  request('/parametric/triggers', { method: 'POST', body: rule, auth: true })

export const updateTrigger = (id, changes) =>
  request(`/parametric/triggers/${id}`, { method: 'PATCH', body: changes, auth: true })

export const deleteTrigger = (id) =>
  request(`/parametric/triggers/${id}`, { method: 'DELETE', auth: true })

export const evaluateAllTriggers = () =>
  request('/parametric/evaluate', { method: 'POST', auth: true })

// --- Disclosure report --------------------------------------------------- //

function periodQuery(from, to) {
  const p = new URLSearchParams()
  if (from) p.set('from', from)
  if (to) p.set('to', to)
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const fetchDisclosure = (from, to) => request(`/reports/disclosure${periodQuery(from, to)}`)

// Printable HTML lives on the API origin; open it directly (a navigation, not a fetch).
export const disclosureHtmlUrl = (from, to) =>
  `${API_BASE}/reports/disclosure.html${periodQuery(from, to)}`
