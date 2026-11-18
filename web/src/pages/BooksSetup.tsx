import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowLeft, ArrowUpRight, Check, FileSpreadsheet, Lightbulb, ListTree, Repeat, Split, Trash2, Upload, Wand2, Zap } from 'lucide-react'
import {
  api, ApiError, longDate, money, shortDate, type BooksSummary, type ImportFile, type JournalPreview, type LedgerAccount, type Preview, type Rule,
  type RuleMode,
} from '../api'

export default function BooksSetup() {
  const [s, setS] = useState<BooksSummary | null>(null)
  const [files, setFiles] = useState<{ folder: string; files: ImportFile[] } | null>(null)
  const [accounts, setAccounts] = useState<LedgerAccount[]>([])
  const load = useCallback(() => {
    api.books().then(setS).catch(() => {})
    api.importFiles().then(setFiles).catch(() => {})
    api.accounts().then(setAccounts).catch(() => {})
  }, [])
  useEffect(load, [load])

  return (
    <div className="books-setup">
      <Link to="/books" className="link-btn back"><ArrowLeft size={16} aria-hidden="true" /> Books</Link>
      <h1 className="display">Books setup</h1>

      <FilesPanel files={files} onChange={load} />
      <CategoriesPanel s={s} files={files?.files || []} accounts={accounts} onChange={load} />
      <HistoryPanel s={s} files={files?.files || []} onChange={load} />
      <JournalPanel s={s} files={files?.files || []} onChange={load} />
      {s && s.banks.length > 0 && <BankPairing s={s} accounts={accounts} onChange={load} />}
      <RulesPanel />
    </div>
  )
}

function FilesPanel({ files, onChange }: { files: { folder: string; files: ImportFile[] } | null; onChange: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [msg, setMsg] = useState('')
  async function pick(list: FileList | null) {
    if (!list?.length) return
    setMsg('')
    try {
      for (const f of Array.from(list)) await api.upload(f)
      onChange()
    } catch (e) {
      setMsg((e as ApiError).message)
    }
  }
  return (
    <section className="panel">
      <h2><FileSpreadsheet size={20} aria-hidden="true" /> Your QuickBooks files</h2>
      <p className="muted small">Savannah looks in this folder. You can also add files with the button.</p>
      {files && <code className="path">{files.folder}</code>}
      {files && files.files.length > 0 ? (
        <ul className="file-list">
          {files.files.map((f) => (
            <li key={f.name}>
              <FileSpreadsheet size={18} aria-hidden="true" />
              <span>{f.name}</span>
              <span className={`file-kind kind-${f.kind || 'none'}`}>
                {f.kind === 'accounts' ? 'Account List' : f.kind === 'transactions' ? 'Transactions' : f.kind === 'journal' ? 'Journal' : 'Not recognized'}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        files && <p className="muted">No files yet.</p>
      )}
      <input ref={input} type="file" accept=".xlsx,.csv" multiple hidden onChange={(e) => pick(e.target.files)} />
      <button className="btn btn-small" onClick={() => input.current?.click()}><Upload size={16} aria-hidden="true" /> Add a file</button>
      {msg && <p className="error" role="alert">{msg}</p>}
    </section>
  )
}

function CategoriesPanel({ s, files, accounts, onChange }: { s: BooksSummary | null; files: ImportFile[]; accounts: LedgerAccount[]; onChange: () => void }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const lists = files.filter((f) => f.kind === 'accounts')
  async function run(fn: () => Promise<string>) {
    setBusy(true)
    try {
      setMsg({ ok: true, text: await fn() })
      onChange()
    } catch (e) {
      setMsg({ ok: false, text: (e as ApiError).message })
    }
    setBusy(false)
  }
  const counts = { income: 0, expense: 0, transfer: 0, owner: 0 }
  accounts.forEach((a) => { counts[a.kind] += 1 })
  return (
    <section className="panel">
      <h2><ListTree size={20} aria-hidden="true" /> Step 1: Categories</h2>
      {s && s.chart_count > 0 ? (
        <div className="cat-summary">
          <span className="chip"><ArrowDownLeft size={16} aria-hidden="true" /> {counts.income} income</span>
          <span className="chip"><ArrowUpRight size={16} aria-hidden="true" /> {counts.expense} expense</span>
          <span className="chip"><Repeat size={16} aria-hidden="true" /> {counts.transfer} accounts</span>
          {s.chart_from_quickbooks && <span className="chip chip-good"><Check size={16} aria-hidden="true" /> From QuickBooks</span>}
        </div>
      ) : (
        <p>Bring in your QuickBooks <strong>Account List</strong> so Savannah uses the same categories.</p>
      )}
      <div className="btn-row">
        {lists.map((f) => (
          <button key={f.name} className="btn btn-money" disabled={busy}
            onClick={() => run(async () => { const r = await api.importAccounts(f.name); return `Imported: ${r.added} new, ${r.updated} updated.` })}>
            <Upload size={18} aria-hidden="true" /> Import {f.name}
          </button>
        ))}
        {s && s.chart_count === 0 && (
          <button className="btn btn-small" disabled={busy}
            onClick={() => run(async () => { const r = await api.starterChart(); return `Added ${r.added} starter categories.` })}>
            <Wand2 size={16} aria-hidden="true" /> No QuickBooks? Use a starter list
          </button>
        )}
      </div>
      {lists.length === 0 && (!s || s.chart_count === 0) && (
        <p className="muted small">No Account List found yet. In QuickBooks: Reports → Account List → Export → Excel.</p>
      )}
      {msg && <p className={msg.ok ? 'success' : 'error'} role="status">{msg.text}</p>}
    </section>
  )
}

function HistoryPanel({ s, files, onChange }: { s: BooksSummary | null; files: ImportFile[]; onChange: () => void }) {
  const lists = files.filter((f) => f.kind === 'transactions')
  const [file, setFile] = useState('')
  const [flip, setFlip] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [start, setStart] = useState('')

  useEffect(() => { if (!file && lists[0]) setFile(lists[0].name) }, [lists, file])
  useEffect(() => { setStart(s?.start_date || '') }, [s?.start_date])

  async function look(f: string, fl: boolean) {
    setBusy(true)
    setMsg(null)
    try {
      setPreview(await api.previewHistory(f, fl))
    } catch (e) {
      setPreview(null)
      setMsg({ ok: false, text: (e as ApiError).message })
    }
    setBusy(false)
  }

  async function confirm() {
    setBusy(true)
    try {
      const r = await api.importHistory(file, flip)
      setMsg({ ok: true, text: `Imported ${r.added} transactions${r.already_there ? ` (${r.already_there} were already there)` : ''}.` })
      setPreview(null)
      onChange()
    } catch (e) {
      setMsg({ ok: false, text: (e as ApiError).message })
    }
    setBusy(false)
  }

  const noChart = !s || s.chart_count === 0
  return (
    <section className="panel">
      <h2><FileSpreadsheet size={20} aria-hidden="true" /> Step 2: History</h2>
      {s && s.quickbooks_history > 0 && (
        <p className="success"><Check size={16} aria-hidden="true" /> {s.quickbooks_history} transactions from QuickBooks are in Savannah.</p>
      )}
      <p className="muted small">Your past transactions teach Savannah how you categorize, and feed the reports in phase 4.</p>
      {noChart ? (
        <p className="muted">Do step 1 first.</p>
      ) : lists.length === 0 ? (
        <p className="muted small">No transaction file found yet. In QuickBooks: Reports → Transaction List by Date → All Dates → Export → Excel.</p>
      ) : (
        <div className="btn-row">
          {lists.length > 1 && (
            <select className="cat-select" value={file} onChange={(e) => { setFile(e.target.value); setPreview(null) }} aria-label="File">
              {lists.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
          )}
          <button className="btn btn-money" disabled={busy || !file} onClick={() => { setFlip(false); look(file, false) }}>
            <FileSpreadsheet size={18} aria-hidden="true" /> {busy && !preview ? 'Reading…' : `Look at ${lists.length > 1 ? 'this file' : file}`}
          </button>
        </div>
      )}

      {preview && (
        <div className="preview">
          <div className="preview-stats">
            <div><span className="big">{preview.count.toLocaleString()}</span><span className="muted small">transactions</span></div>
            <div><span className="big">{shortDate(preview.first)} – {shortDate(preview.last)}</span><span className="muted small">{preview.first.slice(0, 4)}{preview.first.slice(0, 4) !== preview.last.slice(0, 4) ? `–${preview.last.slice(0, 4)}` : ''}</span></div>
            <div><span className="big amount-in">{money(preview.money_in_cents)}</span><span className="muted small">money in</span></div>
            <div><span className="big">{money(preview.money_out_cents)}</span><span className="muted small">money out</span></div>
          </div>
          <p className="preview-q">Do these look right? Deposits and payouts should be <span className="amount-in">green, money in</span>.</p>
          <ul className="txn-list">
            {preview.samples.map((t, i) => (
              <li key={i} className="txn-row">
                <span className="txn-date">{shortDate(t.date)}</span>
                <span className="txn-desc"><strong>{t.description}</strong><span className="muted small">{t.account}{t.category ? `, ${t.category}` : ''}</span></span>
                <span className={`amount ${t.amount_cents > 0 ? 'amount-in' : 'amount-out'}`}>
                  {t.amount_cents > 0 ? <ArrowDownLeft size={15} aria-hidden="true" /> : <ArrowUpRight size={15} aria-hidden="true" />}{money(t.amount_cents, true)}
                </span>
              </li>
            ))}
          </ul>
          {preview.skipped > 0 && (
            <p className="muted small">Left out {preview.skipped} {preview.skipped === 1 ? "row that isn't a Chase transaction" : "rows that aren't Chase transactions"} (like invoices or journal entries).</p>
          )}
          <div className="btn-row">
            <button className="btn btn-money" disabled={busy} onClick={confirm}><Check size={18} aria-hidden="true" /> Looks right, import</button>
            <button className="btn btn-small" disabled={busy} onClick={() => { const f = !flip; setFlip(f); look(file, f) }}>
              <Repeat size={16} aria-hidden="true" /> In and out are swapped
            </button>
          </div>
        </div>
      )}
      {msg && <p className={msg.ok ? 'success' : 'error'} role="status">{msg.text}</p>}

      {s?.start_date && (
        <div className="start-date">
          <div className="timeline" aria-hidden="true">
            <span className="tl-qb">QuickBooks history</span>
            <span className="tl-sv">Savannah</span>
          </div>
          <p>Savannah's own books start on <strong>{longDate(s.start_date)}</strong>. Older bank transactions come from QuickBooks instead, so nothing is counted twice.</p>
          <label className="inline-date">
            <span className="muted small">Change start date</span>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            <button className="btn btn-small" disabled={!start || start === s.start_date}
              onClick={() => api.setStartDate(start).then(onChange).catch(() => {})}>Save</button>
          </label>
        </div>
      )}
    </section>
  )
}

function JournalPanel({ s, files, onChange }: { s: BooksSummary | null; files: ImportFile[]; onChange: () => void }) {
  const journals = files.filter((f) => f.kind === 'journal')
  const [preview, setPreview] = useState<JournalPreview | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const file = journals[0]?.name || ''

  async function look() {
    setBusy(true)
    setMsg(null)
    try { setPreview(await api.previewJournal(file)) } catch (e) { setMsg({ ok: false, text: (e as ApiError).message }) }
    setBusy(false)
  }
  async function confirm() {
    setBusy(true)
    try {
      const r = await api.importJournal(file)
      setMsg({ ok: true, text: `Done: ${r.splits_filled} split payments filled in and ${r.journal_entries} journal entries added.` })
      setPreview(null)
      onChange()
    } catch (e) { setMsg({ ok: false, text: (e as ApiError).message }) }
    setBusy(false)
  }

  if (!s || s.quickbooks_history === 0) return null
  return (
    <section className="panel">
      <h2><Split size={20} aria-hidden="true" /> Step 3: Split payments and journal entries</h2>
      <p className="muted small">
        QuickBooks' Journal report has the parts of payments like your mortgage (interest, escrow, principal)
        and entries made by hand. With it, your P&L matches QuickBooks.
      </p>
      {journals.length === 0 ? (
        <p className="muted small">No Journal file yet. In QuickBooks: Reports → Journal → All Dates → Export → Excel.</p>
      ) : (
        <button className="btn btn-money" onClick={look} disabled={busy}><FileSpreadsheet size={18} aria-hidden="true" /> {busy && !preview ? 'Reading…' : `Look at ${file}`}</button>
      )}
      {preview && (
        <div className="preview">
          <div className="preview-stats">
            <div><span className="big">{preview.splits_filled}</span><span className="muted small">split payments filled in</span></div>
            <div><span className="big">{preview.journal_entries}</span><span className="muted small">journal entries to add</span></div>
            <div><span className="big">{preview.splits_still_missing}</span><span className="muted small">split payments still without parts</span></div>
          </div>
          {preview.samples[0] && (
            <div className="split-sample">
              <span className="muted small">For example, {preview.samples.find((x) => /mortgage/i.test(x.name))?.name || preview.samples[0].name}:</span>
              <ul>
                {(preview.samples.find((x) => /mortgage/i.test(x.name)) || preview.samples[0]).parts.map((p, i) => (
                  <li key={i}><span>{p.category}</span><strong>{money(Math.abs(p.cents))}</strong></li>
                ))}
              </ul>
            </div>
          )}
          {preview.pl_effect.length > 0 && (
            <>
              <p className="preview-q">What this adds to your P&L (all years):</p>
              <ul className="effect-list">
                {preview.pl_effect.map((e) => (
                  <li key={e.name}><span>{e.name}</span><strong>{money(Math.abs(e.cents))}</strong><span className="muted small">{e.label}</span></li>
                ))}
              </ul>
            </>
          )}
          {preview.unknown_accounts.length > 0 && (
            <p className="muted small">Skipped lines for accounts not in your list: {preview.unknown_accounts.join(', ')}.</p>
          )}
          <div className="btn-row">
            <button className="btn btn-money" onClick={confirm} disabled={busy}><Check size={18} aria-hidden="true" /> Looks right, import</button>
          </div>
        </div>
      )}
      {msg && <p className={msg.ok ? 'success' : 'error'} role="status">{msg.text}</p>}
    </section>
  )
}

function BankPairing({ s, accounts, onChange }: { s: BooksSummary; accounts: LedgerAccount[]; onChange: () => void }) {
  const money_ = accounts.filter((a) => a.kind === 'transfer' && /bank|credit card/i.test(a.type))
  return (
    <section className="panel">
      <h2><Repeat size={20} aria-hidden="true" /> Chase accounts</h2>
      <p className="muted small">Which QuickBooks account each Chase account matches.</p>
      <ul className="pair-list">
        {s.banks.map((b) => (
          <li key={b.id}>
            <span><strong>{b.name}</strong> ••{b.mask}</span>
            <span aria-hidden="true">→</span>
            <select className="cat-select" value={b.ledger_account_id ?? ''} aria-label={`QuickBooks account for ${b.name}`}
              onChange={(e) => api.mapBank(b.id, Number(e.target.value)).then(onChange).catch(() => {})}>
              {money_.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </li>
        ))}
      </ul>
    </section>
  )
}

function RulesPanel() {
  const [rules, setRules] = useState<Rule[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => api.rules().then(setRules).catch(() => {})
  useEffect(() => { load() }, [])
  async function changeMode(r: Rule, mode: RuleMode) {
    if (r.mode === mode) return
    setRules((xs) => xs.map((x) => (x.id === r.id ? { ...x, mode } : x)))
    try {
      const res = await api.setRuleMode(r.id, mode)
      setNote(mode === 'auto'
        ? `“${r.match}” now files by itself${res.filed ? `, and filed ${res.filed} waiting` : ''}.`
        : `“${r.match}” will now only suggest. New matches wait in "To review".`)
    } catch (e) {
      setNote((e as ApiError).message)
      load()
    }
  }
  async function runNow() {
    setBusy(true)
    try {
      const r = await api.runRules()
      setNote(r.sorted > 0 ? `Sorted ${r.sorted} transaction${r.sorted === 1 ? '' : 's'}.` : 'Everything already follows your rules.')
      load()
    } catch (e) {
      setNote((e as ApiError).message)
    }
    setBusy(false)
  }
  return (
    <section className="panel">
      <h2><Wand2 size={20} aria-hidden="true" /> Your rules</h2>
      <p className="muted small">Rules run by themselves on every new Chase transaction. Pick what each one does:</p>
      <div className="mode-legend">
        <span><Zap size={15} aria-hidden="true" /> <strong>Auto</strong> files it and skips "To review"</span>
        <span><Lightbulb size={15} aria-hidden="true" /> <strong>Suggest</strong> fills in the category and waits for your OK</span>
      </div>
      {rules.length > 0 && (
        <div className="btn-row">
          <button className="btn btn-money" onClick={runNow} disabled={busy}>
            <Wand2 size={18} aria-hidden="true" /> {busy ? 'Running…' : 'Run rules now'}
          </button>
          {note && <span className="success" role="status"><Check size={16} aria-hidden="true" /> {note}</span>}
        </div>
      )}
      {rules.length === 0 ? (
        <p className="muted small">When you review a transaction, tick "Always do this" to make a rule. Rules show up here.</p>
      ) : (
        <ul className="rule-list">
          {rules.map((r) => (
            <li key={r.id} className="rule-row">
              <span className="rule-text">
                When it says “{r.match}” {r.direction === 'in' ? '(money in)' : r.direction === 'out' ? '(money out)' : ''}
                <span aria-hidden="true"> → </span><strong>{r.category}</strong>
                <span className="muted small"> · used {r.times_used}×</span>
              </span>
              <span className="mode-pick mode-small" role="radiogroup" aria-label={`What the rule for ${r.match} does`}>
                <button role="radio" aria-checked={r.mode === 'auto'} className={r.mode === 'auto' ? 'is-on' : ''} onClick={() => changeMode(r, 'auto')}>
                  <Zap size={14} aria-hidden="true" /> Auto
                </button>
                <button role="radio" aria-checked={r.mode === 'suggest'} className={r.mode === 'suggest' ? 'is-on' : ''} onClick={() => changeMode(r, 'suggest')}>
                  <Lightbulb size={14} aria-hidden="true" /> Suggest
                </button>
              </span>
              <button className="link-btn" aria-label={`Delete rule ${r.match}`} onClick={() => api.deleteRule(r.id).then(load)}>
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
