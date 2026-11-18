import { useEffect, useState, type FormEvent } from 'react'
import QRCode from 'qrcode'
import { Check, Copy, FolderOpen, KeyRound, LogOut, Smartphone, Zap } from 'lucide-react'
import { api, ApiError, timeAgo, type HooksInfo, type SystemInfo } from '../api'
import Connections from '../components/Connections'

export default function Settings({ onSignOut }: { onSignOut: () => void }) {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [qr, setQr] = useState('')
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api
      .system()
      .then(async (s) => {
        setInfo(s)
        if (s.phone_urls[0]) {
          // Always dark-on-white so every phone camera can read it.
          setQr(await QRCode.toDataURL(s.phone_urls[0], { margin: 2, width: 360, color: { dark: '#1F2B25', light: '#FFFFFF' } }))
        }
      })
      .catch((e: ApiError) => setLoadError(e.message))
  }, [])

  async function signOut() {
    await api.logout().catch(() => {})
    onSignOut()
  }

  return (
    <div className="settings">
      <h1 className="display">Settings</h1>
      {loadError && <p className="error" role="alert">{loadError}</p>}

      <Connections />

      <InstantAlerts />

      <section className="panel panel-phone">
        <h2><Smartphone size={20} aria-hidden="true" /> Open on your phone</h2>
        {info && info.phone_urls.length > 0 ? (
          <div className="phone">
            {qr && <img src={qr} alt={`QR code for ${info.phone_urls[0]}`} width={180} height={180} />}
            <div>
              <p>Point your phone's camera at the code, or type:</p>
              <p className="url">{info.phone_urls[0]}</p>
              <p className="muted small">Your phone must be on the same Wi-Fi as this computer.</p>
            </div>
          </div>
        ) : (
          info && <p className="muted">This computer isn't on a network right now. Connect it to Wi-Fi to use Savannah on your phone.</p>
        )}
      </section>

      <section className="panel">
        <h2><FolderOpen size={20} aria-hidden="true" /> Your data</h2>
        <p>Everything Savannah knows is in one folder. Back it up and you have it all.</p>
        {info && <code className="path">{info.data_folder}</code>}
      </section>

      <ChangePassword />

      <section className="panel">
        <button className="btn" onClick={signOut}>
          <LogOut size={18} aria-hidden="true" /> Sign out of this device
        </button>
        {info && <p className="muted small">Savannah version {info.version}</p>}
      </section>
    </div>
  )
}

function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!current) return setMsg({ ok: false, text: 'Enter your current password.' })
    if (next.length < 8) return setMsg({ ok: false, text: 'Use at least 8 characters for your new password.' })
    setBusy(true)
    try {
      await api.changePassword(current, next)
      setMsg({ ok: true, text: 'Password changed.' })
      setCurrent('')
      setNext('')
    } catch (err) {
      setMsg({ ok: false, text: (err as ApiError).message })
    }
    setBusy(false)
  }

  return (
    <section className="panel">
      <h2><KeyRound size={20} aria-hidden="true" /> Change password</h2>
      <form className="inline-form" onSubmit={submit} noValidate>
        <label className="field">
          <span>Current password</span>
          <input type="password" value={current} onChange={(e) => { setCurrent(e.target.value); setMsg(null) }} autoComplete="current-password" />
        </label>
        <label className="field">
          <span>New password</span>
          <input type="password" value={next} onChange={(e) => { setNext(e.target.value); setMsg(null) }} autoComplete="new-password" />
        </label>
        {msg && <p className={msg.ok ? 'success' : 'error'} role="status">{msg.text}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Changing…' : 'Change password'}</button>
      </form>
    </section>
  )
}

/** Hospitable pings Savannah through the Cloudflare tunnel the moment a guest writes. */
function InstantAlerts() {
  const [info, setInfo] = useState<HooksInfo | null>(null)
  const [host, setHost] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const load = () => api.hooks().then((x) => { setInfo(x); setHost((h) => h || x.host || 'hooks.sproutly-app.com') }).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg(null)
    try {
      const x = await api.setHookHost(host)
      setInfo(x)
      const t = await api.testHooks()
      setMsg({ ok: t.ok, text: t.message })
      setInfo(await api.hooks())
    } catch (err) {
      setMsg({ ok: false, text: (err as ApiError).message })
    }
    setBusy(false)
  }

  function copy() {
    if (!info?.link) return
    navigator.clipboard?.writeText(info.link).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) }).catch(() => {})
  }

  const realAlert = info?.last_at && info.last_action !== 'savannah.test'
  return (
    <section className="panel">
      <h2><Zap size={20} aria-hidden="true" /> Instant alerts</h2>
      <p>Hospitable tells Savannah the moment a guest writes, instead of waiting up to 3 minutes.</p>
      <ol className="hook-steps">
        <li className={info?.host ? 'is-done' : ''}>
          <span className="hook-num">1</span>
          <form className="inline-form" onSubmit={save} noValidate>
            <label className="field">
              <span>Your tunnel address</span>
              <input value={host} onChange={(e) => { setHost(e.target.value); setMsg(null) }} placeholder="hooks.sproutly-app.com" />
            </label>
            <button className="btn" disabled={busy}>{busy ? 'Testing…' : 'Save and test'}</button>
          </form>
        </li>
        {msg && <p className={msg.ok ? 'success' : 'error'} role="status">{msg.ok ? <Check size={16} aria-hidden="true" /> : null}{msg.text}</p>}
        {info?.link && (
          <li>
            <span className="hook-num">2</span>
            <div className="hook-link">
              <span className="muted small">Paste this link in Hospitable → Apps → Webhooks (message events). Keep it private.</span>
              <div className="hook-copy">
                <code className="path">{info.link}</code>
                <button className="btn btn-small" onClick={copy}>{copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />} {copied ? 'Copied' : 'Copy'}</button>
              </div>
            </div>
          </li>
        )}
        {info?.link && (
          <li className={realAlert ? 'is-done' : ''}>
            <span className="hook-num">3</span>
            <span className={`chip ${realAlert ? 'chip-good' : ''}`}>
              {realAlert ? <><span className="dot" /> Last alert from Hospitable {timeAgo(info.last_at!)}</> : 'Waiting for the first alert from Hospitable'}
            </span>
          </li>
        )}
      </ol>
    </section>
  )
}
