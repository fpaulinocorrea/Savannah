import { useRef, useState } from 'react'
import { Check, FileText, Plus, Split, Trash2 } from 'lucide-react'
import { api, ApiError, money, shortDate, type LedgerAccount, type Txn } from '../api'
import CategorySelect from './CategorySelect'

type Part = { category_id: number | null; dollars: string; memo: string }

const toCents = (s: string) => {
  const n = Number(String(s).replace(/[$,\s]/g, ''))
  return Number.isFinite(n) ? Math.round(n * 100) : NaN
}

/** Split one transaction across several categories, e.g. a mortgage payment into
 *  interest, escrow and principal. Amounts are typed as positive numbers. */
export default function SplitEditor({ t, accounts, onDone, onCancel }: {
  t: Txn; accounts: LedgerAccount[]; onDone: () => void; onCancel: () => void
}) {
  const sign = t.amount_cents < 0 ? -1 : 1
  const total = Math.abs(t.amount_cents)
  const [parts, setParts] = useState<Part[]>(() =>
    t.splits && t.splits.length
      ? t.splits.map((s) => ({ category_id: s.category_id, dollars: (Math.abs(s.amount_cents) / 100).toFixed(2), memo: s.memo }))
      : [
          { category_id: t.category_id, dollars: (total / 100).toFixed(2), memo: '' },
          { category_id: null, dollars: '', memo: '' },
        ],
  )
  const [remember, setRemember] = useState(false)
  const [match, setMatch] = useState(t.suggested_rule)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reading, setReading] = useState(false)
  const [fromStatement, setFromStatement] = useState<{ text: string; warning: string } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function readStatement(file: File | undefined) {
    if (!file) return
    setReading(true); setError(''); setFromStatement(null)
    try {
      const r = await api.readStatement(t.id, file)
      const filled = r.lines.map((ln) => ({ category_id: ln.category_id, dollars: (ln.amount_cents / 100).toFixed(2), memo: ln.label }))
      if (filled.length) setParts(filled)
      const when = r.statement_date ? ` (statement ${shortDate(r.statement_date)})` : ''
      setFromStatement({ text: `Filled in from ${r.lender || 'your statement'}${when}, ${r.where}.`, warning: r.warning })
    } catch (e) {
      setError((e as ApiError).message)
    }
    setReading(false)
    if (fileInput.current) fileInput.current.value = ''
  }

  const placed = parts.reduce((a, p) => a + (toCents(p.dollars) || 0), 0)
  const left = total - placed
  const set = (i: number, patch: Partial<Part>) => { setParts((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p))); setError('') }

  async function save() {
    const used = parts.filter((p) => p.dollars.trim() !== '' && toCents(p.dollars) !== 0)
    if (used.some((p) => !p.category_id)) return setError('Pick a category for every part.')
    if (used.some((p) => Number.isNaN(toCents(p.dollars)))) return setError('Type amounts as numbers, like 1250.00')
    if (left !== 0) return setError(`The parts must add up to ${money(total)}.`)
    if (remember && !match.trim()) return setError('Type the words to look for, or untick "Next time".')
    setBusy(true)
    try {
      await api.splitTxn(t.id, used.map((p) => ({ category_id: p.category_id!, amount_cents: sign * toCents(p.dollars), memo: p.memo })), remember, match)
      onDone()
    } catch (e) {
      setError((e as ApiError).message)
      setBusy(false)
    }
  }

  async function unsplit() {
    setBusy(true)
    await api.splitTxn(t.id, [], false, '').catch(() => {})
    onDone()
  }

  return (
    <div className="split-editor">
      <div className="split-head">
        <Split size={18} aria-hidden="true" />
        <strong>Split {money(total)}</strong>
        <span className={`split-left ${left === 0 ? 'is-ok' : ''}`}>
          {left === 0 ? <><Check size={15} aria-hidden="true" /> Adds up</> : left > 0 ? `${money(left)} left to place` : `${money(-left)} too much`}
        </span>
      </div>
      {t.category_source === 'rule-split' && !fromStatement && (
        <p className="muted small">Split like last time. Check the amounts against this month's statement.</p>
      )}
      <div className="statement-row">
        <input ref={fileInput} type="file" accept="application/pdf,image/*" hidden onChange={(e) => readStatement(e.target.files?.[0])} />
        <button className="btn btn-small" onClick={() => fileInput.current?.click()} disabled={reading || busy}>
          <FileText size={16} aria-hidden="true" /> {reading ? 'Reading the statement…' : 'Fill in from mortgage statement'}
        </button>
        {!fromStatement && !reading && <span className="muted small">PDF or photo. Savannah finds principal, interest and escrow.</span>}
      </div>
      {fromStatement && (
        <p className={fromStatement.warning ? 'error' : 'success'} role="status">
          {fromStatement.warning ? null : <Check size={16} aria-hidden="true" />} {fromStatement.text}{fromStatement.warning ? ` ${fromStatement.warning}` : ''}
        </p>
      )}
      <ul className="split-parts">
        {parts.map((p, i) => (
          <li key={i}>
            <CategorySelect accounts={accounts} value={p.category_id} onChange={(id) => set(i, { category_id: id })} label={`Category for part ${i + 1}`} moneyIn={sign > 0} />
            <label className="split-amount">
              <span aria-hidden="true">$</span>
              <input inputMode="decimal" value={p.dollars} onChange={(e) => set(i, { dollars: e.target.value })} aria-label={`Amount for part ${i + 1}`} placeholder="0.00" />
            </label>
            {left > 0 && !p.dollars && (
              <button className="link-btn" onClick={() => set(i, { dollars: (left / 100).toFixed(2) })}>Use the rest</button>
            )}
            {parts.length > 1 && (
              <button className="link-btn" aria-label={`Remove part ${i + 1}`} onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}>
                <Trash2 size={16} aria-hidden="true" />
              </button>
            )}
          </li>
        ))}
      </ul>
      <button className="link-btn" onClick={() => setParts((ps) => [...ps, { category_id: null, dollars: '', memo: '' }])}>
        <Plus size={16} aria-hidden="true" /> Add a part
      </button>
      <label className="always">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span>Next time, split it the same way when the description has</span>
        <input className="always-text" value={match} onChange={(e) => setMatch(e.target.value)} aria-label="Words to look for" disabled={!remember} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="btn-row">
        <button className="btn btn-money" onClick={save} disabled={busy}><Check size={18} aria-hidden="true" /> {busy ? 'Saving…' : 'Save split'}</button>
        <button className="btn btn-small" onClick={onCancel} disabled={busy}>Cancel</button>
        {t.splits && t.splits.length > 0 && <button className="link-btn" onClick={unsplit} disabled={busy}>Undo split</button>}
      </div>
    </div>
  )
}
