import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { downloadBlob, drafts } from '../api'
import * as I from '../icons'
import { Alert, Field, Skeleton, Spinner, WakingNotice, useSlow, useToast } from './ui'

// The form is generated entirely from the backend's template schema
// (GET /api/drafts/templates), so adding a template in Python needs no UI
// work. The preview re-renders live (debounced) once a draft exists.

const CATEGORY_ICON = { Notices: I.Pen, Civil: I.Scales, Criminal: I.Gavel, General: I.File }
const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

function defaults(t) {
  const v = {}
  for (const f of t.fields) {
    if (f.type === 'parties') v[f.name] = [{ name: '', details: '' }]
    else v[f.name] = f.default ?? ''
  }
  return v
}

function PartyEditor({ value, onChange, label }) {
  const list = value?.length ? value : [{ name: '', details: '' }]
  const set = (i, patch) => onChange(list.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  return (
    <div className="party-editor">
      {list.map((p, i) => (
        <div className="party-item" key={i}>
          <div className="idx">{i + 1}</div>
          <div className="stack">
            <input className="input" placeholder="Full name" value={p.name} onChange={(e) => set(i, { name: e.target.value })} />
            <input className="input" placeholder="Description / address (S/o …, R/o …)" value={p.details}
              onChange={(e) => set(i, { details: e.target.value })} />
          </div>
          <button type="button" className="btn btn-text btn-icon" disabled={list.length === 1}
            onClick={() => onChange(list.filter((_, j) => j !== i))} aria-label={`Remove ${label} ${i + 1}`}>
            <I.Trash size={16} />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange([...list, { name: '', details: '' }])}>
          <I.Plus size={14} /> Add another
        </button>
      </div>
    </div>
  )
}

function Input({ f, value, onChange }) {
  switch (f.type) {
    case 'textarea':
      return <textarea className="textarea" rows={f.name.match(/facts|grounds|statements/) ? 6 : 3}
        placeholder={f.placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    case 'select':
      return (
        <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
          {!f.required || !f.default ? <option value="">Select…</option> : null}
          {f.options.map((o) => <option key={o}>{o}</option>)}
        </select>
      )
    case 'date':
      return <input type="date" className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    case 'amount':
    case 'number':
      return <input className="input" inputMode="decimal" placeholder={f.placeholder} value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^\d.,]/g, ''))} />
    case 'parties':
      return <PartyEditor value={value} onChange={onChange} label={f.label} />
    default:
      return <input className="input" placeholder={f.placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
  }
}

function Paper({ draft }) {
  // Visible blanks ("________") render as fill-in lines, as on a printed form.
  const fmt = (t) =>
    t.split(/(_{4,})/).map((part, i) => (/^_{4,}$/.test(part) ? <span key={i} className="blank" /> : <Fragment key={i}>{part}</Fragment>))
  return (
    <div className="paper">
      {draft.blocks.map((b, i) => {
        const cls = `b-${b.kind} ${b.bold ? 'bold' : ''}`
        if (b.kind === 'spacer') return <div key={i} className="b-spacer" />
        if (b.kind === 'numbered' || b.kind === 'prayer')
          return <p key={i} className={cls}><span>{b.number}</span><span>{fmt(b.text)}</span></p>
        return <p key={i} className={cls}>{fmt(b.text)}</p>
      })}
    </div>
  )
}

export default function DraftStudio() {
  const toast = useToast()
  const [templates, setTemplates] = useState(null)
  const [loadErr, setLoadErr] = useState(null)
  const [tid, setTid] = useState('')
  const [values, setValues] = useState({})
  const [errors, setErrors] = useState({})
  const [draft, setDraft] = useState(null)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const [formErr, setFormErr] = useState('')
  const timer = useRef()
  const waking = useSlow(!templates && !loadErr)

  useEffect(() => {
    drafts.templates()
      .then((t) => {
        setTemplates(t)
        setTid(t[0].id)
        setValues(defaults(t[0]))
      })
      .catch(setLoadErr)
  }, [])

  const tpl = templates?.find((t) => t.id === tid)
  const groups = useMemo(() => {
    const g = new Map()
    tpl?.fields.forEach((f) => g.set(f.group, [...(g.get(f.group) || []), f]))
    return [...g.entries()]
  }, [tpl])

  const pick = (t) => {
    setTid(t.id)
    setValues(defaults(t))
    setDraft(null)
    setErrors({})
    setLive(false)
    setFormErr('')
  }

  const generate = async (vals = values, quiet = false) => {
    if (!quiet) setBusy(true)
    try {
      const d = await drafts.generate(tid, vals)
      setDraft(d)
      setErrors({})
      setFormErr('')
      setLive(true)
    } catch (e) {
      // During live updates keep the last good preview and stay quiet;
      // on an explicit click, show every field error.
      if (!quiet) {
        setErrors(e.fields || {})
        setFormErr(e.message)
      }
    } finally {
      if (!quiet) setBusy(false)
    }
  }

  const update = (name, v) => {
    const next = { ...values, [name]: v }
    setValues(next)
    if (errors[name]) setErrors(({ [name]: _, ...rest }) => rest)
    if (live) {
      clearTimeout(timer.current)
      timer.current = setTimeout(() => generate(next, true), 450)
    }
  }

  const fillSample = () => {
    const v = { ...defaults(tpl), ...tpl.sample }
    setValues(v)
    generate(v)
  }

  const downloadDocx = async () => {
    setBusy(true)
    try {
      const { blob, name } = await drafts.docx(tid, values)
      downloadBlob(blob, name)
      toast('Word document downloaded')
    } catch (e) {
      setErrors(e.fields || {})
      setFormErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (loadErr) return <Alert title="Could not load templates">{loadErr.message}</Alert>
  if (!templates)
    return (
      <>
        {waking && <div style={{ marginBottom: 16 }}><WakingNotice /></div>}
        <div className="templates">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} h={150} style={{ borderRadius: 14 }} />)}
        </div>
      </>
    )

  return (
    <>
      <div className="templates">
        {templates.map((t) => {
          const Icon = CATEGORY_ICON[t.category] || I.File
          return (
            <button key={t.id} className={`tpl ${t.id === tid ? 'active' : ''}`} onClick={() => pick(t)}>
              <div className="tpl-icon"><Icon size={20} /></div>
              <div className="tpl-cat">{t.category}</div>
              <div className="tpl-name">{t.name}</div>
              <div className="tpl-desc">{t.description}</div>
            </button>
          )
        })}
      </div>

      <div className="studio">
        <form className="card" onSubmit={(e) => { e.preventDefault(); generate() }}>
          <div className="card-pad" style={{ paddingBottom: 8 }}>
            <div className="card-head" style={{ marginBottom: 6 }}>
              <div>
                <h2 className="card-title">{tpl.name}</h2>
                <div className="card-sub">Fill in the details. Fields marked * are required.</div>
              </div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={fillSample}>
                <I.Sparkle size={14} /> Fill sample
              </button>
            </div>
            {formErr && <Alert title={formErr} onClose={() => setFormErr('')} />}
          </div>

          {groups.map(([group, fields]) => (
            <div className="form-group" key={group}>
              <div className="section-label">{group}</div>
              <div className="grid g2">
                {fields.map((f) => {
                  const wide = ['textarea', 'parties'].includes(f.type) || f.name.endsWith('court_name')
                  const v = values[f.name] ?? ''
                  const amountHint = f.type === 'amount' && v && !isNaN(+String(v).replace(/,/g, ''))
                    ? `₹ ${inr.format(+String(v).replace(/,/g, ''))}` : null
                  return (
                    <Field key={f.name} label={f.label} required={f.required && f.default == null}
                      help={amountHint || f.help} error={errors[f.name]} className={wide ? 'span-all' : ''}>
                      <Input f={f} value={v} onChange={(x) => update(f.name, x)} />
                    </Field>
                  )
                })}
              </div>
            </div>
          ))}

          <div className="form-actions">
            <span className="card-sub" style={{ margin: 0 }}>
              {live ? <><I.Check size={13} /> Live preview on</> : 'Pure Python templates. No AI or external APIs.'}
            </span>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? <Spinner /> : <I.Sparkle size={16} />} Generate draft
            </button>
          </div>
        </form>

        <div className="preview-shell">
          <div className="preview-bar">
            <h3>Preview</h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-ghost btn-sm" disabled={!draft}
                onClick={() => navigator.clipboard.writeText(draft.text).then(() => toast('Draft copied'))}>
                <I.Copy size={14} /> Copy
              </button>
              <button className="btn btn-ghost btn-sm" disabled={!draft} onClick={() => window.print()}>
                <I.Printer size={14} /> Print / PDF
              </button>
              <button className="btn btn-brass btn-sm" disabled={!draft || busy} onClick={downloadDocx}>
                <I.Download size={14} /> Word (.docx)
              </button>
            </div>
          </div>
          {draft?.warnings?.length > 0 && (
            <div className="warnings">
              {draft.warnings.map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
            </div>
          )}
          <div className="desk">
            {draft ? (
              <Paper draft={draft} />
            ) : (
              <div className="paper">
                <div className="paper-empty">
                  <div>
                    <I.Scales size={44} />
                    <div className="big">Your draft appears here</div>
                    <div>Fill the form and click <b>Generate draft</b>, or try <b>Fill sample</b>.</div>
                  </div>
                </div>
              </div>
            )}
          </div>
          <p className="card-sub" style={{ marginTop: 10 }}>
            Generated drafts are a starting point and must be reviewed by an advocate before filing.
          </p>
        </div>
      </div>
    </>
  )
}
