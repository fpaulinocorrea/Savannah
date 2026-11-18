import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, Check, CircleAlert, CircleCheck, History, Lightbulb, Link2, Undo2, UserRound, CreditCard, Landmark, RefreshCw, Search, Settings2, Sparkles, Split, Wand2, Zap } from 'lucide-react'
import {
  api, ApiError, money, shortDate, timeAgo, type BalanceCheck, type BooksSummary, type LedgerAccount, type Txn,
  type RuleMode,
} from '../api'
import CategorySelect from '../components/CategorySelect'
import ConnectBank from '../components/ConnectBank'
import SplitEditor from '../components/SplitEditor'

export default function Books() {
  const [s, setS] = useState<BooksSummary | null>(null)
  const [accounts, setAccounts] = useState<LedgerAccount[]>([])
  const [tab, setTab] = useState<'review' | 'all'>('review')
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)

  const load = useCallback(() => {
    api.books().then((x) => { setS(x); setError('') }).catch((e: ApiError) => setError(e.message))
    api.accounts().then(setAccounts).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, s?.syncing ? 3000 : 30000)
    return () => clearInterval(t)
  }, [load, s?.syncing])

  // When a sync finishes, refresh the lists too.
  useEffect(() => { setTick((n) => n + 1) }, [s?.last_sync_at])

  if (error && !s) return <p className="error" role="alert">{error}</p>
  if (!s) return null

  const hasChart = s.chart_count > 0
  const hasBank = s.banks.length > 0
  const refreshAll = () => { load(); setTick((n) => n + 1) }

  return (
    <div className="books">
      <header className="books-head">
        <h1 className="display">Books</h1>
        <Link to="/books/setup" className="btn btn-small"><Settings2 size={16} aria-hidden="true" /> Setup</Link>
      </header>

      {(!hasChart || !hasBank) && <BooksSteps s={s} onDone={refreshAll} />}

      {hasBank && (
        <section className="bank-row" aria-label="Your accounts">
          {s.banks.map((b) => (
            <div key={b.id} className={`bank-card ${b.error ? 'bank-bad' : ''}`}>
              <span className="bank-icon" aria-hidden="true">{b.type === 'credit' ? <CreditCard size={20} /> : <Landmark size={20} />}</span>
              <div className="bank-text">
                <span className="bank-name">{b.name} ••{b.mask}</span>
                <span className="bank-balance">
                  {b.balance_cents == null ? '—' : money(b.balance_cents)}
                  <small>{b.type === 'credit' ? ' owed' : ' balance'}</small>
                </span>
                {b.error && (
                  <span className="error small"><CircleAlert size={14} aria-hidden="true" /> {b.error}</span>
                )}
              </div>
              {b.error && <ConnectBank small itemId={b.item_id} label="Reconnect" onDone={refreshAll} />}
            </div>
          ))}
          <MonthTile s={s} />
          <AddBank s={s} onDone={refreshAll} />
        </section>
      )}

      {hasBank && <SyncLine s={s} setS={setS} onDone={refreshAll} />}

      {hasChart && hasBank && <ChaseCheck tick={tick} onChange={load} />}

      {hasChart && (
        <>
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === 'review'} className={tab === 'review' ? 'is-on' : ''} onClick={() => setTab('review')}>
              To review {s.review_count > 0 && <span className="count">{s.review_count}</span>}
            </button>
            <button role="tab" aria-selected={tab === 'all'} className={tab === 'all' ? 'is-on' : ''} onClick={() => setTab('all')}>
              All transactions
            </button>
          </div>
          {tab === 'review'
            ? <ReviewList key={`r${tick}`} accounts={accounts} onChange={load} />
            : <AllList key={`a${tick}`} accounts={accounts} onChange={load} />}
        </>
      )}
    </div>
  )
}

function BooksSteps({ s, onDone }: { s: BooksSummary; onDone: () => void }) {
  const steps = [
    {
      done: s.chart_count > 0,
      title: 'Bring in your QuickBooks categories',
      note: s.chart_count > 0 ? `${s.chart_count} categories` : 'And your history, if you like',
      action: <Link to="/books/setup" className="btn btn-small">Open QuickBooks import</Link>,
    },
    {
      done: s.banks.length > 0,
      title: 'Connect Chase',
      note: s.plaid_keys ? 'Sign in to Chase in a safe Plaid window' : 'First add your Plaid keys in Settings',
      action: s.plaid_keys
        ? <ConnectBank label="Connect Chase" onDone={onDone} />
        : <Link to="/settings" className="btn btn-small">Open Settings</Link>,
    },
  ]
  return (
    <section className="setup-steps setup-money">
      <h2>Set up your books</h2>
      <ol>
        {steps.map((st) => (
          <li key={st.title} className={st.done ? 'is-done' : ''}>
            <span className="tick">{st.done ? <Check size={18} strokeWidth={2.5} aria-hidden="true" /> : null}</span>
            <span className="step-body">
              <strong>{st.title}</strong>
              <span className="muted small">{st.note}</span>
              {!st.done && <span className="step-action">{st.action}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function MonthTile({ s }: { s: BooksSummary }) {
  const max = Math.max(s.month.in_cents, s.month.out_cents, 1)
  return (
    <div className="month-tile" aria-label={`${s.month.label}: ${money(s.month.in_cents)} in, ${money(s.month.out_cents)} out`}>
      <span className="month-label">{s.month.label} so far</span>
      <div className="bar-row">
        <span className="bar-name">In</span>
        <span className="bar"><span className="bar-in" style={{ width: `${(s.month.in_cents / max) * 100}%` }} /></span>
        <span className="bar-val">{money(s.month.in_cents)}</span>
      </div>
      <div className="bar-row">
        <span className="bar-name">Out</span>
        <span className="bar"><span className="bar-out" style={{ width: `${(s.month.out_cents / max) * 100}%` }} /></span>
        <span className="bar-val">{money(s.month.out_cents)}</span>
      </div>
    </div>
  )
}

function Amount({ cents }: { cents: number }) {
  return (
    <span className={`amount ${cents > 0 ? 'amount-in' : 'amount-out'}`}>
      {cents > 0 ? <ArrowDownLeft size={15} aria-hidden="true" /> : <ArrowUpRight size={15} aria-hidden="true" />}
      {money(cents, true)}
    </span>
  )
}

function ReviewList({ accounts, onChange }: { accounts: LedgerAccount[]; onChange: () => void }) {
  const [items, setItems] = useState<Txn[] | null>(null)
  const [note, setNote] = useState('')
  const load = useCallback(() => {
    api.transactions('review').then((r) => setItems(r.items)).catch(() => setItems([]))
  }, [])
  useEffect(load, [load])

  async function runRules() {
    const r = await api.runRules().catch(() => null)
    if (r) {
      setNote(r.sorted > 0 ? `Your rules sorted ${r.sorted} more.` : 'Your rules have nothing new to sort here.')
      load()
      onChange()
    }
  }

  if (!items) return null
  if (items.length === 0) {
    return (
      <div className="all-clear">
        <span className="all-clear-icon"><Check size={34} strokeWidth={2} aria-hidden="true" /></span>
        <h2>Everything is sorted</h2>
        <p className="muted">New transactions that Savannah isn't sure about will show up here.</p>
      </div>
    )
  }
  return (
    <section className="review-list" aria-label="Transactions to review">
      <div className="btn-row">
        <button className="btn btn-small" onClick={runRules}><Sparkles size={16} aria-hidden="true" /> Run my rules</button>
        {note && <span className="success" role="status"><Check size={16} aria-hidden="true" /> {note}</span>}
      </div>
      {items.map((t) => (
        <ReviewItem
          key={t.id}
          t={t}
          accounts={accounts}
          onSaved={(also) => {
            setNote(also < 0 ? 'Saved. Your new rule will suggest this category from now on.'
              : also > 0 ? `Saved. Your new rule also sorted ${also} more.` : 'Saved.')
            setItems((xs) => (xs || []).filter((x) => x.id !== t.id))
            if (also !== 0) load()
            onChange()
          }}
        />
      ))}
    </section>
  )
}

function ReviewItem({ t, accounts, onSaved }: { t: Txn; accounts: LedgerAccount[]; onSaved: (also: number) => void }) {
  const [cat, setCat] = useState<number | null>(t.category_id)
  const [always, setAlways] = useState(false)
  const [match, setMatch] = useState(t.suggested_rule)
  const [mode, setMode] = useState<RuleMode>('auto')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [splitting, setSplitting] = useState(t.splits.length > 0)

  async function save() {
    if (!cat) return setError('Choose a category first.')
    if (always && !match.trim()) return setError('Type the words to look for, or untick "Always".')
    setBusy(true)
    try {
      const r = await api.setCategory(t.id, cat, always, match, mode)
      onSaved(always && mode === 'suggest' ? -1 : r.also_sorted)
    } catch (e) {
      setError((e as ApiError).message)
      setBusy(false)
    }
  }

  return (
    <article className="review-item">
      <div className="txn-top">
        <span className="txn-date">{shortDate(t.date)}</span>
        <span className="txn-desc">
          <strong>{t.merchant || t.description}</strong>
          <span className="muted small">{t.merchant ? `${t.description}, ` : ''}{t.account}</span>
        </span>
        <Amount cents={t.amount_cents} />
      </div>
      {splitting ? (
        <SplitEditor t={t} accounts={accounts} onDone={() => onSaved(0)} onCancel={() => setSplitting(false)} />
      ) : (<>
      <div className="txn-pick">
        {t.category_source === 'ai' && cat === t.category_id && (
          <span className="guess-tag"><Sparkles size={14} aria-hidden="true" /> Savannah's guess</span>
        )}
        {(t.category_source === 'rule' || t.category_source === 'rule-split') && cat === t.category_id && (
          <span className="guess-tag rule-tag"><Wand2 size={14} aria-hidden="true" /> Suggested by your rule</span>
        )}
        <CategorySelect accounts={accounts} value={cat} onChange={(id) => { setCat(id); setError('') }} label={`Category for ${t.description}`} moneyIn={t.amount_cents > 0} />
        <button className="btn btn-money" onClick={save} disabled={busy || !cat}>
          <Check size={18} aria-hidden="true" /> {busy ? 'Saving…' : 'Save'}
        </button>
        <button className="link-btn" onClick={() => setSplitting(true)}><Split size={16} aria-hidden="true" /> Split</button>
      </div>
      <label className="always">
        <input type="checkbox" checked={always} onChange={(e) => { setAlways(e.target.checked); setError('') }} />
        <span>Always do this when the description has</span>
        <input className="always-text" value={match} onChange={(e) => { setMatch(e.target.value); setError('') }} aria-label="Words to look for" disabled={!always} />
      </label>
      {always && (
        <div className="mode-pick" role="radiogroup" aria-label="What the rule should do">
          <button role="radio" aria-checked={mode === 'auto'} className={mode === 'auto' ? 'is-on' : ''} onClick={() => setMode('auto')}>
            <Zap size={15} aria-hidden="true" /> File it automatically
          </button>
          <button role="radio" aria-checked={mode === 'suggest'} className={mode === 'suggest' ? 'is-on' : ''} onClick={() => setMode('suggest')}>
            <Lightbulb size={15} aria-hidden="true" /> Just suggest it
          </button>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      </>)}
    </article>
  )
}

function AllList({ accounts, onChange }: { accounts: LedgerAccount[]; onChange: () => void }) {
  const [q, setQ] = useState('')
  const [month, setMonth] = useState('')
  const [data, setData] = useState<{ total: number; items: Txn[] } | null>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [splitting, setSplitting] = useState<number | null>(null)

  const load = useCallback((more = false) => {
    api.transactions('all', q, month, more ? data?.items.length ?? 0 : 0)
      .then((r) => setData((d) => (more && d ? { total: r.total, items: [...d.items, ...r.items] } : r)))
      .catch(() => {})
  }, [q, month, data?.items.length])

  useEffect(() => {
    const t = setTimeout(() => load(false), 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, month])

  async function change(t: Txn, id: number) {
    await api.setCategory(t.id, id).catch(() => {})
    setEditing(null)
    setData((d) => d && { ...d, items: d.items.map((x) => (x.id === t.id ? { ...x, category_id: id, category: accounts.find((a) => a.id === id)?.name || '', needs_review: false } : x)) })
    onChange()
  }

  return (
    <section className="all-list" aria-label="All transactions">
      <div className="filters">
        <label className="search">
          <Search size={18} aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search descriptions" aria-label="Search descriptions" />
        </label>
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" className="month-input" />
        {(q || month) && <button className="link-btn" onClick={() => { setQ(''); setMonth('') }}>Clear</button>}
      </div>
      {data && <p className="muted small">{data.total} transactions</p>}
      <ul className="txn-list">
        {data?.items.map((t) => (
          <li key={t.id} className={`txn-row ${splitting === t.id ? 'is-splitting' : ''}`}>
            <span className="txn-date">{shortDate(t.date)}</span>
            <span className="txn-desc">
              <strong>{t.merchant || t.description}</strong>
              <span className="muted small">
                {t.source === 'journal' ? 'Journal entry from QuickBooks' : `${t.account}${t.source === 'quickbooks' ? ', from QuickBooks' : ''}`}
              </span>
            </span>
            {editing === t.id ? (
              <span className="pick-inline">
                <CategorySelect accounts={accounts} value={t.category_id} onChange={(id) => change(t, id)} label={`Category for ${t.description}`} moneyIn={t.amount_cents > 0} />
                {t.source !== 'journal' && (
                  <button className="link-btn" onClick={() => { setEditing(null); setSplitting(t.id) }}><Split size={15} aria-hidden="true" /> Split</button>
                )}
              </span>
            ) : t.splits.length > 0 ? (
              <button className="cat-pill cat-split" onClick={() => t.source !== 'journal' && setSplitting(splitting === t.id ? null : t.id)}
                title={t.splits.map((s) => `${s.category}: ${money(Math.abs(s.amount_cents))}`).join('\n')}>
                <Split size={13} aria-hidden="true" /> {t.splits[0].category.split(':').pop()}{t.splits.length > 1 ? ` + ${t.splits.length - 1} more` : ''}
              </button>
            ) : (
              <button className={`cat-pill ${t.category ? '' : 'cat-empty'} ${t.needs_review ? 'cat-review' : ''}`} onClick={() => setEditing(t.id)}>
                {t.category || 'No category'}
              </button>
            )}
            {t.source === 'journal' ? <span className="amount muted">—</span> : <Amount cents={t.amount_cents} />}
            {splitting === t.id && (
              <div className="row-editor">
                <SplitEditor t={t} accounts={accounts} onCancel={() => setSplitting(null)} onDone={() => { setSplitting(null); load(false); onChange() }} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {data && data.items.length < data.total && (
        <button className="btn" onClick={() => load(true)}>Show more</button>
      )}
    </section>
  )
}

/** Does Savannah's balance for each account equal what Chase says? */
function ChaseCheck({ tick, onChange }: { tick: number; onChange: () => void }) {
  const [rows, setRows] = useState<BalanceCheck[] | null>(null)
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState('')
  const load = useCallback(() => { api.balanceCheck().then(setRows).catch(() => setRows([])) }, [])
  useEffect(load, [load, tick])
  if (!rows || rows.length === 0) return null

  const off = rows.filter((r) => !r.matches && !r.left_out)
  const allGood = off.length === 0

  const act = (id: string, label: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(id + label); setMsg('')
    fn().then(() => { setMsg(done); load(); onChange(); setTimeout(load, 4000) })
      .catch((e: ApiError) => setMsg(e.message))
      .finally(() => setBusy(''))
  }

  return (
    <section className="bal-check" aria-label="Do your balances match Chase?">
      <button className={`chip ${allGood ? 'chip-good' : 'chip-bad'}`} onClick={() => setOpen(!open)} aria-expanded={open}>
        {allGood ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}
        {allGood ? 'Balances match your banks' : `${off.length} account${off.length === 1 ? " doesn't" : "s don't"} match the bank`}
        <span className="muted small">{open ? 'Hide' : 'See'}</span>
      </button>
      {msg && <p className="success small">{msg}</p>}
      {open && rows.map((r) => (
        <div key={r.bank_account_id} className={`bal-row ${r.matches ? 'is-ok' : ''}`}>
          <div className="bal-top">
            <span className="bal-name">
              {r.card ? <CreditCard size={18} aria-hidden="true" /> : <Landmark size={18} aria-hidden="true" />}
              {r.name}
            </span>
            {r.left_out ? <span className="chip">Left out (personal)</span>
              : r.matches ? <span className="chip chip-good"><Check size={14} aria-hidden="true" /> Matches</span>
              : r.counted_twice ? <span className="chip chip-bad">Counted twice</span>
              : <span className="chip chip-bad">Off by {money(Math.abs(r.difference_cents))}</span>}
          </div>
          {!r.left_out && (
            <div className={`bal-nums ${r.matches ? '' : 'bal-off'}`}>
              <div><span>Bank says</span><strong>{money(r.chase_cents)}</strong></div>
              <div><span>Savannah says</span><strong>{money(r.savannah_cents)}</strong></div>
              <div><span>In your books as</span><strong className="small">{r.ledger_name || '—'}</strong></div>
            </div>
          )}
          {!r.matches && !r.left_out && (
            <div className="bal-actions">
              {r.suggestion ? (
                <button className="btn btn-small btn-primary" disabled={!!busy}
                  onClick={() => act(r.bank_account_id, 'pair', () => api.mapBank(r.bank_account_id, r.suggestion!.id), `Paired with ${r.suggestion!.name}.`)}>
                  <Link2 size={16} aria-hidden="true" /> Pair with “{r.suggestion.name}”{r.suggestion.why ? `: ${r.suggestion.why}` : ' (fixes it)'}
                </button>
              ) : !r.full_history && !r.in_quickbooks && (
                <button className="btn btn-small btn-primary" disabled={!!busy}
                  onClick={() => act(r.bank_account_id, 'hist', () => api.useHistory(r.bank_account_id), 'Brought in its Chase history.')}>
                  <History size={16} aria-hidden="true" /> Bring in its Chase history
                </button>
              )}
              <button className="btn btn-small" disabled={!!busy}
                onClick={() => act(r.bank_account_id, 'out', () => api.leaveOut(r.bank_account_id, true), `${r.name} is left out of the books.`)}>
                <UserRound size={16} aria-hidden="true" /> It's personal, leave it out
              </button>
            </div>
          )}
          {r.left_out && (
            <div className="bal-actions">
              <button className="btn btn-small" disabled={!!busy}
                onClick={() => act(r.bank_account_id, 'back', () => api.leaveOut(r.bank_account_id, false), `${r.name} is back in the books.`)}>
                <Undo2 size={16} aria-hidden="true" /> Bring it back
              </button>
            </div>
          )}
        </div>
      ))}
    </section>
  )
}

/** Connect another bank or card through Plaid, while staying inside Plaid's free connections. */
function AddBank({ s, onDone }: { s: BooksSummary; onDone: () => void }) {
  const used = s.plaid_items_used ?? 0
  const limit = s.plaid_item_limit ?? 10
  const left = Math.max(limit - used, 0)
  return (
    <div className="bank-card bank-add">
      <div className="bank-text">
        <span className="bank-name">Add a bank or card</span>
        <span className="plaid-meter" role="img" aria-label={`${used} of ${limit} free Plaid connections used`}>
          {Array.from({ length: limit }, (_, i) => <i key={i} className={i < used ? 'is-used' : ''} />)}
        </span>
        <small className="muted">{used} of {limit} free connections used{s.plaid_institutions?.length ? ` · ${s.plaid_institutions.join(', ')}` : ''}</small>
      </div>
      {left > 0
        ? <ConnectBank small label="Connect" onDone={onDone} />
        : <small className="error">All free connections used</small>}
      {left > 0 && left <= 3 && <small className="muted">Each new bank login uses one for good, even if removed later.</small>}
    </div>
  )
}


// ---------- Update now: spins until the banks are really done ----------

function SyncLine({ s, setS, onDone }: { s: BooksSummary; setS: (x: BooksSummary) => void; onDone: () => void }) {
  const [updating, setUpdating] = useState(false)
  const [done, setDone] = useState('')
  const [err, setErr] = useState('')
  const busy = updating || s.syncing

  async function update() {
    const before = s.last_sync_at
    setUpdating(true)
    setDone('')
    setErr('')
    try {
      await api.syncBank()
    } catch (e) {
      setErr((e as ApiError).message)
      setUpdating(false)
      return
    }
    const started = Date.now()
    const check = async () => {
      try {
        const x = await api.books()
        setS(x)
        const finished = !x.syncing && x.last_sync_at !== before
        if (finished || Date.now() - started > 180_000) {
          setUpdating(false)
          onDone()
          if (finished && !x.last_error) {
            const n = x.last_result?.new ?? 0
            setDone(n === 0 ? 'Up to date. No new transactions.' : `Done. ${n} new transaction${n === 1 ? '' : 's'}.`)
            setTimeout(() => setDone(''), 8000)
          }
          return
        }
      } catch { /* keep trying */ }
      setTimeout(check, 1500)
    }
    setTimeout(check, 1200)
  }

  return (
    <div className="sync-line" aria-live="polite">
      <span className={`chip ${s.last_error && !busy ? 'chip-bad' : busy ? 'chip-busy' : 'chip-good'}`}>
        {busy
          ? <RefreshCw size={16} aria-hidden="true" className="spin" />
          : s.last_error ? <CircleAlert size={16} aria-hidden="true" /> : <span className="dot" />}
        {busy
          ? 'Updating transactions and balances…'
          : done || s.last_error || (s.last_sync_at ? `Updated ${timeAgo(s.last_sync_at)}` : 'Not updated yet since restart')}
      </span>
      <button className="btn btn-small" disabled={busy} onClick={update} aria-busy={busy}>
        <RefreshCw size={16} aria-hidden="true" className={busy ? 'spin' : ''} /> {busy ? 'Updating…' : 'Update now'}
      </button>
      {err && <span className="error small" role="alert">{err}</span>}
    </div>
  )
}
