import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowDownLeft, ArrowUpRight, Bookmark, CalendarClock, ChevronDown, ChevronRight, CircleAlert, Download,
  Landmark, LineChart, Printer, RefreshCw, Save, Scale, TrendingUp, Waves, X,
} from 'lucide-react'
import { CircleCheck } from 'lucide-react'
import {
  api, ApiError, money, shortDate, stayDates, platformName,
  type BalanceSheet, type Booking, type CashFlow, type Detail, type PL, type ReportConfig, type ReportRow, type ReportSection, type SavedView, type Upcoming,
} from '../api'
import CashForecast from './CashForecast'

type ReportKey = 'pl' | 'cashflow' | 'bs' | 'upcoming' | 'forecast'

const REPORTS: { key: ReportKey; label: string; icon: typeof Scale }[] = [
  { key: 'pl', label: 'Profit & Loss', icon: Scale },
  { key: 'cashflow', label: 'Cash flow', icon: Waves },
  { key: 'bs', label: 'Balance sheet', icon: Landmark },
  { key: 'upcoming', label: 'Coming income', icon: CalendarClock },
  { key: 'forecast', label: 'Cash forecast', icon: LineChart },
]

// ---------- date ranges ----------

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

const PRESETS: { key: string; label: string }[] = [
  { key: 'this_month', label: 'This month' },
  { key: 'last_month', label: 'Last month' },
  { key: 'this_quarter', label: 'This quarter' },
  { key: 'last_quarter', label: 'Last quarter' },
  { key: 'ytd', label: 'This year so far' },
  { key: 'last_year', label: 'Last year' },
  { key: 'last_12', label: 'Last 12 months' },
  { key: 'this_year', label: 'This year, with booked months' },
  { key: 'next_12', label: 'Next 12 months (booked)' },
  { key: 'all', label: 'All time' },
  { key: 'custom', label: 'Pick dates' },
]

function presetRange(key: string, first: string | null): [string, string] | null {
  const t = new Date()
  const y = t.getFullYear(), m = t.getMonth()
  const q = Math.floor(m / 3)
  switch (key) {
    case 'this_month': return [iso(new Date(y, m, 1)), iso(t)]
    case 'last_month': return [iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))]
    case 'this_quarter': return [iso(new Date(y, q * 3, 1)), iso(t)]
    case 'last_quarter': return [iso(new Date(y, q * 3 - 3, 1)), iso(new Date(y, q * 3, 0))]
    case 'ytd': return [iso(new Date(y, 0, 1)), iso(t)]
    case 'last_year': return [iso(new Date(y - 1, 0, 1)), iso(new Date(y - 1, 11, 31))]
    case 'last_12': return [iso(new Date(y, m - 11, 1)), iso(t)]
    case 'this_year': return [iso(new Date(y, 0, 1)), iso(new Date(y, 11, 31))]
    case 'next_12': return [iso(new Date(y, m, 1)), iso(new Date(y, m + 12, 0))]
    case 'all': return [first || iso(new Date(y - 3, 0, 1)), iso(t)]
    default: return null
  }
}

const DEFAULT: ReportConfig = {
  preset: 'this_year', start: '', end: '', breakdown: 'month', compare: '',
  show: { total: true, pct: false, prev: true, change: true }, expand: true,
}

function withDates(c: ReportConfig, first: string | null): ReportConfig {
  const r = presetRange(c.preset, first)
  return r ? { ...c, start: r[0], end: r[1] } : c
}

// ---------- page ----------

export default function Reports() {
  const [report, setReport] = useState<ReportKey>(() => {
    try { return (localStorage.getItem('savannah.report') as ReportKey) || 'pl' } catch { return 'pl' }
  })
  const [first, setFirst] = useState<string | null>(null)
  const [cfg, setCfg] = useState<ReportConfig>(withDates(DEFAULT, null))
  const [views, setViews] = useState<SavedView[]>([])

  useEffect(() => {
    api.dataRange().then((r) => { setFirst(r.first); setCfg((c) => withDates(c, r.first)) }).catch(() => {})
    api.views().then(setViews).catch(() => {})
  }, [])
  useEffect(() => { try { localStorage.setItem('savannah.report', report) } catch { /* private mode */ } }, [report])

  const update = (patch: Partial<ReportConfig>) => setCfg((c) => withDates({ ...c, ...patch }, first))

  return (
    <div className="reports">
      <header className="reports-head">
        <h1 className="display">Reports</h1>
      </header>

      <div className="report-switch" role="tablist" aria-label="Report">
        {REPORTS.map(({ key, label, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={report === key} className={report === key ? 'is-on' : ''} onClick={() => setReport(key)}>
            <Icon size={18} aria-hidden="true" /> {label}
          </button>
        ))}
      </div>

      {(report === 'pl' || report === 'cashflow') && (
        <>
          <Controls cfg={cfg} update={update} report={report} />
          <SavedViews report={report} views={views} setViews={setViews} cfg={cfg} apply={(c) => setCfg(withDates(c, first))} />
        </>
      )}

      {report === 'pl' && <ProfitLoss cfg={cfg} update={update} />}
      {report === 'cashflow' && <CashFlowReport cfg={cfg} />}
      {report === 'bs' && <BalanceSheetReport />}
      {report === 'upcoming' && <ComingIncome />}
      {report === 'forecast' && <CashForecast />}
    </div>
  )
}

// ---------- controls: period, columns, comparison ----------

function Controls({ cfg, update, report }: { cfg: ReportConfig; update: (p: Partial<ReportConfig>) => void; report: ReportKey }) {
  const chip = (on: boolean, label: string, onClick: () => void, disabled = false) => (
    <button className={`col-chip ${on ? 'is-on' : ''}`} aria-pressed={on} onClick={onClick} disabled={disabled}>{label}</button>
  )
  return (
    <section className="report-controls" aria-label="Report settings">
      <label className="ctl">
        <span>Period</span>
        <select value={cfg.preset} onChange={(e) => update({ preset: e.target.value })}>
          {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
      </label>
      {cfg.preset === 'custom' && (
        <span className="ctl ctl-dates">
          <input type="date" value={cfg.start} onChange={(e) => update({ start: e.target.value })} aria-label="Start date" />
          <span aria-hidden="true">to</span>
          <input type="date" value={cfg.end} onChange={(e) => update({ end: e.target.value })} aria-label="End date" />
        </span>
      )}
      <label className="ctl">
        <span>Split into</span>
        <select value={cfg.breakdown} onChange={(e) => update({ breakdown: e.target.value as ReportConfig['breakdown'] })}>
          <option value="">No split (one total)</option>
          <option value="month">Months</option>
          <option value="quarter">Quarters</option>
          <option value="year">Years</option>
        </select>
      </label>
      {report === 'pl' && (
        <label className="ctl">
          <span>Compare with</span>
          <select value={cfg.compare} onChange={(e) => update({ compare: e.target.value as ReportConfig['compare'] })}>
            <option value="">Nothing</option>
            <option value="prev_period">Period before</option>
            <option value="prev_year">Same time last year</option>
          </select>
        </label>
      )}
      <div className="ctl ctl-cols">
        <span>Columns</span>
        <div className="col-chips">
          {chip(cfg.show.total, 'Total', () => update({ show: { ...cfg.show, total: !cfg.show.total } }), !cfg.breakdown)}
          {report === 'pl' && chip(cfg.show.pct, '% of income', () => update({ show: { ...cfg.show, pct: !cfg.show.pct } }))}
          {report === 'pl' && cfg.compare && chip(cfg.show.prev, 'Before', () => update({ show: { ...cfg.show, prev: !cfg.show.prev } }))}
          {report === 'pl' && cfg.compare && chip(cfg.show.change, 'Change', () => update({ show: { ...cfg.show, change: !cfg.show.change } }))}
        </div>
      </div>
    </section>
  )
}

function SavedViews({ report, views, setViews, cfg, apply }: {
  report: ReportKey; views: SavedView[]; setViews: (v: SavedView[]) => void; cfg: ReportConfig; apply: (c: ReportConfig) => void
}) {
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const mine = views.filter((v) => v.report === report)

  async function save() {
    if (!name.trim()) return setErr('Give this layout a name.')
    try {
      const v = await api.saveView(name, report as SavedView['report'], cfg)
      setViews([...views.filter((x) => x.id !== v.id), v])
      setNaming(false)
      setName('')
    } catch (e) {
      setErr((e as ApiError).message)
    }
  }

  return (
    <section className="saved-views" aria-label="Saved layouts">
      <Bookmark size={16} aria-hidden="true" className="muted" />
      {mine.length === 0 && !naming && <span className="muted small">Set it up the way you like, then save it.</span>}
      {mine.map((v) => (
        <span key={v.id} className="view-chip">
          <button onClick={() => apply(v.config)}>{v.name}</button>
          <button aria-label={`Delete layout ${v.name}`} className="view-x"
            onClick={() => api.deleteView(v.id).then(() => setViews(views.filter((x) => x.id !== v.id)))}>
            <X size={14} aria-hidden="true" />
          </button>
        </span>
      ))}
      {naming ? (
        <span className="view-name">
          <input autoFocus value={name} onChange={(e) => { setName(e.target.value); setErr('') }} placeholder="Name, e.g. Monthly P&L"
            onKeyDown={(e) => e.key === 'Enter' && save()} aria-label="Layout name" />
          <button className="btn btn-small btn-money" onClick={save}>Save</button>
          <button className="link-btn" onClick={() => { setNaming(false); setErr('') }}>Cancel</button>
          {err && <span className="error small">{err}</span>}
        </span>
      ) : (
        <button className="btn btn-small" onClick={() => setNaming(true)}><Save size={15} aria-hidden="true" /> Save this layout</button>
      )}
    </section>
  )
}

// ---------- shared table ----------

type Col = { label: string; get: (vals: number[], row?: ReportRow) => string; className?: string; idx?: number }

function useColumns(cfg: ReportConfig, columns: string[], hasPrev: boolean, incomeTotal?: number): Col[] {
  return useMemo(() => {
    const n = columns.length
    const totalIdx = n
    const prevIdx = n + 1
    const out: Col[] = columns.map((label, i) => ({ label, get: (v) => fmt(v[i]), idx: i }))
    if (!n || cfg.show.total) out.push({ label: n ? 'Total' : 'Amount', get: (v) => fmt(v[totalIdx]), className: 'col-total', idx: totalIdx })
    if (incomeTotal !== undefined && cfg.show.pct) {
      out.push({ label: '% of income', get: (v) => (incomeTotal ? `${((v[totalIdx] / incomeTotal) * 100).toFixed(1)}%` : '—'), className: 'col-soft' })
    }
    if (hasPrev && cfg.show.prev) out.push({ label: 'Before', get: (v) => fmt(v[prevIdx]), className: 'col-soft', idx: prevIdx })
    if (hasPrev && cfg.show.change) {
      out.push({
        label: 'Change',
        get: (v) => {
          const d = v[totalIdx] - v[prevIdx]
          const pct = v[prevIdx] ? ` (${d >= 0 ? '+' : ''}${Math.round((d / Math.abs(v[prevIdx])) * 100)}%)` : ''
          return `${d >= 0 ? '+' : '−'}${money(Math.abs(d))}${pct}`
        },
        className: 'col-soft',
      })
    }
    return out
  }, [cfg.show, columns, hasPrev, incomeTotal])
}

const fmt = (c: number | undefined) => (c === undefined ? '' : c === 0 ? '—' : c < 0 ? `−${money(-c)}` : money(c))

function ReportTable({ sections, cols, lines, expand, csvName, title, onDrill }: {
  sections: ReportSection[]; cols: Col[]; lines: { label: string; values: number[]; strong?: boolean }[]
  expand: boolean; csvName: string; title: string; onDrill?: (row: ReportRow, valueIndex: number) => void
}) {
  const [closed, setClosed] = useState<Set<string>>(new Set())
  useEffect(() => { setClosed(new Set()) }, [expand])

  const visible = (rows: ReportRow[]) => {
    const out: ReportRow[] = []
    let hideBelow: number | null = null
    for (const r of rows) {
      if (hideBelow !== null && r.depth > hideBelow) continue
      hideBelow = null
      out.push(r)
      const isClosed = expand ? closed.has(r.path) : !closed.has(r.path)
      if (r.parent && isClosed) hideBelow = r.depth
    }
    return out
  }
  const toggle = (path: string) => setClosed((s) => { const n = new Set(s); n.has(path) ? n.delete(path) : n.add(path); return n })

  function csv() {
    const esc = (s: string) => `"${s.replace(/"/g, '""')}"`
    const raw = (c: Col, v: number[], r?: ReportRow) => c.get(v, r).replace(/[−]/g, '-')
    const out = [[title, ...cols.map((c) => c.label)].map(esc).join(',')]
    for (const s of sections) {
      out.push(esc(s.title))
      for (const r of s.rows) out.push([esc(`${'  '.repeat(r.depth + 1)}${r.name}`), ...cols.map((c) => esc(raw(c, r.values, r)))].join(','))
      out.push([esc(`Total ${s.title}`), ...cols.map((c) => esc(raw(c, s.total)))].join(','))
    }
    for (const l of lines) out.push([esc(l.label), ...cols.map((c) => esc(raw(c, l.values)))].join(','))
    const blob = new Blob([out.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = csvName
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <section className="report-table-wrap">
      <div className="report-actions">
        <button className="btn btn-small" onClick={csv}><Download size={15} aria-hidden="true" /> Download for Excel</button>
        <button className="btn btn-small" onClick={() => window.print()}><Printer size={15} aria-hidden="true" /> Print or PDF</button>
      </div>
      <div className="report-scroll">
        <table className="report-table">
          <thead>
            <tr>
              <th scope="col" className="col-name"><span className="sr-only">Category</span></th>
              {cols.map((c) => <th key={c.label} scope="col" className={c.className}>{c.label}</th>)}
            </tr>
          </thead>
          {sections.map((s) => (
            <tbody key={s.key}>
              <tr className="sec-head"><th scope="rowgroup" colSpan={cols.length + 1}>{s.title}</th></tr>
              {visible(s.rows).map((r) => {
                const isClosed = expand ? closed.has(r.path) : !closed.has(r.path)
                return (
                  <tr key={r.path} className={r.parent ? 'is-parent' : ''}>
                    <th scope="row" className="col-name" style={{ paddingLeft: `${14 + r.depth * 20}px` }}>
                      {r.parent ? (
                        <button className="tree-btn" onClick={() => toggle(r.path)} aria-expanded={!isClosed}>
                          {isClosed ? <ChevronRight size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />} {r.name}
                        </button>
                      ) : r.name}
                    </th>
                    {cols.map((c) => {
                      const text = c.get(r.values, r)
                      const can = onDrill && c.idx !== undefined && text !== '—' && !r.path.startsWith('__')
                      return (
                        <td key={c.label} className={c.className}>
                          {can ? (
                            <button className="cell-btn" onClick={() => onDrill!(r, c.idx!)} aria-label={`See what's in ${r.name}, ${c.label}: ${text}`}>{text}</button>
                          ) : text}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
              <tr className="sec-total">
                <th scope="row" className="col-name">Total {s.title.toLowerCase()}</th>
                {cols.map((c) => <td key={c.label} className={c.className}>{c.get(s.total)}</td>)}
              </tr>
            </tbody>
          ))}
          <tbody>
            {lines.map((l) => (
              <tr key={l.label} className={l.strong ? 'grand-total' : 'sub-total'}>
                <th scope="row" className="col-name">{l.label}</th>
                {cols.map((c) => <td key={c.label} className={c.className}>{c.get(l.values)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ---------- charts ----------

const compact = (c: number) => {
  const d = Math.abs(c) / 100
  const s = d >= 1_000_000 ? `${(d / 1_000_000).toFixed(1)}M` : d >= 1000 ? `${Math.round(d / 1000)}K` : `${Math.round(d)}`
  return `${c < 0 ? '−' : ''}$${s}`
}

function niceMax(v: number) {
  if (v <= 0) return 100
  const mag = Math.pow(10, Math.floor(Math.log10(v)))
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= v) return m * mag
  return 10 * mag
}

/** Income vs expenses for each period: two series, one axis, legend + hover. */
function InOutBars({ labels, income, expenses, booked, names = ['Income', 'Expenses'], netName = 'Profit', title = 'Money in and out' }: {
  labels: string[]; income: number[]; expenses: number[]; booked?: number[]; names?: [string, string]; netName?: string; title?: string
}) {
  const short = labels.length > 6
  const [hover, setHover] = useState<number | null>(null)
  const bk = (i: number) => Math.max(booked?.[i] ?? 0, 0)
  const hasBooked = !!booked && booked.some((v) => v > 0)
  const max = niceMax(Math.max(...income.map((v, i) => Math.max(v, 0) + bk(i)), ...expenses, 0))
  const ticks = [0, max / 2, max]
  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="chart-title">{title}</span>
        <span className="legend">
          <span><i className="sw sw-in" aria-hidden="true" /> {hasBooked ? `${names[0]} (paid)` : names[0]}</span>
          {hasBooked && <span><i className="sw sw-booked" aria-hidden="true" /> Booked, coming</span>}
          <span><i className="sw sw-out" aria-hidden="true" /> {names[1]}</span>
        </span>
      </figcaption>
      <div className="plot" onMouseLeave={() => setHover(null)}>
        <div className="grid" aria-hidden="true">
          {ticks.slice().reverse().map((t) => <span key={t}><em>{compact(t)}</em></span>)}
        </div>
        <div className="groups">
          {labels.map((l, i) => {
            const net = income[i] - expenses[i]
            const inc = Math.max(income[i], 0)
            return (
              <div key={l} className={`group ${hover === i ? 'is-hover' : ''}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
                tabIndex={0} aria-label={`${l}: ${names[0]} ${money(income[i])}${bk(i) ? `, booked and coming ${money(bk(i))}` : ''}, ${names[1]} ${money(expenses[i])}, ${netName} ${fmt(net)}`}>
                <div className="bars">
                  <span className="bar-v bar-stack" style={{ height: `${((inc + bk(i)) / max) * 100}%` }}>
                    {bk(i) > 0 && <span className="seg bar-booked" style={{ flexGrow: bk(i) }} />}
                    {inc > 0 && <span className="seg bar-in" style={{ flexGrow: inc }} />}
                  </span>
                  <span className="bar-v bar-out" style={{ height: `${(Math.max(expenses[i], 0) / max) * 100}%` }} />
                </div>
                <span className="glabel">
                  <span className="gl-long">{l.replace(/ 20(\d\d)$/, " '$1")}</span>
                  <span className="gl-short">{short ? l.split(' ')[0].slice(0, 3) : l.replace(/ 20(\d\d)$/, " '$1")}</span>
                </span>
                {hover === i && (
                  <div className="tip" role="status">
                    <strong>{l}</strong>
                    <span><i className="sw sw-in" aria-hidden="true" /> {names[0]}{hasBooked ? ' (paid)' : ''} {money(income[i])}</span>
                    {bk(i) > 0 && <span><i className="sw sw-booked" aria-hidden="true" /> Booked, coming {money(bk(i))}</span>}
                    <span><i className="sw sw-out" aria-hidden="true" /> {names[1]} {money(expenses[i])}</span>
                    <span className="tip-net">{bk(i) > 0 ? `${netName} with booked ${money(net + bk(i))}` : `${netName} ${fmt(net)}`}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </figure>
  )
}

/** One series of horizontal bars with the value at the tip. */
function TopBars({ title, items, tone }: { title: string; items: { name: string; cents: number }[]; tone: 'in' | 'out' }) {
  const max = Math.max(...items.map((i) => i.cents), 1)
  return (
    <figure className="chart">
      <figcaption className="chart-head"><span className="chart-title">{title}</span></figcaption>
      <ul className="hbars">
        {items.map((it) => (
          <li key={it.name}>
            <span className="hb-name">{it.name}</span>
            <span className="hb-track"><span className={`hb-bar ${tone === 'in' ? 'bar-in' : 'bar-out'}`} style={{ width: `${(it.cents / max) * 100}%` }} /></span>
            <span className="hb-val">{money(it.cents)}</span>
          </li>
        ))}
      </ul>
    </figure>
  )
}

function Tiles({ items }: { items: { label: string; cents: number; tone?: 'in' | 'out' | 'net' | 'booked'; note?: string }[] }) {
  return (
    <div className="tiles">
      {items.map((t) => (
        <div key={t.label} className={`tile tile-${t.tone || 'plain'}`}>
          <span className="tile-label">
            {(t.tone === 'in' || t.tone === 'booked') && <ArrowDownLeft size={16} aria-hidden="true" />}
            {t.tone === 'out' && <ArrowUpRight size={16} aria-hidden="true" />}
            {t.tone === 'net' && <TrendingUp size={16} aria-hidden="true" />}
            {t.label}
          </span>
          <span className="tile-value">{fmt(t.cents)}</span>
          {t.note && <span className="tile-note">{t.note}</span>}
        </div>
      ))}
    </div>
  )
}

function useReport<T>(fetcher: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    let live = true
    setLoading(true)
    fetcher().then((d) => { if (live) { setData(d); setError('') } }).catch((e: ApiError) => live && setError(e.message)).finally(() => live && setLoading(false))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, loading }
}

// ---------- Profit & Loss ----------

function ProfitLoss({ cfg, update }: { cfg: ReportConfig; update: (p: Partial<ReportConfig>) => void }) {
  const [drill, setDrill] = useState<DrillTarget | null>(null)
  const ready = !!cfg.start && !!cfg.end
  const { data, error, loading } = useReport<PL | null>(() => (ready ? api.pl(cfg) : Promise.resolve(null)), [cfg.start, cfg.end, cfg.breakdown, cfg.compare])
  const n = data?.columns.length ?? 0
  const incomeTotal = data ? data.lines.total_income[n] : 0
  const cols = useColumns(cfg, data?.columns ?? [], !!data?.has_prev, incomeTotal)
  const bookings = useBookings()

  if (error) return <p className="error" role="alert">{error}</p>
  if (!data) return <p className="muted">{loading ? 'Adding things up…' : ''}</p>

  const sec = (k: string) => data.sections.find((s) => s.key === k)
  const expensesTotal = (sec('expense')?.total[n] ?? 0) + (sec('cogs')?.total[n] ?? 0) + (sec('other_expense')?.total[n] ?? 0)
  const incomeAll = incomeTotal + (sec('other_income')?.total[n] ?? 0)
  const net = data.lines.net_income[n]
  const perCol = (i: number) => ({
    inc: data.lines.total_income[i] + (sec('other_income')?.total[i] ?? 0),
    exp: (sec('expense')?.total[i] ?? 0) + (sec('cogs')?.total[i] ?? 0) + (sec('other_expense')?.total[i] ?? 0),
  })
  const topExpenses = (sec('expense')?.rows ?? []).filter((r) => r.depth === 0 && r.values[n] > 0)
    .sort((a, b) => b.values[n] - a.values[n]).slice(0, 7).map((r) => ({ name: r.name, cents: r.values[n] }))

  const booked = pad(bookedPer(bookings, data.ranges.slice(0, n), cfg.start, cfg.end), data.lines.net_income.length)
  const bookedTotal = booked[n]
  const lines = [
    ...(data.lines.gross_profit ? [{ label: 'Gross profit', values: data.lines.gross_profit }] : []),
    { label: 'Net operating income', values: data.lines.net_operating_income },
    { label: 'Net income (profit)', values: data.lines.net_income, strong: true },
    ...(bookedTotal > 0 ? [{ label: 'Booked income, not paid yet', values: booked }] : []),
  ]

  return (
    <div className={`report-body ${loading ? 'is-loading' : ''}`}>
      <p className="range-label">{data.range_label}{data.has_prev ? `, compared with ${data.prev_label}` : ''}</p>
      <Tiles items={[
        { label: 'Income', cents: incomeAll, tone: 'in' },
        { label: 'Expenses', cents: expensesTotal, tone: 'out' },
        { label: 'Profit', cents: net, tone: 'net', note: incomeAll ? `${Math.round((net / incomeAll) * 100)}% of income kept` : undefined },
        ...(bookedTotal > 0 ? [{ label: 'Booked, coming', cents: bookedTotal, tone: 'booked' as const, note: 'From Hospitable, not paid yet' }] : []),
      ]} />

      {(data.unsorted.out_cents > 0 || data.unsorted.in_cents > 0) && (
        <p className="report-warn">
          <CircleAlert size={18} aria-hidden="true" />
          <span>
            Not in this report yet: {money(data.unsorted.out_cents)} out and {money(data.unsorted.in_cents)} in that have no category
            (for example QuickBooks split payments). <Link to="/books">Sort them in Books</Link> so your profit is complete.
          </span>
        </p>
      )}

      {n > 1
        ? <InOutBars labels={data.columns} income={data.columns.map((_, i) => perCol(i).inc)} expenses={data.columns.map((_, i) => perCol(i).exp)} booked={booked.slice(0, n)} />
        : topExpenses.length > 0 && <TopBars title="Where the money went" items={topExpenses} tone="out" />}

      <div className="table-tools">
        <button className="link-btn" onClick={() => update({ expand: !cfg.expand })}>
          {cfg.expand ? 'Close all sub-categories' : 'Open all sub-categories'}
        </button>
      </div>
      <ReportTable sections={data.sections} cols={cols} lines={lines} expand={cfg.expand}
        csvName={`Profit and Loss ${cfg.start} to ${cfg.end}.csv`} title="Profit & Loss"
        onDrill={(r, i) => setDrill({ report: 'pl', path: r.path, title: r.name, start: data.ranges[i][0], end: data.ranges[i][1] })} />
      {drill && <DrillPanel {...drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

// ---------- Cash flow ----------

function CashFlowReport({ cfg }: { cfg: ReportConfig }) {
  const [drill, setDrill] = useState<DrillTarget | null>(null)
  const ready = !!cfg.start && !!cfg.end
  const { data, error, loading } = useReport<CashFlow | null>(() => (ready ? api.cashflow(cfg) : Promise.resolve(null)), [cfg.start, cfg.end, cfg.breakdown])
  const cols = useColumns({ ...cfg, show: { ...cfg.show, pct: false } }, data?.columns ?? [], false)
  const bookings = useBookings()
  if (error) return <p className="error" role="alert">{error}</p>
  if (!data) return <p className="muted">{loading ? 'Adding things up…' : ''}</p>
  const n = data.columns.length
  const all = data.sections.flatMap((s) => s.rows)
  const cashIn = all.reduce((a, r) => a + Math.max(r.values[n], 0), 0)
  const cashOut = all.reduce((a, r) => a + Math.max(-r.values[n], 0), 0)
  const booked = bookedPer(bookings, data.ranges.slice(0, n), cfg.start, cfg.end)

  return (
    <div className={`report-body ${loading ? 'is-loading' : ''}`}>
      <p className="range-label">{data.range_label}. Money that moved through your bank accounts. Card purchases count when you pay the card.</p>
      <Tiles items={[
        { label: 'Cash in', cents: cashIn, tone: 'in' },
        { label: 'Cash out', cents: cashOut, tone: 'out' },
        { label: 'Change in cash', cents: data.net_change[n], tone: 'net' },
        ...(booked[n] > 0 ? [{ label: 'Booked, coming', cents: booked[n], tone: 'booked' as const, note: 'From Hospitable, not paid yet' }] : []),
      ]} />
      {n > 1 && (
        <InOutBars labels={data.columns} names={['Cash in', 'Cash out']} netName="Change" title="Cash in and out"
          income={data.columns.map((_, i) => all.reduce((a, r) => a + Math.max(r.values[i], 0), 0))}
          expenses={data.columns.map((_, i) => all.reduce((a, r) => a + Math.max(-r.values[i], 0), 0))} booked={booked.slice(0, n)} />
      )}
      <ReportTable sections={data.sections} cols={cols} lines={[{ label: 'Change in cash', values: data.net_change, strong: true }]}
        expand={cfg.expand} csvName={`Cash flow ${cfg.start} to ${cfg.end}.csv`} title="Cash flow"
        onDrill={(r, i) => setDrill({ report: 'cashflow', path: r.path, title: r.name, start: data.ranges[i][0], end: data.ranges[i][1] })} />
      {drill && <DrillPanel {...drill} onClose={() => setDrill(null)} />}
      <p className="muted small">Bank accounts included: {data.bank_accounts.join(', ')}.</p>
    </div>
  )
}

// ---------- Coming income (from Hospitable bookings) ----------

function ComingIncome() {
  const [data, setData] = useState<Upcoming | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hover, setHover] = useState<number | null>(null)
  const [checking, setChecking] = useState<{ cents: number; name: string } | null>(null)
  useEffect(() => {
    api.books().then((s) => {
      const banks = s.banks.filter((b) => b.type !== 'credit' && b.balance_cents != null)
      if (banks.length) setChecking({ cents: banks.reduce((a, b) => a + (b.balance_cents ?? 0), 0), name: banks.map((b) => b.name).join(' + ') })
    }).catch(() => {})
  }, [])

  const load = useCallback((refresh = false) => {
    setBusy(true)
    api.upcoming(refresh).then((d) => { setData(d); setError('') }).catch((e: ApiError) => setError(e.message)).finally(() => setBusy(false))
  }, [])
  useEffect(() => { load(false) }, [load])

  if (error && !data) return <p className="error" role="alert">{error}</p>
  if (!data) return <p className="muted">{busy ? 'Getting your upcoming bookings from Hospitable…' : ''}</p>

  const max = niceMax(Math.max(...data.months.map((m) => m.payout_cents), 0))
  const peak = data.months.reduce((best, m, i) => (m.payout_cents > (data.months[best]?.payout_cents ?? -1) ? i : best), 0)
  const monthName = (k: string) => new Date(`${k}-15T12:00:00`).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })

  return (
    <div className="report-body">
      <div className="upcoming-head">
        <p className="range-label">Confirmed bookings from today on, by check-in month. Not in your books until the money arrives.</p>
        <button className="btn btn-small" onClick={() => load(true)} disabled={busy}>
          <RefreshCw size={15} aria-hidden="true" className={busy ? 'spin' : ''} /> {busy ? 'Updating…' : 'Update from Hospitable'}
        </button>
      </div>
      {data.error && <p className="error"><CircleAlert size={16} aria-hidden="true" /> {data.error}</p>}
      <Tiles items={[
        { label: 'Coming in', cents: data.total_cents, tone: 'in', note: `${data.bookings.length} bookings` },
        { label: 'Next 30 days', cents: data.bookings.filter((b) => (new Date(b.arrival).getTime() - Date.now()) / 864e5 <= 30).reduce((a, b) => a + (b.payout_cents || 0), 0), tone: 'in' },
      ]} />
      {data.missing > 0 && (
        <p className="report-warn"><CircleAlert size={18} aria-hidden="true" /><span>{data.missing} bookings came without an amount from Hospitable, so they aren't in the totals.</span></p>
      )}

      {data.months.length > 0 && (
        <figure className="chart">
          <figcaption className="chart-head"><span className="chart-title">Payouts by check-in month</span></figcaption>
          <div className="plot" onMouseLeave={() => setHover(null)}>
            <div className="grid" aria-hidden="true">
              {[max, max / 2, 0].map((t) => <span key={t}><em>{compact(t)}</em></span>)}
            </div>
            <div className="groups">
              {data.months.map((m, i) => (
                <div key={m.month} className={`group ${hover === i ? 'is-hover' : ''}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}
                  aria-label={`${monthName(m.month)}: ${money(m.payout_cents)} from ${m.count} bookings`}>
                  <div className="bars">
                    <span className="bar-v bar-in bar-solo" style={{ height: `${(m.payout_cents / max) * 100}%` }}>
                      {i === peak && <em className="cap-label">{compact(m.payout_cents)}</em>}
                    </span>
                  </div>
                  <span className="glabel">{monthName(m.month)}</span>
                  {hover === i && (
                    <div className="tip" role="status">
                      <strong>{monthName(m.month)}</strong>
                      <span>{money(m.payout_cents)}</span>
                      <span className="muted">{m.count} booking{m.count === 1 ? '' : 's'}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </figure>
      )}

      <ul className="booking-list">
        <li className="booking-head" aria-hidden="true">
          <span /><span />
          <span>Payout</span>
          <span>Running total</span>
        </li>
        {(() => {
          let running = 0
          return data.bookings.map((b, i) => {
            running += b.payout_cents || 0
            const month = b.arrival.slice(0, 7)
            const next = data.bookings[i + 1]
            const monthEnds = !next || next.arrival.slice(0, 7) !== month
            const endLabel = new Date(`${month}-15T12:00:00`).toLocaleDateString(undefined, { month: 'long' })
            return (
              <Fragment key={b.id}>
                <li>
                  <span className="txn-date">{shortDate(b.arrival)}</span>
                  <span className="txn-desc">
                    <strong>{b.guest_name}</strong>
                    <span className="muted small">{b.property_name}, {stayDates(b.arrival, b.departure)}, {platformName(b.platform)}</span>
                  </span>
                  <span className="amount amount-in">{b.payout_cents == null ? '—' : money(b.payout_cents)}</span>
                  <span className="amount running">{money(running)}</span>
                </li>
                {monthEnds && (
                  <li className="month-end">
                    <span className="month-end-text">
                      <strong>By the end of {endLabel}</strong>
                      {checking && <span className="muted small">{checking.name} today {money(checking.cents)} + coming {money(running)}</span>}
                    </span>
                    <span className="month-end-sum">
                      {checking ? <><small>You'd have</small> <strong>{money(checking.cents + running)}</strong></> : <><small>Coming</small> <strong>{money(running)}</strong></>}
                    </span>
                  </li>
                )}
              </Fragment>
            )
          })
        })()}
      </ul>
      {data.bookings.length === 0 && <p className="muted">No upcoming bookings found.</p>}
    </div>
  )
}


// ---------- What's behind a number ----------

type DrillTarget = { report: 'pl' | 'cashflow' | 'bs'; path: string; title: string; start: string; end: string }

function DrillPanel({ report, path, title, start, end, onClose }: DrillTarget & { onClose: () => void }) {
  const [data, setData] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.detail(report, path, start, end).then(setData).catch((e: ApiError) => setError(e.message))
  }, [report, path, start, end])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const when = start ? `${shortDate(start)}, ${start.slice(0, 4)} – ${shortDate(end)}, ${end.slice(0, 4)}` : `Everything up to ${shortDate(end)}, ${end.slice(0, 4)}`
  return (
    <div className="drill-backdrop" onClick={onClose}>
      <aside className="drill" role="dialog" aria-modal="true" aria-label={`What's in ${title}`} onClick={(e) => e.stopPropagation()}>
        <header className="drill-head">
          <div>
            <h2>{title}</h2>
            <p className="muted small">{when}</p>
          </div>
          <button className="link-btn" onClick={onClose} aria-label="Close"><X size={20} aria-hidden="true" /></button>
        </header>
        {error && <p className="error">{error}</p>}
        {data && (
          <>
            <div className="drill-total">
              <span>{data.count} transaction{data.count === 1 ? '' : 's'}</span>
              <strong>{fmt(data.total_cents)}</strong>
            </div>
            <ul className="drill-list">
              {data.items.map((it, i) => (
                <li key={`${it.id}-${i}`}>
                  <span className="txn-date">{shortDate(it.date)}<small>{it.date.slice(0, 4)}</small></span>
                  <span className="txn-desc">
                    <strong>{it.description}</strong>
                    <span className="muted small">{it.account}{it.source === 'quickbooks' || it.source === 'journal' ? ', from QuickBooks' : ''}</span>
                  </span>
                  <span className="amount">{fmt(it.cents)}</span>
                </li>
              ))}
            </ul>
            {data.count > data.items.length && <p className="muted small">Showing the newest {data.items.length}.</p>}
            {report !== 'bs' && (
              <Link className="btn btn-small" to="/books">Open Books to change categories</Link>
            )}
          </>
        )}
      </aside>
    </div>
  )
}

// ---------- Balance sheet ----------

const BS_PRESETS = [
  { key: 'today', label: 'Today' },
  { key: 'month_end', label: 'End of last month' },
  { key: 'quarter_end', label: 'End of last quarter' },
  { key: 'year_end', label: 'End of last year' },
  { key: 'custom', label: 'Pick a date' },
]

function bsDate(key: string): string | null {
  const t = new Date()
  switch (key) {
    case 'today': return iso(t)
    case 'month_end': return iso(new Date(t.getFullYear(), t.getMonth(), 0))
    case 'quarter_end': return iso(new Date(t.getFullYear(), Math.floor(t.getMonth() / 3) * 3, 0))
    case 'year_end': return iso(new Date(t.getFullYear() - 1, 11, 31))
    default: return null
  }
}

function BalanceSheetReport() {
  const [preset, setPreset] = useState('today')
  const [asOf, setAsOf] = useState(bsDate('today')!)
  const [compare, setCompare] = useState('')
  const [drill, setDrill] = useState<DrillTarget | null>(null)
  const { data, error, loading } = useReport<BalanceSheet>(() => api.balanceSheet(asOf, compare), [asOf, compare])

  const cols: Col[] = (data?.columns ?? []).map((label, i) => ({ label, get: (v) => fmt(v[i]), idx: i, className: i === 0 ? 'col-total' : 'col-soft' }))
  const by = (side: string) => (data?.sections ?? []).filter((s) => s.side === side)

  return (
    <>
      <section className="report-controls" aria-label="Balance sheet settings">
        <label className="ctl">
          <span>As of</span>
          <select value={preset} onChange={(e) => { setPreset(e.target.value); const d = bsDate(e.target.value); if (d) setAsOf(d) }}>
            {BS_PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        {preset === 'custom' && (
          <label className="ctl"><span>Date</span><input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></label>
        )}
        <label className="ctl">
          <span>Compare with</span>
          <select value={compare} onChange={(e) => setCompare(e.target.value)}>
            <option value="">Nothing</option>
            <option value="prev_period">End of the month before</option>
            <option value="prev_year">Same date last year</option>
          </select>
        </label>
      </section>
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <div className={`report-body ${loading ? 'is-loading' : ''}`}>
          <p className="range-label">What the business owns and owes on {data.columns[0]}.</p>
          <Tiles items={[
            { label: 'What you own', cents: data.totals.assets[0], tone: 'in' },
            { label: 'What you owe', cents: data.totals.liabilities[0], tone: 'out' },
            { label: "Owner's equity", cents: data.totals.equity[0], tone: 'net', note: 'Own minus owe' },
          ]} />
          <p className={data.balanced ? 'success balanced' : 'error'}>
            {data.balanced ? <CircleCheck size={18} aria-hidden="true" /> : <CircleAlert size={18} aria-hidden="true" />}
            {data.balanced ? 'Balanced: what you own equals what you owe plus your equity.' : "Doesn't balance yet. Some transactions may be missing a category."}
          </p>
          <OwnOwe own={data.totals.assets[0]} owe={data.totals.liabilities[0]} equity={data.totals.equity[0]} />
          <ReportTable
            sections={[...by('assets'), ...by('liabilities'), ...by('equity')]}
            cols={cols}
            lines={[
              { label: 'Total you own', values: data.totals.assets },
              { label: 'Total you owe', values: data.totals.liabilities },
              { label: 'Owe + equity', values: data.liabilities_and_equity, strong: true },
            ]}
            expand={true}
            csvName={`Balance sheet ${asOf}.csv`}
            title="Balance sheet"
            onDrill={(r, i) => setDrill({ report: 'bs', path: r.path, title: r.name, start: '', end: data.dates[i] })}
          />
          {drill && <DrillPanel {...drill} onClose={() => setDrill(null)} />}
        </div>
      )}
    </>
  )
}

/** Own vs owe + equity: two bars on one scale, the second split into owe and equity. */
function OwnOwe({ own, owe, equity }: { own: number; owe: number; equity: number }) {
  const max = Math.max(own, owe + Math.max(equity, 0), 1)
  const pct = (v: number) => `${(Math.max(v, 0) / max) * 100}%`
  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="chart-title">Own vs. owe</span>
        <span className="legend">
          <span><i className="sw sw-in" aria-hidden="true" /> Own</span>
          <span><i className="sw sw-out" aria-hidden="true" /> Owe</span>
          <span><i className="sw sw-eq" aria-hidden="true" /> Your equity</span>
        </span>
      </figcaption>
      <div className="ownowe">
        <span className="oo-label">Own</span>
        <span className="oo-track"><span className="oo-seg bar-in" style={{ width: pct(own) }} /></span>
        <span className="oo-val">{fmt(own)}</span>
        <span className="oo-label">Owe + equity</span>
        <span className="oo-track">
          <span className="oo-seg bar-out" style={{ width: pct(owe) }} />
          <span className="oo-seg bar-eq" style={{ width: pct(equity) }} />
        </span>
        <span className="oo-val">{fmt(owe + equity)}</span>
      </div>
    </figure>
  )
}

// ---------- Booked income (from Hospitable) on the P&L and cash flow ----------

/** Upcoming bookings, loaded once (Savannah keeps a 30-minute copy). Empty if Hospitable isn't connected. */
function useBookings(): Booking[] {
  const [rows, setRows] = useState<Booking[]>([])
  useEffect(() => { api.upcoming().then((u) => setRows(u.bookings)).catch(() => setRows([])) }, [])
  return rows
}

/** Booked payouts per column (by arrival date), plus the whole range at the end. Only today onward. */
function bookedPer(bookings: Booking[], ranges: [string, string][], start: string, end: string): number[] {
  const today = iso(new Date())
  const inRange = (d: string, a: string, b: string) => d >= a && d <= b
  const sum = (a: string, b: string) => bookings
    .filter((x) => x.payout_cents && x.arrival >= today && inRange(x.arrival, a, b))
    .reduce((t, x) => t + (x.payout_cents ?? 0), 0)
  return [...ranges.map(([a, b]) => sum(a, b)), sum(start, end)]
}

const pad = (v: number[], len: number) => [...v, ...Array(Math.max(len - v.length, 0)).fill(0)]
