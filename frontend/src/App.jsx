import { useEffect, useState } from 'react'
import CaseSearch from './components/CaseSearch'
import DraftStudio from './components/DraftStudio'
import { ToastProvider } from './components/ui'
import * as I from './icons'

// Two pages, switched by URL hash (#/cases, #/drafts). Hash routing avoids a
// router dependency and works on any static host without rewrite rules.
const PAGES = {
  cases: {
    nav: 'Case Search',
    icon: I.Search,
    eyebrow: 'eCourts · District Courts',
    title: <>Every detail of a case, <em>in one clean view.</em></>,
    sub: 'Search any district court case in India by CNR or case number. Parties, hearings, orders and judgments, structured and ready to export.',
  },
  drafts: {
    nav: 'Draft Studio',
    icon: I.Pen,
    eyebrow: 'Legal draft generator',
    title: <>From facts to a filing-ready <em>first draft.</em></>,
    sub: 'Legal notices, plaints, bail applications and affidavits, built from rule-based Python templates with Indian drafting conventions.',
  },
}

const fromHash = () => (window.location.hash.replace('#/', '') in PAGES ? window.location.hash.replace('#/', '') : 'cases')

export default function App() {
  const [page, setPage] = useState(fromHash)
  useEffect(() => {
    const on = () => setPage(fromHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const p = PAGES[page]

  return (
    <ToastProvider>
      <header className="hero">
        <div className="wrap">
          <div className="topbar">
            <a className="brand" href="#/cases">
              <span className="brand-mark"><I.Scales size={22} /></span>
              <span className="brand-name">Nyaya<span>Desk</span></span>
            </a>
            <nav className="nav">
              {Object.entries(PAGES).map(([id, x]) => (
                <button key={id} className={page === id ? 'active' : ''} onClick={() => (window.location.hash = `/${id}`)}>
                  <x.icon size={15} /> {x.nav}
                </button>
              ))}
            </nav>
          </div>
          <div className="hero-copy" key={page}>
            <div className="eyebrow"><I.Sparkle size={13} /> {p.eyebrow}</div>
            <h1>{p.title}</h1>
            <p>{p.sub}</p>
          </div>
        </div>
      </header>

      <main className="main">
        <div className="wrap">{page === 'cases' ? <CaseSearch /> : <DraftStudio />}</div>
      </main>

      <footer className="footer">
        Data is fetched live from services.ecourts.gov.in. Captchas are always solved by you. Drafts must be reviewed by an advocate.
      </footer>
    </ToastProvider>
  )
}
