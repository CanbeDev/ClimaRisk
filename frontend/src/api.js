const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function getJSON(path) {
  let res
  try {
    res = await fetch(`${API_BASE}${path}`)
  } catch {
    const err = new Error('Could not reach the ClimRisk API — is the backend running?')
    err.status = 0
    throw err
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || detail
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }

  return res.json()
}

export function fetchHazards() {
  return getJSON('/hazards')
}

export function fetchAssets() {
  return getJSON('/assets')
}

export function fetchIntersection(hazardEventId) {
  return getJSON(`/exposure/intersect/${hazardEventId}`)
}

export function fetchTrends() {
  return getJSON('/trends/hazards')
}
