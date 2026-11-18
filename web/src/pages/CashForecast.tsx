import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { CalendarCheck, CircleAlert, CreditCard, Home, RefreshCw, ShoppingBasket, Sparkles, TrendingDown, Wallet } from 'lucide-react'
import { api, ApiError, money, shortDate, type CardMode, type CostMode, type Forecast, type ForecastChoices, type ForecastEvent, type ForecastKind } from '../api'
import ConnectBank from '../components/ConnectBank'

// ---------- helpers ----------

const DAY = 864e5
const toDate = (iso: string) => new Date(iso + 'T12:00:00')
const isoOf = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const addDays = (iso: string, n: number) => isoOf(new Date(toDate(iso).getTime() + n * DAY))
const signed = (c: number) => `${c < 0 ? '−' : ''}${money(c)}`
const ordinal = (n: number) => `${n}${[11, 12, 13].includes(n % 100) ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'}`
const compact = (c: number) => {
  const d = Math.abs(c) / 100
  const s = d >= 1_000_000 ? `${(d / 1_000_000).toFixed(1)}M` : d >= 1000 ? `${(d / 1000).toFixed(d >= 10000 ? 0 : 1).replace(/\.0$/, '')}K` : `${Math.round(d)}`
  return `${c < 0 ? '−' : ''}$${s}`
}

const LAYERS: { key: ForecastKind; label: string; icon: typeof Wallet }[] = [
  { key: 'income', label: 'Payouts', icon: CalendarCheck },
  { key: 'card', label: 'Card bills', icon: CreditCard },
  { key: 'fixed', label: 'Mortgage', icon: Home },
  { key: 'cost', label: 'Other costs', icon: ShoppingBasket },
]

type Day = { date: string; cents: number; events: ForecastEvent[]; past: boolean }

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(720)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

// ---------- the report ----------

export default function CashForecast() {
  const [data, setData] = useState<Forecast | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [on, setOn] = useState<Record<ForecastKind, boolean>>({ income: true, card: true, fixed: true, cost: true })
  const [minText, setMinText] = useState('')
  const [minSaved, setMinSaved] = useState(false)

  const load = useCallback((refresh = false) => {
    setBusy(true)
    api.forecast(refresh)
      .then((d) => { setData(d); setError(''); setMinText(String(Math.round(d.min_cents / 100))) })
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setBusy(false))
  }, [])
  useEffect(() => { load(false) }, [load])

  const minCents = useMemo(() => {
    const n = Number(minText.replace(/[$,\s]/g, ''))
    return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : data?.min_cents ?? 0
  }, [minText, data])

  async function saveMin() {
    if (!data || minCents === data.min_cents) return
    try {
      await api.setForecastMin(minCents)
      setData({ ...data, min_cents: minCents })
      setMinSaved(true)
      setTimeout(() => setMinSaved(false), 1800)
    } catch (e) { setError((e as ApiError).message) }
  }

  async function choose(c: ForecastChoices) {
    try {
      await api.setForecastChoices(c)
      const d = await api.forecast(false)
      setData(d)
    } catch (e) { setError((e as ApiError).message) }
  }

  const days = useMemo<Day[]>(() => {
    if (!data) return []
    const byDay = new Map<string, ForecastEvent[]>()
    for (const e of data.events) if (on[e.kind]) byDay.set(e.date, [...(byDay.get(e.date) || []), e])
    const past: Day[] = data.history.filter((h) => h.date < data.today).map((h) => ({ date: h.date, cents: h.cents, events: [], past: true }))
    const out: Day[] = [...past, { date: data.today, cents: data.start_cents, events: [], past: false }]
    let bal = data.start_cents
    for (let i = 1; i <= data.weeks * 7; i++) {
      const d = addDays(data.today, i)
      const evs = byDay.get(d) || []
      bal += evs.reduce((a, e) => a + e.cents, 0)
      out.push({ date: d, cents: bal, events: evs, past: false })
    }
    return out
  }, [data, on])

  if (error && !data) return <p className="error" role="alert">{error}</p>
  if (!data) return <p className="muted">{busy ? 'Working out your cash forecast…' : ''}</p>
  if (!data.accounts.length) return <p className="muted">Connect your Chase checking account in Books to see a cash forecast.</p>

  const future = days.filter((d) => !d.past)
  const lowest = future.reduce((lo, d) => (d.cents < lo.cents ? d : lo), future[0])
  const last = future[future.length - 1]
  const firstBelow = future.find((d) => d.cents < minCents)
  const below = !!firstBelow

  return (
    <div className="report-body forecast">
      <div className="upcoming-head">
        <p className="range-label">
          {data.accounts.join(' + ')}, today through {shortDate(data.end)}. Dashed line = forecast.
        </p>
        <button className="btn btn-small" onClick={() => load(true)} disabled={busy}>
          <RefreshCw size={15} aria-hidden="true" className={busy ? 'spin' : ''} /> {busy ? 'Updating…' : 'Update bookings'}
        </button>
      </div>
      {data.bookings_error && <p className="error"><CircleAlert size={16} aria-hidden="true" /> {data.bookings_error}</p>}

      <div className="fc-controls">
        <div className="col-chips" role="group" aria-label="What to include">
          {LAYERS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={`col-chip fc-chip ${on[key] ? 'is-on' : ''}`} aria-pressed={on[key]} onClick={() => setOn({ ...on, [key]: !on[key] })}>
              <Icon size={15} aria-hidden="true" /> {label}
            </button>
          ))}
        </div>
        <label className="fc-min">
          <span>Warn me below</span>
          <span className="fc-min-input">
            <span aria-hidden="true">$</span>
            <input inputMode="numeric" value={minText} onChange={(e) => setMinText(e.target.value)} onBlur={saveMin}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} aria-label="Minimum balance in dollars" />
          </span>
          {minSaved && <span className="success small">Saved</span>}
        </label>
      </div>

      <div className="tiles">
        <div className="tile">
          <span className="tile-label"><Wallet size={16} aria-hidden="true" /> Today</span>
          <span className="tile-value">{signed(data.start_cents)}</span>
          <span className="tile-note">In checking now</span>
        </div>
        <div className={`tile ${lowest.cents < minCents ? 'tile-danger' : ''}`}>
          <span className="tile-label">
            {lowest.cents < minCents ? <CircleAlert size={16} aria-hidden="true" /> : <TrendingDown size={16} aria-hidden="true" />} Lowest point
          </span>
          <span className="tile-value">{signed(lowest.cents)}</span>
          <span className="tile-note">{shortDate(lowest.date)}{lowest.cents < minCents ? ' · below your minimum' : ''}</span>
        </div>
        <div className="tile">
          <span className="tile-label"><CalendarCheck size={16} aria-hidden="true" /> In {data.weeks} weeks</span>
          <span className="tile-value">{signed(last.cents)}</span>
          <span className="tile-note">{shortDate(last.date)}</span>
        </div>
      </div>

      {below && (
        <p className="fc-alert" role="status">
          <CircleAlert size={18} aria-hidden="true" />
          <span>Below {money(minCents)} from <strong>{shortDate(firstBelow!.date)}</strong>{firstBelow!.events.length ? ` (${firstBelow!.events.slice().sort((a, b) => a.cents - b.cents)[0].label})` : ''}.</span>
        </p>
      )}

      <BalanceLine days={days} minCents={minCents} today={data.today} lowest={lowest} />

      <DayTable days={future} />

      <Sources data={data} on={on} choose={choose} reload={() => load(true)} />
    </div>
  )
}

// ---------- the line chart ----------

function BalanceLine({ days, minCents, today, lowest }: { days: Day[]; minCents: number; today: string; lowest: Day }) {
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const H = width < 520 ? 220 : 270
  const m = { l: 52, r: 14, t: 18, b: 28 }
  const iw = width - m.l - m.r, ih = H - m.t - m.b
  const vals = days.map((d) => d.cents)
  let lo = Math.min(...vals, minCents, 0), hi = Math.max(...vals, minCents)
  const span = hi - lo || 100000
  const step = niceStep(span / 4)
  lo = Math.floor(lo / step) * step
  hi = Math.ceil((hi + span * 0.05) / step) * step
  const ticks: number[] = []
  for (let v = lo; v <= hi + 1; v += step) ticks.push(v)
  const n = days.length - 1
  const x = (i: number) => m.l + (i / n) * iw
  const y = (c: number) => m.t + (1 - (c - lo) / (hi - lo)) * ih
  const todayI = days.findIndex((d) => d.date === today)
  const lowI = days.indexOf(lowest)

  // Balances change once a day, so draw steps.
  const stepPath = (from: number, to: number) => {
    let p = `M${x(from)},${y(days[from].cents)}`
    for (let i = from + 1; i <= to; i++) p += `H${x(i)}V${y(days[i].cents)}`
    return p
  }
  const pastPath = todayI > 0 ? stepPath(0, todayI) : ''
  const futurePath = stepPath(Math.max(todayI, 0), n)
  const minY = y(minCents)
  const months = days.map((d, i) => ({ d, i })).filter(({ d, i }) => d.date.endsWith('-01') && i > 0 && i < n)

  function move(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * width
    setHover(Math.max(0, Math.min(n, Math.round(((px - m.l) / iw) * n))))
  }
  function key(e: React.KeyboardEvent) {
    if (e.key === 'ArrowRight') setHover((h) => Math.min(n, (h ?? todayI) + 1))
    else if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? todayI) - 1))
    else return
    e.preventDefault()
  }
  const hd = hover != null ? days[hover] : null
  const lowLabelLeft = x(lowI) > width - 150

  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="chart-title">Cash in checking</span>
        <span className="legend">
          <span><i className="ln ln-solid" aria-hidden="true" /> Actual</span>
          <span><i className="ln ln-dash" aria-hidden="true" /> Forecast</span>
          <span><i className="ln ln-min" aria-hidden="true" /> Your minimum</span>
        </span>
      </figcaption>
      <div ref={wrap} className="fc-plot">
        <svg width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" tabIndex={0}
          aria-label={`Checking balance from ${shortDate(days[0].date)} to ${shortDate(days[n].date)}. Lowest ${signed(lowest.cents)} on ${shortDate(lowest.date)}. Use the arrow keys to read each day.`}
          onPointerMove={move} onPointerLeave={() => setHover(null)} onKeyDown={key} onBlur={() => setHover(null)}>
          <defs>
            <clipPath id="fc-below"><rect x={0} y={minY} width={width} height={Math.max(H - minY, 0)} /></clipPath>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={width - m.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'fc-zero' : 'fc-grid'} />
              <text x={m.l - 8} y={y(t) + 4} className="fc-axis" textAnchor="end">{compact(t)}</text>
            </g>
          ))}
          {minY < m.t + ih && <rect x={m.l} y={minY} width={iw} height={m.t + ih - minY} className="fc-below-band" />}
          {days.map((d, i) => (toDate(d.date).getDay() === 1 && !months.some((mm) => Math.abs(mm.i - i) <= 3) ? (
            <g key={`w${d.date}`}>
              <line x1={x(i)} x2={x(i)} y1={m.t} y2={m.t + ih} className="fc-vgrid" />
              {width >= 640 && <text x={x(i)} y={H - 8} className="fc-axis fc-axis-day" textAnchor="middle">{toDate(d.date).getDate()}</text>}
            </g>
          ) : null))}
          {months.map(({ d, i }) => (
            <g key={d.date}>
              <line x1={x(i)} x2={x(i)} y1={m.t} y2={m.t + ih + 5} className="fc-vgrid fc-vgrid-month" />
              <text x={x(i)} y={H - 8} className="fc-axis" textAnchor="middle">{toDate(d.date).toLocaleDateString(undefined, { month: 'short' })}</text>
            </g>
          ))}
          {todayI >= 0 && (
            <g>
              <line x1={x(todayI)} x2={x(todayI)} y1={m.t - 6} y2={m.t + ih} className="fc-today" />
              <text x={x(todayI) + 5} y={m.t + 4} className="fc-axis fc-today-label">Today</text>
            </g>
          )}
          <line x1={m.l} x2={width - m.r} y1={minY} y2={minY} className="fc-minline" />
          {pastPath && <path d={pastPath} className="fc-line" />}
          <path d={futurePath} className="fc-line fc-future" />
          <path d={futurePath} className="fc-line fc-future fc-danger" clipPath="url(#fc-below)" />
          {lowI >= 0 && (
            <g>
              <circle cx={x(lowI)} cy={y(lowest.cents)} r={5} className={`fc-dot ${lowest.cents < minCents ? 'is-danger' : ''}`} />
              <text x={x(lowI) + (lowLabelLeft ? -9 : 9)} y={y(lowest.cents) + (y(lowest.cents) > H - 50 ? -10 : 16)} textAnchor={lowLabelLeft ? 'end' : 'start'} className="fc-label">
                Lowest {compact(lowest.cents)} · {shortDate(lowest.date)}
              </text>
            </g>
          )}
          {hd && hover != null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + ih} className="fc-cross" />
              <circle cx={x(hover)} cy={y(hd.cents)} r={4.5} className={`fc-dot ${hd.cents < minCents && !hd.past ? 'is-danger' : ''}`} />
            </g>
          )}
        </svg>
        {hd && hover != null && (
          <div className="tip fc-tip" role="status" style={{ left: Math.min(Math.max(x(hover), 110), width - 110), top: 6 }}>
            <strong>{toDate(hd.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}{hd.past ? ' · actual' : ''}</strong>
            <span>Balance {signed(hd.cents)}</span>
            {hd.events.slice(0, 4).map((e, i) => (
              <span key={i} className="muted">{e.cents > 0 ? '+' : '−'}{money(e.cents)} {e.label.length > 30 ? e.label.slice(0, 29) + '…' : e.label}</span>
            ))}
            {hd.events.length > 4 && <span className="muted">+ {hd.events.length - 4} more</span>}
          </div>
        )}
      </div>
    </figure>
  )
}

function niceStep(v: number) {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1))))
  for (const s of [1, 2, 2.5, 5, 10]) if (s * mag >= v) return s * mag
  return 10 * mag
}

// ---------- week by week: every income and expense as a row ----------

const rowName = (e: ForecastEvent) => {
  if (e.kind === 'income') return 'Payouts'
  if (e.kind === 'cost' && e.label.startsWith('Cleaning · ')) return 'Cleaning'
  if (e.kind === 'card') return e.label.split(' · ')[0]
  return e.label
}
const whole = (c: number) => `${c < 0 ? '−' : ''}$${Math.round(Math.abs(c) / 100).toLocaleString()}`

function DayTable({ days }: { days: Day[] }) {
  const scroller = useRef<HTMLDivElement>(null)
  const cols = days.slice(1) // tomorrow onward (today's balance is the starting point)

  // Who pushed the balance below $0: the biggest payment on each day it crossed.
  const culprits: { col: number; row: string; date: string; cents: number; balance: number }[] = []
  cols.forEach((d, i) => {
    const before = days[i].cents
    if (before >= 0 && d.cents < 0) {
      const worst = d.events.filter((e) => e.cents < 0).sort((a, b) => a.cents - b.cents)[0]
      if (worst) culprits.push({ col: i, row: rowName(worst), date: d.date, cents: worst.cents, balance: d.cents })
    }
  })
  const isCulprit = (row: string, i: number) => culprits.some((c) => c.row === row && c.col === i)

  const rows = new Map<string, { name: string; vals: number[] }>()
  cols.forEach((d, i) => d.events.forEach((e) => {
    const name = rowName(e)
    const r = rows.get(name) || { name, vals: cols.map(() => 0) }
    r.vals[i] += e.cents
    rows.set(name, r)
  }))
  const sum = (v: number[]) => v.reduce((a, b) => a + b, 0)
  const income = [...rows.values()].filter((r) => sum(r.vals) > 0)
  const costs = [...rows.values()].filter((r) => sum(r.vals) <= 0).sort((a, b) => sum(a.vals) - sum(b.vals))
  const net = cols.map((_, i) => [...rows.values()].reduce((a, r) => a + r.vals[i], 0))

  // Month header: one cell spanning each month's days.
  const months: { label: string; span: number }[] = []
  cols.forEach((d) => {
    const label = toDate(d.date).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    if (months.length && months[months.length - 1].label === label) months[months.length - 1].span++
    else months.push({ label, span: 1 })
  })
  const dayClass = (d: Day, extra = '') => {
    const t = toDate(d.date)
    return [extra, t.getDate() === 1 ? 'fc-month-start' : '', t.getDay() === 0 || t.getDay() === 6 ? 'fc-weekend' : ''].filter(Boolean).join(' ')
  }
  const cell = (v: number) => (v ? whole(v) : '')

  function jump(i: number) {
    const el = scroller.current?.querySelector<HTMLElement>(`[data-col="${i}"]`)
    const sc = scroller.current
    if (el && sc) sc.scrollTo({ left: Math.max(el.offsetLeft - 260, 0), behavior: 'smooth' })
  }

  return (
    <section className="fc-table-wrap" aria-label="Day by day">
      {culprits.length > 0 && (
        <ul className="fc-culprits">
          {culprits.slice(0, 4).map((c) => (
            <li key={c.date}>
              <CircleAlert size={16} aria-hidden="true" />
              <span><strong>{shortDate(c.date)}: {c.row}</strong> ({whole(c.cents)}) takes you below $0, to {whole(c.balance)}.</span>
              <button className="btn btn-small fc-jump" onClick={() => jump(c.col)}>Show</button>
            </li>
          ))}
        </ul>
      )}
      <div className="report-scroll" ref={scroller}>
        <table className="report-table fc-table">
          <thead>
            <tr className="fc-months">
              <th className="col-name" rowSpan={2}>Day</th>
              {months.map((m) => <th key={m.label} colSpan={m.span} scope="colgroup">{m.label}</th>)}
              <th rowSpan={2} className="col-total fc-total-col">Total</th>
            </tr>
            <tr className="fc-days">
              {cols.map((d, i) => (
                <th key={d.date} scope="col" data-col={i} className={dayClass(d)}>
                  <small>{toDate(d.date).toLocaleDateString(undefined, { weekday: 'short' })}</small>
                  {i === 0 || toDate(d.date).getDate() === 1 ? shortDate(d.date) : toDate(d.date).getDate()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="sec-head"><th className="col-name" scope="rowgroup">Money in</th><td colSpan={cols.length + 1} /></tr>
            {income.map((r) => (
              <tr key={r.name}>
                <th className="col-name" scope="row">{r.name}</th>
                {r.vals.map((v, i) => <td key={i} className={dayClass(cols[i], 'fc-in')}>{cell(v)}</td>)}
                <td className="col-total fc-in fc-total-col">{whole(sum(r.vals))}</td>
              </tr>
            ))}
            {!income.length && <tr><th className="col-name muted" scope="row">Nothing coming in</th><td colSpan={cols.length + 1} /></tr>}
            <tr className="sec-head"><th className="col-name" scope="rowgroup">Money out</th><td colSpan={cols.length + 1} /></tr>
            {costs.map((r) => (
              <tr key={r.name}>
                <th className="col-name" scope="row">{r.name}</th>
                {r.vals.map((v, i) => (
                  <td key={i} className={dayClass(cols[i], isCulprit(r.name, i) ? 'fc-culprit' : '')}>
                    {isCulprit(r.name, i) && <CircleAlert size={13} aria-label="Takes you below $0" />} {cell(v)}
                  </td>
                ))}
                <td className="col-total fc-total-col">{whole(sum(r.vals))}</td>
              </tr>
            ))}
            <tr className="sec-total">
              <th className="col-name" scope="row">Net for the day</th>
              {net.map((v, i) => <td key={i} className={dayClass(cols[i], v > 0 ? 'fc-in' : '')}>{v ? whole(v) : ''}</td>)}
              <td className="col-total fc-total-col">{whole(sum(net))}</td>
            </tr>
            <tr className="grand-total fc-balance-row">
              <th className="col-name" scope="row">Balance at day end</th>
              {cols.map((d, i) => <td key={i} className={dayClass(d, d.cents < 0 ? 'fc-below' : '')}>{whole(d.cents)}</td>)}
              <td className="col-total fc-total-col" />
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted small">Scroll sideways to move through the days. Red balance = below $0. Weekends are shaded.</p>
    </section>
  )
}

// ---------- what the forecast is made of ----------

const CARD_MODES: { key: CardMode; label: string }[] = [
  { key: 'statement', label: 'Statement balance' },
  { key: 'minimum', label: 'Minimum payment' },
  { key: 'average', label: 'Average of last 3 payments' },
]
const COST_MODES: { key: CostMode; label: string }[] = [
  { key: 'last_year', label: 'Same weeks last year' },
  { key: 'recent', label: 'Last 3 months' },
  { key: 'off', label: 'Leave out' },
]

function Sources({ data, on, choose, reload }: { data: Forecast; on: Record<ForecastKind, boolean>; choose: (c: ForecastChoices) => void; reload: () => void }) {
  const s = data.sources
  const [a, b] = data.last_year_range
  const cleaningTotal = s.cleaning.reduce((t, h) => t + h.total_cents, 0)
  const costTotal = s.costs.reduce((t, c) => t + (c.mode === 'off' ? 0 : c.cents), 0)
  const yr = (iso: string) => toDate(iso).getFullYear()
  return (
    <section className="fc-sources" aria-label="What's in the forecast">
      <div className={`fc-card ${on.income ? '' : 'is-off'}`}>
        <h3><CalendarCheck size={17} aria-hidden="true" /> Payouts</h3>
        <p className="fc-big amount-in">+{money(s.income.cents)}</p>
        <p className="muted small">
          {data.hospitable_connected ? `${s.income.count} confirmed bookings, paid the day after check-in.` : 'Connect Hospitable in Settings to add payouts.'} Only bookings you already have.
        </p>
      </div>

      <div className={`fc-card ${on.fixed ? '' : 'is-off'}`}>
        <h3><Home size={17} aria-hidden="true" /> Mortgage</h3>
        {s.fixed.map((f) => (
          <div key={f.label} className="fc-item">
            <span><strong>{money(f.cents)}</strong> on the {ordinal(f.day)}</span>
            <span className="muted small">Same as your latest payment.</span>
          </div>
        ))}
        {!s.fixed.length && <p className="muted small">No loan payments found.</p>}
      </div>

      <div className={`fc-card fc-card-wide ${on.card ? '' : 'is-off'}`}>
        <h3><CreditCard size={17} aria-hidden="true" /> Card bills</h3>
        {s.cards.map((c) => (
          <div key={c.id} className="fc-item fc-card-row">
            <div className="fc-row-top">
              <span className="fc-item-name">{c.name}</span>
              <label className="fc-pick">
                <span className="sr-only">How to forecast {c.name}</span>
                <select value={c.mode} onChange={(e) => choose({ cards: { [c.id]: e.target.value as CardMode } })}>
                  {CARD_MODES.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                </select>
              </label>
            </div>
            <ul className="fc-schedule">
              {c.schedule.map((p) => (
                <li key={p.date}><span>{shortDate(p.date)}</span><strong>−{money(p.cents)}</strong><span className="muted small">{p.why}</span></li>
              ))}
              {!c.schedule.length && <li className="muted small">Nothing due in these 13 weeks.</li>}
            </ul>
            <span className="muted small">
              {c.balance_cents != null && <>Balance {money(c.balance_cents)}. </>}
              {c.bill?.statement_cents != null && <>From the bank: statement {money(c.bill.statement_cents)}, minimum {money(c.bill.minimum_cents ?? 0)}{c.bill.due_date ? `, due ${shortDate(c.bill.due_date)}` : ''}. </>}
              {c.last_payments.length > 0 && <>Your last payments: {c.last_payments.map((p) => compact(p.cents)).join(', ')}.</>}
            </span>
            {c.mode !== 'average' && !c.bill && (
              <div className="fc-permission">
                <CircleAlert size={16} aria-hidden="true" />
                <span>{c.bill_problem?.message || "The bank hasn't shared this card's bill yet, so the average is used for now."}</span>
                {(!c.bill_problem || c.bill_problem.kind === 'permission') && (
                  <ConnectBank small itemId={c.item_id} addProducts={['liabilities']} label="Allow card bills" onDone={reload} />
                )}
              </div>
            )}
          </div>
        ))}
        {!s.cards.length && <p className="muted small">No credit cards connected.</p>}
      </div>

      <div className={`fc-card fc-card-wide ${on.cost ? '' : 'is-off'}`}>
        <h3><Sparkles size={17} aria-hidden="true" /> Cleaning <span className="fc-total">−{money(cleaningTotal)}</span></h3>
        <p className="muted small">Your price per checkout, on the checkout day.</p>
        {s.cleaning.map((h) => <CleaningRow key={h.property} house={h} choose={choose} />)}
        {!s.cleaning.length && <p className="muted small">No houses yet. Connect Hospitable to see your bookings.</p>}
      </div>

      <div className={`fc-card fc-card-wide ${on.cost ? '' : 'is-off'}`}>
        <h3><ShoppingBasket size={17} aria-hidden="true" /> Other costs from checking <span className="fc-total">−{money(costTotal)}</span></h3>
        <p className="muted small">"Same weeks last year" means {shortDate(a)} – {shortDate(b)}, {yr(a)}{yr(b) !== yr(a) ? `–${String(yr(b)).slice(2)}` : ''}.</p>
        <ul className="fc-costs">
          {s.costs.map((c) => (
            <li key={c.id} className={c.mode === 'off' ? 'is-off' : ''}>
              <span className="hb-name">{c.name}{c.new && <span className="tag-ask fc-tag">new</span>}</span>
              <label className="fc-pick">
                <span className="sr-only">How to forecast {c.name}</span>
                <select value={c.mode} onChange={(e) => choose({ categories: { [String(c.id)]: e.target.value as CostMode } })}>
                  {COST_MODES.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                </select>
              </label>
              <span className="hb-val">{c.mode === 'off' ? '—' : money(c.cents)}</span>
            </li>
          ))}
        </ul>
        {s.moved_to_card.length > 0 && (
          <p className="muted small">Now paid by card, so they're inside the card bills: {s.moved_to_card.join(', ')}.</p>
        )}
        <p className="muted small">Left out: owner money, transfers and equipment purchases.</p>
      </div>
    </section>
  )
}

function CleaningRow({ house, choose }: { house: Forecast['sources']['cleaning'][number]; choose: (c: ForecastChoices) => void }) {
  const [text, setText] = useState(house.cents != null ? String(house.cents / 100) : '')
  useEffect(() => { setText(house.cents != null ? String(house.cents / 100) : '') }, [house.cents])
  function save() {
    const v = text.trim() === '' ? null : Math.round(Number(text.replace(/[$,\s]/g, '')) * 100)
    if (v !== null && (!Number.isFinite(v) || v < 0)) return
    if (v !== house.cents) choose({ cleaning: { [house.property]: v } })
  }
  return (
    <div className="fc-clean">
      <span className="fc-item-name">{house.property.split('|')[0].trim()}</span>
      <span className="fc-min-input">
        <span aria-hidden="true">$</span>
        <input inputMode="decimal" value={text} placeholder="0" onChange={(e) => setText(e.target.value)} onBlur={save}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} aria-label={`Cleaning cost per checkout at ${house.property}`} />
      </span>
      <span className="muted small">× {house.count} checkout{house.count === 1 ? '' : 's'}</span>
      <strong className="hb-val">{house.cents == null ? '—' : `−${money(house.total_cents)}`}</strong>
    </div>
  )
}
