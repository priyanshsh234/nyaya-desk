import { useCallback, useEffect, useState } from 'react'
import { ecourts } from '../api'
import * as I from '../icons'
import Captcha from './Captcha'
import CaseView from './CaseView'
import { Alert, Field, Skeleton, Spinner } from './ui'

const EXAMPLE_CNR = 'DLND020000602007'
// Matches the assignment's example; resolved by *label* against live
// dropdowns, because the portal's internal codes are not user-visible.
const EXAMPLE_CASE = {
  state: 'delhi', district: 'south', complex: 'saket', establishment: 'district and sessions judge',
  caseType: 'cs (comm)', caseNo: '233', year: '2024',
}

const findBy = (list, needle) => list.find((o) => o.label.toLowerCase().includes(needle))
const YEAR = new Date().getFullYear()

export default function CaseSearch() {
  // portal session
  const [sid, setSid] = useState('')
  const [states, setStates] = useState([])
  const [booting, setBooting] = useState(true)
  const [nonce, setNonce] = useState(0)

  // ui
  const [mode, setMode] = useState('cnr')
  const [captcha, setCaptcha] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [list, setList] = useState(null)

  // cnr form
  const [cnr, setCnr] = useState('')

  // case number form
  const [f, setF] = useState({ state: '', district: '', complex: '', est: '', caseType: '', caseNo: '', year: '' })
  const [opts, setOpts] = useState({ districts: [], complexes: [], ests: [], caseTypes: [] })
  const [loadingOpt, setLoadingOpt] = useState('')

  const refreshCaptcha = () => {
    setCaptcha('')
    setNonce((n) => n + 1)
  }

  const boot = useCallback(async () => {
    setBooting(true)
    setError(null)
    try {
      const s = await ecourts.newSession()
      setSid(s.session_id)
      setStates(s.states)
      setNonce((n) => n + 1)
      return s.session_id
    } catch (e) {
      setError(e)
      return ''
    } finally {
      setBooting(false)
    }
  }, [])

  useEffect(() => {
    boot()
  }, [boot])

  // Central error policy (mirrors the backend's typed errors):
  //  - session_expired -> transparently start a new portal session
  //  - anything after a submit -> captcha is consumed, so load a new one
  const handle = async (e, { afterSubmit = false } = {}) => {
    if (e.code === 'session_expired') {
      await boot()
      setError({ message: 'Your eCourts session expired, so a new one was started. Please enter the new captcha.', hint: e.hint })
      return
    }
    setError(e)
    if (afterSubmit) refreshCaptcha()
  }

  // ---------------------------------------------------- cascading dropdowns
  const cx = opts.complexes.find((c) => c.value === f.complex)

  const loadDistricts = async (state, s = sid) => {
    setF((x) => ({ ...x, state, district: '', complex: '', est: '', caseType: '' }))
    setOpts({ districts: [], complexes: [], ests: [], caseTypes: [] })
    if (!state) return []
    setLoadingOpt('districts')
    try {
      const d = await ecourts.districts(s, state)
      setOpts((o) => ({ ...o, districts: d }))
      return d
    } catch (e) {
      handle(e)
      return []
    } finally {
      setLoadingOpt('')
    }
  }

  const loadComplexes = async (district, state = f.state, s = sid) => {
    setF((x) => ({ ...x, district, complex: '', est: '', caseType: '' }))
    setOpts((o) => ({ ...o, complexes: [], ests: [], caseTypes: [] }))
    if (!district) return []
    setLoadingOpt('complexes')
    try {
      const c = await ecourts.complexes(s, { state_code: state, dist_code: district })
      setOpts((o) => ({ ...o, complexes: c }))
      return c
    } catch (e) {
      handle(e)
      return []
    } finally {
      setLoadingOpt('')
    }
  }

  const loadCaseTypes = async (p, s = sid) => {
    setLoadingOpt('caseTypes')
    try {
      const t = await ecourts.caseTypes(s, p)
      setOpts((o) => ({ ...o, caseTypes: t }))
      return t
    } catch (e) {
      handle(e)
      return []
    } finally {
      setLoadingOpt('')
    }
  }

  const onComplex = async (complex, district = f.district, state = f.state, s = sid, complexes = opts.complexes) => {
    setF((x) => ({ ...x, complex, est: '', caseType: '' }))
    setOpts((o) => ({ ...o, ests: [], caseTypes: [] }))
    if (!complex) return {}
    const meta = complexes.find((c) => c.value === complex)
    const base = { state_code: state, dist_code: district, complex_value: complex }
    setLoadingOpt('ests')
    let ests = []
    try {
      ests = await ecourts.establishments(s, base)
      setOpts((o) => ({ ...o, ests }))
    } catch (e) {
      handle(e)
    } finally {
      setLoadingOpt('')
    }
    // Case types can load right away unless the portal insists on an
    // establishment first.
    const types = meta?.requires_establishment ? [] : await loadCaseTypes(base, s)
    return { ests, types }
  }

  const onEst = async (est, s = sid, base = null) => {
    setF((x) => ({ ...x, est, caseType: '' }))
    setOpts((o) => ({ ...o, caseTypes: [] }))
    if (!est) return []
    return loadCaseTypes(base || { state_code: f.state, dist_code: f.district, complex_value: f.complex, est_code: est }, s)
  }

  // Walk the cascade by label so reviewers can try the documented example.
  const loadExample = async () => {
    setError(null)
    const s = sid || (await boot())
    const st = findBy(states, EXAMPLE_CASE.state)
    if (!st) return
    const d = findBy(await loadDistricts(st.value, s), EXAMPLE_CASE.district)
    if (!d) return
    const cxs = await loadComplexes(d.value, st.value, s)
    const c = findBy(cxs, EXAMPLE_CASE.complex)
    if (!c) return
    const { ests = [] } = await onComplex(c.value, d.value, st.value, s, cxs)
    const e = findBy(ests, EXAMPLE_CASE.establishment)
    let types = []
    if (e) {
      types = await onEst(e.value, s, { state_code: st.value, dist_code: d.value, complex_value: c.value, est_code: e.value })
    }
    const t = findBy(types, EXAMPLE_CASE.caseType)
    setF((x) => ({ ...x, caseType: t?.value || '', caseNo: EXAMPLE_CASE.caseNo, year: EXAMPLE_CASE.year }))
  }

  // ------------------------------------------------------------- submits
  const submitCnr = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setResult(await ecourts.searchCnr(sid, { cnr, captcha }))
      setList(null)
    } catch (err) {
      await handle(err, { afterSubmit: true })
    } finally {
      setBusy(false)
    }
  }

  const submitNumber = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await ecourts.searchCaseNumber(sid, {
        state_code: f.state, dist_code: f.district, complex_value: f.complex, est_code: f.est,
        case_type: f.caseType, case_no: f.caseNo, year: f.year, captcha,
      })
      setList(r)
      setResult(null)
      refreshCaptcha() // consumed by the portal even on success
    } catch (err) {
      await handle(err, { afterSubmit: true })
    } finally {
      setBusy(false)
    }
  }

  const openCase = async (row) => {
    setBusy(true)
    setError(null)
    try {
      setResult(await ecourts.get(row.details_url))
    } catch (err) {
      await handle(err)
    } finally {
      setBusy(false)
    }
  }

  // ------------------------------------------------------------- render
  if (result) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="no-print">
          <button className="btn btn-ghost" onClick={() => { setResult(null); refreshCaptcha() }}>
            <I.Search size={16} /> New search
          </button>
        </div>
        <CaseView result={result} onBack={list ? () => setResult(null) : null} />
      </div>
    )
  }

  const cnrValid = /^[A-Za-z]{4}\d{12}$/.test(cnr.replace(/[^A-Za-z0-9]/g, ''))
  const numValid = f.state && f.district && f.complex && f.caseType && /^\d{1,7}$/.test(f.caseNo) &&
    /^\d{4}$/.test(f.year) && (!cx?.requires_establishment || f.est)

  return (
    <div className="search-layout">
      <div className="card">
        <div className="card-pad">
          <div className="card-head">
            <div>
              <h2 className="card-title">Find a case</h2>
              <div className="card-sub">Live data from the eCourts District Court portal</div>
            </div>
            <div className="segmented" role="tablist">
              <button className={mode === 'cnr' ? 'active' : ''} onClick={() => { setMode('cnr'); setError(null) }}>
                <I.Hash size={15} /> CNR
              </button>
              <button className={mode === 'number' ? 'active' : ''} onClick={() => { setMode('number'); setError(null) }}>
                <I.Building size={15} /> Case number
              </button>
            </div>
          </div>

          {error && (
            <div style={{ marginBottom: 18 }}>
              <Alert title={error.message} onClose={() => setError(null)}>
                {error.hint && <div>{error.hint}</div>}
                {error.code === 'network' || (!sid && !booting) ? (
                  <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={boot}>
                    <I.Refresh size={14} /> Retry connection
                  </button>
                ) : null}
              </Alert>
            </div>
          )}

          {mode === 'cnr' ? (
            <form onSubmit={submitCnr} className="grid">
              <Field label="CNR number" required help="16 characters: 4-letter court code and 12 digits">
                <input
                  className="input input-lg mono"
                  value={cnr}
                  onChange={(e) => setCnr(e.target.value.toUpperCase())}
                  placeholder="e.g. DLND020000602007"
                  maxLength={20}
                  autoFocus
                />
              </Field>
              <div>
                <button type="button" className="example" onClick={() => setCnr(EXAMPLE_CNR)}>
                  <I.Sparkle size={13} /> Try {EXAMPLE_CNR}
                </button>
              </div>
              <Field label="Security check" required>
                <Captcha sid={sid} nonce={nonce} onRefresh={refreshCaptcha} value={captcha} onChange={setCaptcha} disabled={booting} />
              </Field>
              <div>
                <button className="btn btn-primary btn-lg" disabled={busy || booting || !cnrValid || !captcha}>
                  {busy ? <Spinner /> : <I.Search size={17} />} Search case
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={submitNumber}>
              <div className="court-bar">
                <div className="grid g2">
                  <Field label="State" required>
                    {booting ? <Skeleton h={44} /> : (
                      <select className="select" value={f.state} onChange={(e) => loadDistricts(e.target.value)}>
                        <option value="">Select state</option>
                        {states.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                      </select>
                    )}
                  </Field>
                  <Field label="District" required>
                    <select className="select" value={f.district} disabled={!opts.districts.length}
                      onChange={(e) => loadComplexes(e.target.value)}>
                      <option value="">{loadingOpt === 'districts' ? 'Loading…' : 'Select district'}</option>
                      {opts.districts.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Court complex" required>
                    <select className="select" value={f.complex} disabled={!opts.complexes.length}
                      onChange={(e) => onComplex(e.target.value)}>
                      <option value="">{loadingOpt === 'complexes' ? 'Loading…' : 'Select court complex'}</option>
                      {opts.complexes.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Establishment" required={!!cx?.requires_establishment}>
                    <select className="select" value={f.est} disabled={!opts.ests.length}
                      onChange={(e) => onEst(e.target.value)}>
                      <option value="">{loadingOpt === 'ests' ? 'Loading…' : 'Select establishment'}</option>
                      {opts.ests.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </Field>
                </div>
              </div>

              <div className="grid g4">
                <Field label="Case type" required className="span2">
                  <select className="select" value={f.caseType} disabled={!opts.caseTypes.length}
                    onChange={(e) => setF({ ...f, caseType: e.target.value })}>
                    <option value="">{loadingOpt === 'caseTypes' ? 'Loading…' : 'Select case type'}</option>
                    {opts.caseTypes.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </Field>
                <Field label="Case number" required>
                  <input className="input" inputMode="numeric" value={f.caseNo} maxLength={7} placeholder="e.g. 233"
                    onChange={(e) => setF({ ...f, caseNo: e.target.value.replace(/\D/g, '') })} />
                </Field>
                <Field label="Year" required>
                  <input className="input" inputMode="numeric" value={f.year} maxLength={4} placeholder={String(YEAR)}
                    onChange={(e) => setF({ ...f, year: e.target.value.replace(/\D/g, '') })} />
                </Field>
              </div>
              <div style={{ margin: '14px 0 18px' }}>
                <button type="button" className="example" onClick={loadExample} disabled={!!loadingOpt}>
                  {loadingOpt ? <Spinner /> : <I.Sparkle size={13} />} Load example: CS (COMM) 233/2024, Saket
                </button>
              </div>
              <Field label="Security check" required>
                <Captcha sid={sid} nonce={nonce} onRefresh={refreshCaptcha} value={captcha} onChange={setCaptcha} disabled={booting} />
              </Field>
              <div style={{ marginTop: 18 }}>
                <button className="btn btn-primary btn-lg" disabled={busy || booting || !numValid || !captcha}>
                  {busy ? <Spinner /> : <I.Search size={17} />} Search case
                </button>
              </div>
            </form>
          )}

          {list && mode === 'number' && (
            <div style={{ marginTop: 28 }}>
              <div className="section-label">{list.total} matching case{list.total === 1 ? '' : 's'}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {list.cases.map((r, i) => (
                  <div className="result-row" key={i}>
                    <div className="result-no">{r.sr_no || i + 1}</div>
                    <div>
                      <div className="result-title">
                        {r.petitioner || r.title}
                        {r.respondent && <><span className="vs">vs</span>{r.respondent}</>}
                      </div>
                      <div className="result-meta">
                        <span>{r.case_number}</span>
                        {r.establishment && <span>{r.establishment}</span>}
                        {r.cnr && <span>CNR {r.cnr}</span>}
                      </div>
                    </div>
                    <button className="btn btn-brass" onClick={() => openCase(r)} disabled={busy}>
                      {busy ? <Spinner /> : null} View <I.Arrow size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <aside className="card how">
        <div className="section-label">How it works</div>
        <ol>
          <li><div><b>We open a live eCourts session</b>Cookies and the rotating security token are held server-side for you.</div></li>
          <li><div><b>You solve the captcha</b>It is the portal's own image, proxied unchanged. We never bypass it.</div></li>
          <li><div><b>We replay the portal's requests</b>The same calls the official site makes, reproduced in Python.</div></li>
          <li><div><b>You get clean, structured data</b>Parties, hearings, orders with PDF links, and downloadable JSON.</div></li>
        </ol>
      </aside>
    </div>
  )
}
