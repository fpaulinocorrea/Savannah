import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, ApiError, type Status } from './api'
import Shell from './components/Shell'
import Setup from './pages/Setup'
import Login from './pages/Login'
import Home from './pages/Home'
import Guests from './pages/Guests'
import Books from './pages/Books'
import BooksSetup from './pages/BooksSetup'
import Settings from './pages/Settings'
import Reports from './pages/Reports'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    api
      .status()
      .then((s) => {
        setStatus(s)
        setError('')
      })
      .catch((e: ApiError) => setError(e.message))
  }, [])

  useEffect(refresh, [refresh])

  if (error) {
    return (
      <main className="gate">
        <div className="gate-card">
          <h1 className="display">Savannah</h1>
          <p className="error" role="alert">{error}</p>
          <button className="btn" onClick={refresh}>Try again</button>
        </div>
      </main>
    )
  }

  if (!status) return <main className="gate" aria-busy="true" />

  if (!status.set_up) return <Setup onDone={refresh} />
  if (!status.signed_in) return <Login onDone={refresh} />

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Home name={status.name} />} />
        <Route path="/guests" element={<Guests />} />
        <Route path="/guests/:id" element={<Guests />} />
        <Route path="/books" element={<Books />} />
        <Route path="/books/setup" element={<BooksSetup />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings onSignOut={refresh} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
