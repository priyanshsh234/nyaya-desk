import { useEffect, useState } from 'react'
import { ecourts } from '../api'
import * as I from '../icons'
import { Skeleton } from './ui'

// The captcha image is proxied through our backend for the user's portal
// session; the user types the answer. We deliberately do not auto-solve it.
// `nonce` changes force a fresh image (each portal attempt consumes the code).
export default function Captcha({ sid, nonce, onRefresh, value, onChange, disabled }) {
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setLoaded(false)
    setFailed(false)
  }, [sid, nonce])

  return (
    <div className="captcha">
      <div className="captcha-img">
        {sid && !failed && (
          <img
            key={`${sid}-${nonce}`}
            src={ecourts.captchaUrl(sid, nonce)}
            alt="Captcha from eCourts"
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            style={{ opacity: loaded ? 1 : 0, transition: 'opacity .2s' }}
          />
        )}
        {!loaded && !failed && (
          <div style={{ position: 'absolute', inset: 8 }}>
            <Skeleton h="100%" />
          </div>
        )}
        {failed && <span style={{ fontSize: 12.5, color: 'var(--red)', padding: 8 }}>Could not load captcha</span>}
      </div>
      <button type="button" className="btn btn-ghost btn-icon" onClick={onRefresh} title="New captcha" disabled={disabled}>
        <I.Refresh />
      </button>
      <div className="captcha-side">
        <input
          className="input mono"
          placeholder="Enter captcha"
          value={value}
          maxLength={8}
          onChange={(e) => onChange(e.target.value.trim())}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          aria-label="Captcha answer"
        />
        <span className="captcha-note">
          <I.Shield size={13} /> Shown live from eCourts for your session. Solved by you, never by a bot.
        </span>
      </div>
    </div>
  )
}
