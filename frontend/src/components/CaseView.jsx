import { useMemo, useState } from 'react'
import { downloadBlob, ecourts } from '../api'
import * as I from '../icons'
import { Alert, JsonView, Spinner, initials, useToast } from './ui'

// Renders the structured case JSON returned by the backend as a "dossier".
// Every section tolerates missing data: the portal omits sections freely
// (no orders yet, no FIR for civil cases, ...).

const ACRONYMS = { cnr: 'CNR', fir: 'FIR', ia: 'IA', e: 'e-' }
const pretty = (k) =>
  k.split('_').map((w) => ACRONYMS[w] || w.charAt(0).toUpperCase() + w.slice(1)).join(' ').replace('e- ', 'e-')

function caseStatus(cs) {
  const text = `${cs.case_status || ''} ${cs.nature_of_disposal || ''} ${cs.case_stage || ''}`.toLowerCase()
  if (cs.decision_date || text.includes('disposed') || text.includes('decided')) return 'disposed'
  return 'pending'
}

function KV({ data, exclude = [] }) {
  const rows = Object.entries(data || {}).filter(([k, v]) => v && !exclude.includes(k))
  if (!rows.length) return null
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div className="kv-row" key={k}>
          <dt>{pretty(k)}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function DataTable({ rows }) {
  const cols = useMemo(() => {
    const set = new Set()
    rows.forEach((r) => Object.keys(r).forEach((k) => !k.endsWith('_ref') && !k.endsWith('_url') && set.add(k)))
    return [...set]
  }, [rows])
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{pretty(c)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{r[c] ?? ''}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Empty({ icon: Icon = I.File, children }) {
  return (
    <div className="empty">
      <Icon size={32} />
      <div>{children}</div>
    </div>
  )
}

function PartyList({ title, parties, kind }) {
  return (
    <div className="party-col">
      <h4>{title}</h4>
      {parties.length === 0 && <div className="party-det">Not listed</div>}
      {parties.map((p, i) => (
        <div className={`party ${kind}`} key={i}>
          <div className="avatar">{initials(p.name)}</div>
          <div>
            <div className="party-name">{p.name}</div>
            {p.advocate && (
              <div className="party-adv">
                <I.Gavel size={13} /> Adv. {p.advocate}
              </div>
            )}
            {p.details && <div className="party-det">{p.details}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}

function Hearing({ h, next }) {
  const [biz, setBiz] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  if (h.note) return <div className="tl-item"><div className="tl-meta">{h.note}</div></div>
  const date = h.hearing_date || h.business_on_date || '—'
  const loadBusiness = async () => {
    setLoading(true)
    setErr('')
    try {
      setBiz(await ecourts.get(h.business_url))
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className={`tl-item ${next ? 'next' : ''}`}>
      <div className="tl-date">{date}</div>
      <div className="tl-purpose">{h.purpose_of_hearing || h.purpose || 'Hearing'}</div>
      <div className="tl-meta">
        {h.judge && <span>{h.judge}</span>}
        {h.business_on_date && <span>Business on {h.business_on_date}</span>}
        {h.business_url && !biz && (
          <button className="btn btn-text btn-sm" onClick={loadBusiness} disabled={loading}>
            {loading ? <Spinner /> : <I.Book size={14} />} What happened
          </button>
        )}
      </div>
      {err && <div className="tl-business" style={{ color: 'var(--red)' }}>{err}</div>}
      {biz && <div className="tl-business">{biz.fields?.business || biz.text}</div>}
    </div>
  )
}

export default function CaseView({ result, onBack }) {
  const toast = useToast()
  const c = result.case
  const cd = c.case_details || {}
  const cs = c.case_status || {}
  const status = caseStatus(cs)
  const pet = c.petitioners || []
  const res = c.respondents || []
  // Most recent hearing first; the portal lists oldest first.
  const hearings = [...(c.hearing_history || [])].reverse()
  const orders = c.orders || []
  const extra = [
    ...(c.acts?.length ? [{ heading: 'Acts', rows: c.acts }] : []),
    ...(c.ia_status?.length ? [{ heading: 'IA Status', rows: c.ia_status }] : []),
    ...(c.transfers?.length ? [{ heading: 'Transfers', rows: c.transfers }] : []),
    ...(c.other_sections || []),
  ]
  const [tab, setTab] = useState('overview')

  const tabs = [
    ['overview', 'Overview', I.File],
    ['parties', 'Parties', I.Users, pet.length + res.length],
    ['hearings', 'Hearings', I.Calendar, hearings.filter((h) => !h.note).length],
    ['orders', 'Orders', I.Gavel, orders.length],
    ['more', 'Acts & more', I.Book, extra.length],
    ['json', 'JSON', I.Code],
  ]

  const name = (list) => (list[0]?.name || '—') + (list.length > 1 ? ` +${list.length - 1}` : '')
  const json = JSON.stringify(result, null, 2)

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="dossier-head">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div className="dossier-court">{c.court_name || 'District Court'}</div>
          <div style={{ display: 'flex', gap: 8 }} className="no-print">
            {onBack && (
              <button className="btn btn-sm" style={{ background: 'rgba(255,255,255,.1)', color: '#fff' }} onClick={onBack}>
                <I.Back size={14} /> Results
              </button>
            )}
            <button
              className="btn btn-sm btn-brass"
              onClick={() => downloadBlob(new Blob([json], { type: 'application/json' }), `${cd.cnr_number || 'case'}.json`)}
            >
              <I.Download size={14} /> JSON
            </button>
          </div>
        </div>
        <h2 className="dossier-title">
          {name(pet)} <span className="vs">versus</span> {name(res)}
        </h2>
        <div className="chips">
          <span className={`chip status ${status}`}>
            <span className="status-dot" /> {status === 'disposed' ? 'Disposed' : 'Pending'}
          </span>
          {cd.cnr_number && <span className="chip mono">CNR {cd.cnr_number}</span>}
          {cd.case_type && <span className="chip">{cd.case_type}</span>}
          {cs.case_stage && <span className="chip">Stage: {cs.case_stage}</span>}
        </div>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="stat-label"><I.File size={13} /> Filing</div>
          <div className="stat-value">{cd.filing_number || '—'}</div>
          <div className="party-det">{cd.filing_date}</div>
        </div>
        <div className="stat">
          <div className="stat-label"><I.Hash size={13} /> Registration</div>
          <div className="stat-value">{cd.registration_number || '—'}</div>
          <div className="party-det">{cd.registration_date}</div>
        </div>
        <div className={`stat ${status === 'pending' ? 'highlight' : ''}`}>
          <div className="stat-label"><I.Calendar size={13} /> {status === 'disposed' ? 'Decided on' : 'Next hearing'}</div>
          <div className="stat-value">{(status === 'disposed' ? cs.decision_date : cs.next_hearing_date) || '—'}</div>
          <div className="party-det">{cs.first_hearing_date && `First: ${cs.first_hearing_date}`}</div>
        </div>
        <div className="stat">
          <div className="stat-label"><I.Building size={13} /> Court & judge</div>
          <div className="stat-value" style={{ fontSize: 15 }}>{cs.court_number_and_judge || '—'}</div>
        </div>
      </div>

      <div className="tabs no-print" role="tablist">
        {tabs.map(([id, label, Icon, count]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            <Icon size={15} /> {label}
            {count !== undefined && <span className="count">{count}</span>}
          </button>
        ))}
      </div>

      <div className="tab-body">
        {tab === 'overview' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            <section>
              <div className="section-label">Case details</div>
              <KV data={cd} />
            </section>
            <section>
              <div className="section-label">Current status</div>
              <KV data={cs} />
            </section>
            {Object.keys(c.fir_details || {}).length > 0 && (
              <section>
                <div className="section-label">FIR details</div>
                <KV data={c.fir_details} />
              </section>
            )}
            {Object.keys(c.subordinate_court || {}).length > 0 && (
              <section>
                <div className="section-label">Subordinate court</div>
                <KV data={c.subordinate_court} />
              </section>
            )}
          </div>
        )}

        {tab === 'parties' && (
          <div className="parties">
            <PartyList title="Petitioners & advocates" parties={pet} kind="pet" />
            <div className="versus">v.</div>
            <PartyList title="Respondents & advocates" parties={res} kind="resp" />
          </div>
        )}

        {tab === 'hearings' &&
          (hearings.length ? (
            <div className="timeline">
              {hearings.map((h, i) => <Hearing key={i} h={h} next={i === 0 && status === 'pending'} />)}
            </div>
          ) : (
            <Empty icon={I.Calendar}>No hearing history published for this case.</Empty>
          ))}

        {tab === 'orders' &&
          (orders.length ? (
            <>
              <Alert kind="info">Order links open through your current eCourts session and expire when it does.</Alert>
              <div className="orders" style={{ marginTop: 16 }}>
                {orders.map((o, i) => (
                  <div className="order" key={i}>
                    <div className="order-top">
                      <div className="order-icon"><I.File /></div>
                      <span className={`order-type ${o.type}`}>{o.type === 'final' ? 'Judgment / Final' : 'Interim'}</span>
                    </div>
                    <div>
                      <div className="order-date">{o.order_date || '—'}</div>
                      <div className="party-det">Order No. {o.order_number || i + 1} · {o.order_details || 'Order'}</div>
                    </div>
                    {o.pdf_url ? (
                      <a className="btn btn-ghost btn-sm" href={ecourts.abs(o.pdf_url)} target="_blank" rel="noreferrer">
                        <I.External size={14} /> Open PDF
                      </a>
                    ) : (
                      <span className="party-det">No document uploaded</span>
                    )}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <Empty icon={I.Gavel}>No orders or judgments uploaded yet.</Empty>
          ))}

        {tab === 'more' &&
          (extra.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {extra.map((s, i) => (
                <section key={i}>
                  <div className="section-label">{s.heading || 'Additional information'}</div>
                  <DataTable rows={s.rows} />
                </section>
              ))}
            </div>
          ) : (
            <Empty icon={I.Book}>No acts or additional sections published.</Empty>
          ))}

        {tab === 'json' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => navigator.clipboard.writeText(json).then(() => toast('JSON copied'))}
              >
                <I.Copy size={14} /> Copy
              </button>
            </div>
            <JsonView data={result} />
          </>
        )}
      </div>
    </div>
  )
}
