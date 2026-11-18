import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import Logo from '../components/Logo'
import Horizon from '../components/Horizon'

export default function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!password) return setError('Enter your password.')
    setBusy(true)
    try {
      await api.login(password)
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
        <h1 className="display">Savannah</h1>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setError('') }} autoComplete="current-password" autoFocus />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main>
  )
}
