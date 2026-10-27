import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as I from '../icons'

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />
}

export function Field({ label, required, help, error, children, className = '' }) {
  return (
    <div className={`field ${error ? 'invalid' : ''} ${className}`}>
      {label && (
        <label>
          {label}
          {required && <span className="req">*</span>}
        </label>
      )}
      {children}
      {error ? <span className="err">{error}</span> : help ? <span className="help">{help}</span> : null}
    </div>
  )
}

export function Alert({ kind = 'error', title, children, onClose }) {
  const Icon = kind === 'info' ? I.Shield : I.Alert
  return (
    <div className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon />
      <div style={{ flex: 1 }}>
        {title && <strong>{title}</strong>}
        {children}
      </div>
      {onClose && (
        <button className="btn btn-text btn-sm" onClick={onClose} aria-label="Dismiss">
          <I.X size={14} />
        </button>
      )}
    </div>
  )
}

// True once `active` has stayed true for `ms`. Used to explain long waits:
// the free Render backend sleeps when idle and takes ~30-60s to wake.
export function useSlow(active, ms = 4000) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    if (!active) {
      setSlow(false)
      return
    }
    const t = setTimeout(() => setSlow(true), ms)
    return () => clearTimeout(t)
  }, [active, ms])
  return slow
}

export function WakingNotice() {
  return (
    <Alert kind="info" title="Waking up the server…">
      The free backend sleeps when idle and can take up to a minute to start. Hang tight.
    </Alert>
  )
}

export function Skeleton({ h = 16, w = '100%', style }) {
  return <div className="skel" style={{ height: h, width: w, ...style }} />
}

// ------------------------------------------------------------------ toasts

const ToastCtx = createContext(() => {})

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((text) => {
    const id = Math.random()
    setItems((x) => [...x, { id, text }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 2600)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" aria-live="polite">
        {items.map((t) => (
          <div className="toast" key={t.id}>
            <I.Check size={16} /> {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)

// ------------------------------------------------------------- JSON viewer

// Minimal syntax highlighter: escape, then colour keys/strings/numbers/bools.
// Avoids pulling in a highlighting library for one view.
function highlight(json) {
  const esc = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(\.\d+)?([eE][+-]?\d+)?)/g,
    (m) => {
      let cls = 'n'
      if (m.startsWith('"')) cls = m.trimEnd().endsWith(':') ? 'k' : 's'
      else if (/true|false|null/.test(m)) cls = 'b'
      return `<span class="${cls}">${m}</span>`
    },
  )
}

export function JsonView({ data }) {
  const html = useMemo(() => highlight(JSON.stringify(data, null, 2)), [data])
  return <pre className="json" dangerouslySetInnerHTML={{ __html: html }} />
}

export function initials(name = '') {
  const words = name.replace(/[^A-Za-z ]/g, ' ').split(/\s+/).filter(Boolean)
  return ((words[0]?.[0] || '') + (words[1]?.[0] || '')).toUpperCase() || '?'
}
