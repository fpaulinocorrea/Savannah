import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import Logo from '../components/Logo'
import Horizon from '../components/Horizon'

export default function Setup({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return setError('Enter your first name.')
    if (password.length < 8) return setError('Use at least 8 characters for your password.')
    if (password !== confirm) return setError("The two passwords don't match.")
    setBusy(true)
    try {
      await api.setup(name.trim(), password)
      onDone()
    } catch (err) {
      setError((err as ApiError).message)
      setBusy(false)
    }
  }

  return (
    <main className="gate">
      <Horizon />
      <form className="gate-card" onSubmit={submit} noValidate>
        <Logo size={56} />
        <h1 className="display">Welcome to Savannah</h1>
        <p className="muted">Pick a password. You'll use it on this computer and on your phone.</p>

        <label className="field">
          <span>Your first name</span>
          <input value={name} onChange={(e) => { setName(e.target.value); setError('') }} autoComplete="given-name" autoFocus />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setError('') }} autoComplete="new-password" />
          <small>At least 8 characters</small>
        </label>
        <label className="field">
          <span>Type it again</span>
          <input type="password" value={confirm} onChange={(e) => { setConfirm(e.target.value); setError('') }} autoComplete="new-password" />
        </label>

        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Setting up…' : 'Start using Savannah'}</button>
      </form>
    </main>
  )
}
