// Thin fetch wrapper. All backend errors share one shape:
//   { detail: { code, message, hint } }            (scraper errors)
//   { detail: { code: 'validation_error', fields } } (draft form errors)
//   { detail: [ ...pydantic errors ] }             (request schema errors)
// We normalise them into an ApiError so components only handle one type.

// Empty in dev (Vite proxy) and when FastAPI serves the build. Set
// VITE_API_BASE only if the frontend is hosted separately from the API.
export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, detail) {
    const d = detail || {}
    let message = 'Something went wrong.'
    if (typeof d === 'string') message = d
    else if (Array.isArray(d)) message = d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join('; ')
    else if (d.message) message = d.message
    super(message)
    this.status = status
    this.code = d.code || (status === 422 ? 'validation_error' : 'error')
    this.hint = d.hint
    this.fields = d.fields || {}
  }
}

async function request(path, { method = 'GET', body, raw = false } = {}) {
  let res
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, { code: 'network', message: 'Cannot reach the server. Is the backend running?' })
  }
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      detail = { message: `Server error (HTTP ${res.status}).` }
    }
    throw new ApiError(res.status, detail)
  }
  return raw ? res : res.json()
}

const qs = (o) => new URLSearchParams(o).toString()

// Cheap liveness probe: answers instantly once the server process is up,
// so a slow reply here means "server waking up", not "portal is slow".
export const health = () => request('/api/health')

export const ecourts = {
  newSession: () => request('/api/ecourts/sessions', { method: 'POST' }),
  captchaUrl: (sid, nonce) => `${API_BASE}/api/ecourts/sessions/${sid}/captcha?n=${nonce}`,
  districts: (sid, state_code) => request(`/api/ecourts/sessions/${sid}/districts?${qs({ state_code })}`),
  complexes: (sid, p) => request(`/api/ecourts/sessions/${sid}/complexes?${qs(p)}`),
  establishments: (sid, p) => request(`/api/ecourts/sessions/${sid}/establishments?${qs(p)}`),
  caseTypes: (sid, p) => request(`/api/ecourts/sessions/${sid}/case-types?${qs(p)}`),
  searchCnr: (sid, body) => request(`/api/ecourts/sessions/${sid}/search/cnr`, { method: 'POST', body }),
  searchCaseNumber: (sid, body) =>
    request(`/api/ecourts/sessions/${sid}/search/case-number`, { method: 'POST', body }),
  get: (path) => request(path),
  abs: (path) => API_BASE + path,
}

export const drafts = {
  templates: () => request('/api/drafts/templates'),
  generate: (id, data) => request(`/api/drafts/${id}`, { method: 'POST', body: data }),
  docx: async (id, data) => {
    const res = await request(`/api/drafts/${id}/docx`, { method: 'POST', body: data, raw: true })
    const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || 'draft.docx'
    return { blob: await res.blob(), name }
  },
}

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
