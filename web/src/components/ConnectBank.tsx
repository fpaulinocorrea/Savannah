import { useState } from 'react'
import { Landmark } from 'lucide-react'
import { api, ApiError } from '../api'

type PlaidHandler = { open: () => void }
type PlaidGlobal = {
  create: (cfg: {
    token: string
    onSuccess: (publicToken: string, metadata: { institution?: { name?: string } | null }) => void
    onExit?: (err: { display_message?: string; error_message?: string } | null) => void
  }) => PlaidHandler
}
declare global {
  interface Window { Plaid?: PlaidGlobal }
}

// Plaid's own sign-in window. Savannah never sees your bank password.
function loadPlaid(): Promise<PlaidGlobal> {
  if (window.Plaid) return Promise.resolve(window.Plaid)
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js'
    s.onload = () => (window.Plaid ? resolve(window.Plaid) : reject(new Error('no plaid')))
    s.onerror = () => reject(new Error('blocked'))
    document.head.appendChild(s)
  })
}

export default function ConnectBank({ itemId = '', label, onDone, small }: { itemId?: string; label: string; onDone: () => void; small?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function start() {
    setBusy(true)
    setError('')
    try {
      const [{ link_token }, Plaid] = await Promise.all([api.plaidLinkToken(itemId), loadPlaid()])
      Plaid.create({
        token: link_token,
        onSuccess: async (publicToken, metadata) => {
          try {
            await api.plaidExchange(publicToken, metadata.institution?.name || 'Bank', itemId)
            onDone()
          } catch (e) {
            setError((e as ApiError).message)
          }
          setBusy(false)
        },
        onExit: (err) => {
          if (err) setError(err.display_message || err.error_message || 'The bank window closed before finishing.')
          setBusy(false)
        },
      }).open()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't open Plaid's window. Check this computer's internet connection.")
      setBusy(false)
    }
  }

  return (
    <span className="connect-bank">
      <button className={small ? 'btn btn-small' : 'btn btn-money'} onClick={start} disabled={busy}>
        <Landmark size={small ? 16 : 20} aria-hidden="true" /> {busy ? 'Opening…' : label}
      </button>
      {error && <span className="error small" role="alert">{error}</span>}
    </span>
  )
}
