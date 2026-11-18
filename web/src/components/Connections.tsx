import { useEffect, useState, type FormEvent } from 'react'
import { Check, CircleAlert, Plug } from 'lucide-react'
import { api, ApiError, type Connections as Conn, type TestResult } from '../api'

const ITEMS: { name: 'hospitable' | 'claude'; title: string; what: string; where: string; placeholder: string }[] = [
  {
    name: 'hospitable',
    title: 'Hospitable',
    what: 'Reads guest messages and sends your replies.',
    where: 'In Hospitable: Apps → API access → Access tokens → add a token.',
    placeholder: 'Paste your Hospitable access key',
  },
  {
    name: 'claude',
    title: 'Claude',
    what: 'Writes the reply drafts in your voice.',
    where: 'At console.anthropic.com: API Keys → Create key. It starts with sk-ant-',
    placeholder: 'Paste your Claude key (sk-ant-…)',
  },
]

export default function Connections() {
  const [conn, setConn] = useState<Conn | null>(null)
  const load = () => api.connections().then(setConn).catch(() => {})
  useEffect(() => { load() }, [])

  return (
    <section className="panel">
      <h2><Plug size={20} aria-hidden="true" /> Connections</h2>
      <p className="muted small">Keys stay on this computer, in your private data folder.</p>
      <div className="conn-list">
        {ITEMS.map((item) => (
          <ConnectionRow key={item.name} item={item} info={conn?.[item.name]} onChange={load} />
        ))}
        <PlaidRow info={conn?.plaid} onChange={load} />
      </div>
    </section>
  )
}

function ConnectionRow({ item, info, onChange }: { item: (typeof ITEMS)[number]; info?: { saved: boolean; ending: string }; onChange: () => void }) {
  const [key, setKey] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!key.trim()) return setResult({ ok: false, message: 'Paste the key first.' })
    setBusy(true)
    try {
      const r = await api.saveKey(item.name, key)
      setResult(r)
      if (r.ok) { setKey(''); setEditing(false) }
      onChange()
    } catch (err) {
      setResult({ ok: false, message: (err as ApiError).message })
    }
    setBusy(false)
  }

  async function test() {
    setBusy(true)
    setResult(await api.testKey(item.name).catch((e: ApiError) => ({ ok: false, message: e.message })))
    setBusy(false)
  }

  async function remove() {
    await api.removeKey(item.name).catch(() => {})
    setResult(null)
    onChange()
  }

  const connected = !!info?.saved
  const showForm = !connected || editing

  return (
    <div className={`conn ${connected ? 'conn-on' : ''}`}>
      <div className="conn-head">
        <span className="conn-state" aria-hidden="true">{connected ? <Check size={18} strokeWidth={2.5} /> : null}</span>
        <div>
          <strong>{item.title}</strong>
          <p className="muted small">{connected ? `Connected (key ending ${info?.ending})` : item.what}</p>
        </div>
      </div>

      {showForm ? (
        <form className="conn-form" onSubmit={save} noValidate>
          <p className="muted small">{item.where}</p>
          <div className="conn-input">
            <input
              type="password"
              value={key}
              onChange={(e) => { setKey(e.target.value); setResult(null) }}
              placeholder={item.placeholder}
              aria-label={`${item.title} key`}
              autoComplete="off"
            />
            <button className="btn btn-dark" disabled={busy}>{busy ? 'Checking…' : 'Save and test'}</button>
          </div>
          {editing && <button type="button" className="link-btn" onClick={() => setEditing(false)}>Cancel</button>}
        </form>
      ) : (
        <div className="conn-buttons">
          <button className="btn btn-small" onClick={test} disabled={busy}>{busy ? 'Testing…' : 'Test connection'}</button>
          <button className="btn btn-small" onClick={() => setEditing(true)}>Replace key</button>
          <button className="link-btn" onClick={remove}>Disconnect</button>
        </div>
      )}

      {result && (
        <p className={result.ok ? 'success' : 'error'} role="status">
          {result.ok ? <Check size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />} {result.message}
          {result.homes && result.homes.length > 0 && <span className="homes">{result.homes.join(', ')}</span>}
        </p>
      )}
    </div>
  )
}

function PlaidRow({ info, onChange }: { info?: { saved: boolean; ending: string }; onChange: () => void }) {
  const [cid, setCid] = useState('')
  const [secret, setSecret] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)
  const connected = !!info?.saved

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!cid.trim() || !secret.trim()) return setResult({ ok: false, message: 'Paste both the client ID and the secret.' })
    setBusy(true)
    try {
      const r = await api.savePlaid(cid, secret)
      setResult(r)
      if (r.ok) { setCid(''); setSecret(''); setEditing(false) }
      onChange()
    } catch (err) {
      setResult({ ok: false, message: (err as ApiError).message })
    }
    setBusy(false)
  }

  return (
    <div className={`conn ${connected ? 'conn-on' : ''}`}>
      <div className="conn-head">
        <span className="conn-state" aria-hidden="true">{connected ? <Check size={18} strokeWidth={2.5} /> : null}</span>
        <div>
          <strong>Plaid (for Chase)</strong>
          <p className="muted small">{connected ? `Connected (client ID ending ${info?.ending})` : 'Brings in your Chase transactions.'}</p>
        </div>
      </div>
      {!connected || editing ? (
        <form className="conn-form" onSubmit={save} noValidate>
          <p className="muted small">At dashboard.plaid.com: Developers → Keys. Use the Production secret.</p>
          <div className="conn-input">
            <input value={cid} onChange={(e) => { setCid(e.target.value); setResult(null) }} placeholder="client_id" aria-label="Plaid client ID" autoComplete="off" />
            <input type="password" value={secret} onChange={(e) => { setSecret(e.target.value); setResult(null) }} placeholder="Production secret" aria-label="Plaid secret" autoComplete="off" />
            <button className="btn btn-dark" disabled={busy}>{busy ? 'Checking…' : 'Save and test'}</button>
          </div>
          {editing && <button type="button" className="link-btn" onClick={() => setEditing(false)}>Cancel</button>}
        </form>
      ) : (
        <div className="conn-buttons">
          <button className="btn btn-small" onClick={() => setEditing(true)}>Replace keys</button>
          <button className="link-btn" onClick={() => api.removePlaid().then(() => { setResult(null); onChange() })}>Disconnect</button>
        </div>
      )}
      {result && (
        <p className={result.ok ? 'success' : 'error'} role="status">
          {result.ok ? <Check size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />} {result.message}
        </p>
      )}
    </div>
  )
}
