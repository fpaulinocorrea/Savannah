import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Archive, ArchiveRestore, ArrowLeft, Check, CheckCheck, CircleAlert, MessageCircle, RefreshCw, Search, Send, Sparkles, Undo2 } from 'lucide-react'
import {
  api, ApiError, messageTime, platformName, stayDates, timeAgo, whenShort,
  type ConvoAction, type Conversation, type GuestsInfo, type InboxRow,
} from '../api'

// The Guests inbox: every conversation, newest first. On a computer the list and the
// open conversation sit side by side; on a phone you see one, then the other.
export default function Guests() {
  const { id } = useParams()
  const [info, setInfo] = useState<GuestsInfo | null>(null)
  const [error, setError] = useState('')
  const [bump, setBump] = useState(0)  // changes whenever the list should refresh now
  const refreshList = useCallback(() => setBump((n) => n + 1), [])
  const [listActs, setListActs] = useState(0)  // archive / replied from the list: the open conversation re-reads

  const loadInfo = useCallback(() => {
    api.guests().then((g) => { setInfo(g); setError('') }).catch((e: ApiError) => setError(e.message))
  }, [])

  const busy = !!info && (info.checking || info.import.running)
  useEffect(() => {
    loadInfo()
    const t = setInterval(loadInfo, busy ? 3000 : 20000)
    return () => clearInterval(t)
  }, [loadInfo, busy])

  if (error && !info) return <p className="error" role="alert">{error}</p>
  if (!info) return null
  const ready = info.hospitable_connected && info.claude_connected

  return (
    <div className={`guests ${id ? 'has-open' : ''}`}>
      <header className="guests-head">
        <h1 className="display">Guests</h1>
        <span className="mode-pill">Suggest mode: you approve every reply</span>
      </header>

      {!ready && <SetupSteps info={info} />}
      {info.hospitable_connected && <StatusStrip info={info} onChange={() => { loadInfo(); refreshList() }} />}

      {info.hospitable_connected && (
        <div className="inbox-layout">
          <InboxList openId={id} bump={bump} onChanged={() => { loadInfo(); setListActs((n) => n + 1) }} />
          <div className="convo-pane">
            {id ? <ConversationView key={id} id={id} claudeReady={info.claude_connected} onChanged={refreshList} listActs={listActs} /> : <PickOne />}
          </div>
        </div>
      )}
    </div>
  )
}

function PickOne() {
  return (
    <div className="pick-one">
      <MessageCircle size={36} strokeWidth={1.5} aria-hidden="true" />
      <p>Pick a conversation to read it and reply.</p>
    </div>
  )
}

// ---------- the list ----------

function InboxList({ openId, bump, onChanged }: { openId?: string; bump: number; onChanged: () => void }) {
  const [view, setView] = useState<'inbox' | 'archived'>('inbox')
  const [q, setQ] = useState('')
  const [data, setData] = useState<{ total: number; waiting: number; archived: number; items: InboxRow[] } | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const load = useCallback(() => {
    api.inbox(view, q).then(setData).catch(() => {})
  }, [view, q])

  useEffect(() => {
    const first = setTimeout(load, q ? 250 : 0)
    const t = setInterval(load, 15000)
    return () => { clearTimeout(first); clearInterval(t) }
  }, [load, q, bump])
  useEffect(() => { setPicked(new Set()) }, [view])

  async function act(ids: string[], action: ConvoAction) {
    if (!ids.length) return
    setBusy(true)
    try {
      const r = await api.convoState(ids, action)
      const what = { archive: 'archived', unarchive: 'moved to the inbox', replied: 'marked as replied', unreplied: 'marked as needing a reply' }[action]
      setNote(`${r.changed} conversation${r.changed === 1 ? '' : 's'} ${what}.`)
      setTimeout(() => setNote(''), 4000)
      setPicked(new Set())
      load()
      onChanged()
    } catch { setNote('That didn\'t work. Try again.') }
    setBusy(false)
  }

  const items = data?.items ?? []
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const allPicked = items.length > 0 && items.every((c) => picked.has(c.reservation_id))
  const pickedNeeding = items.filter((c) => picked.has(c.reservation_id) && c.needs_reply).length

  return (
    <section className="inbox-list" aria-label="Conversations">
      <div className="inbox-tools">
        <div className="tabs tabs-small" role="tablist">
          <button role="tab" aria-selected={view === 'inbox'} className={view === 'inbox' ? 'is-on' : ''} onClick={() => setView('inbox')}>
            Inbox {data && data.waiting > 0 && <span className="count" title={`${data.waiting} need a reply`}>{data.waiting}</span>}
          </button>
          <button role="tab" aria-selected={view === 'archived'} className={view === 'archived' ? 'is-on' : ''} onClick={() => setView('archived')}>
            <Archive size={15} aria-hidden="true" /> Archived {data && data.archived > 0 && <span className="count count-soft">{data.archived}</span>}
          </button>
        </div>
        <label className="search search-small">
          <Search size={16} aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Guest or home" aria-label="Search guest or home" />
        </label>
        {items.length > 0 && (
          <div className={`bulk-bar ${picked.size ? 'is-on' : ''}`}>
            <label className="bulk-all">
              <input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(items.map((c) => c.reservation_id)))} />
              {picked.size ? `${picked.size} selected` : 'Select all'}
            </label>
            {picked.size > 0 && (
              <span className="bulk-actions">
                {view === 'inbox' && pickedNeeding > 0 && (
                  <button className="btn btn-small" disabled={busy} onClick={() => act([...picked], 'replied')}>
                    <CheckCheck size={15} aria-hidden="true" /> Mark replied
                  </button>
                )}
                {view === 'inbox'
                  ? <button className="btn btn-small" disabled={busy} onClick={() => act([...picked], 'archive')}><Archive size={15} aria-hidden="true" /> Archive</button>
                  : <button className="btn btn-small" disabled={busy} onClick={() => act([...picked], 'unarchive')}><ArchiveRestore size={15} aria-hidden="true" /> Move to inbox</button>}
                <button className="link-btn" onClick={() => setPicked(new Set())}>Clear</button>
              </span>
            )}
          </div>
        )}
        {note && <p className="success small" role="status"><Check size={15} aria-hidden="true" /> {note}</p>}
      </div>

      {data && items.length === 0 && (
        <div className="all-clear small-clear">
          <span className="all-clear-icon"><Check size={28} strokeWidth={2} aria-hidden="true" /></span>
          <p className="muted">{q ? 'No matches.' : view === 'archived' ? 'Nothing archived yet.' : 'Inbox empty.'}</p>
        </div>
      )}

      <ul className="convo-list">
        {items.map((c) => (
          <li key={c.reservation_id} className={`convo-li ${picked.has(c.reservation_id) ? 'is-picked' : ''}`}>
            <input type="checkbox" className="convo-pick" checked={picked.has(c.reservation_id)} onChange={() => toggle(c.reservation_id)}
              aria-label={`Select ${c.guest_name}`} />
            <Link to={`/guests/${c.reservation_id}`} className={`convo-row ${openId === c.reservation_id ? 'is-open' : ''} ${c.needs_reply ? 'is-waiting' : ''}`}>
              <Avatar name={c.guest_name} photo={c.photo} />
              <span className="convo-main">
                <span className="convo-top">
                  <strong>{c.guest_name}</strong>
                  <span className="convo-time">{whenShort(c.last_at)}</span>
                </span>
                <span className="convo-home">{c.kind === 'inquiry' && <span className="tag-ask">Asking</span>}{c.property_name}{c.arrival ? `, ${stayDates(c.arrival, c.departure)}` : ''}</span>
                <span className="convo-last">{c.last_role === 'host' ? 'You: ' : ''}{c.last_body}</span>
                {(c.needs_reply || c.draft_status === 'ready') && (
                  <span className="convo-tags">
                    {c.needs_reply && <span className="tag-wait">Needs reply</span>}
                    {c.draft_status === 'ready' && <span className="tag-ready"><Sparkles size={12} aria-hidden="true" /> Reply ready</span>}
                  </span>
                )}
              </span>
            </Link>
            <span className="convo-acts">
              {c.needs_reply && (
                <button className="icon-act" disabled={busy} onClick={() => act([c.reservation_id], 'replied')} title="Mark as already replied" aria-label={`Mark ${c.guest_name} as already replied`}>
                  <CheckCheck size={17} aria-hidden="true" />
                </button>
              )}
              {view === 'inbox'
                ? <button className="icon-act" disabled={busy} onClick={() => act([c.reservation_id], 'archive')} title="Archive" aria-label={`Archive ${c.guest_name}`}><Archive size={17} aria-hidden="true" /></button>
                : <button className="icon-act" disabled={busy} onClick={() => act([c.reservation_id], 'unarchive')} title="Move to inbox" aria-label={`Move ${c.guest_name} to inbox`}><ArchiveRestore size={17} aria-hidden="true" /></button>}
            </span>
          </li>
        ))}
      </ul>
      {data && data.total > data.items.length && (
        <p className="muted small">Showing the newest {data.items.length} of {data.total}. Search to find older ones.</p>
      )}
    </section>
  )
}

// ---------- one conversation ----------

function ConversationView({ id, claudeReady, onChanged, listActs }: { id: string; claudeReady: boolean; onChanged: () => void; listActs: number }) {
  const navigate = useNavigate()
  const [c, setC] = useState<Conversation | null>(null)
  const [error, setError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)

  const load = useCallback((fresh = false) => {
    api.conversation(id, fresh).then((x) => { setC(x); setError('') }).catch((e: ApiError) => setError(e.message))
  }, [id])

  // Opening: fetch the latest from Hospitable, then refresh the list in case something changed.
  useEffect(() => {
    api.conversation(id, true).then((x) => { setC(x); setError(''); onChanged() }).catch((e: ApiError) => setError(e.message))
  }, [id, onChanged])

  useEffect(() => { if (listActs) load(false) }, [listActs, load])

  const drafting = c?.draft?.status === 'drafting'
  useEffect(() => {
    const t = setInterval(() => load(false), drafting ? 2500 : 20000)
    return () => clearInterval(t)
  }, [load, drafting])

  async function act(action: ConvoAction) {
    try {
      await api.convoState([id], action)
      load(false)
      onChanged()
    } catch { /* the list shows the real state on its next refresh */ }
  }

  const count = c?.messages.length ?? 0
  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }) }, [count])

  if (error && !c) return <p className="error" role="alert">{error}</p>
  if (!c) return <p className="muted convo-loading">Opening…</p>
  const r = c.reservation

  return (
    <article className="convo">
      <div className="convo-top-bar">
      <header className="convo-head">
        <button className="link-btn convo-back" onClick={() => navigate('/guests')} aria-label="Back to inbox">
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <Avatar name={r.guest_name} photo={r.photo} />
        <div className="draft-who">
          <strong>{r.guest_name}</strong>
          <span className="muted small">{r.kind === 'inquiry' && <span className="tag-ask">Asking, not booked yet</span>}{r.property_name}{r.arrival ? `, ${stayDates(r.arrival, r.departure)}` : ''}</span>
        </div>
        <span className="platform">{platformName(r.platform)}</span>
      </header>
      <div className="convo-head-acts">
          {c.needs_reply && (
            <button className="btn btn-small" onClick={() => act('replied')} title="Mark as already replied">
              <CheckCheck size={15} aria-hidden="true" /> <span>Mark replied</span>
            </button>
          )}
          {c.archived
            ? <button className="btn btn-small" onClick={() => act('unarchive')} title="Move to inbox"><ArchiveRestore size={15} aria-hidden="true" /> <span>Move to inbox</span></button>
            : <button className="btn btn-small" onClick={() => act('archive')} title="Archive"><Archive size={15} aria-hidden="true" /> <span>Archive</span></button>}
      </div>
      </div>

      <div className="convo-messages">
        {c.messages.map((m, i) => (
          <div key={m.id} className={`msg ${m.role === 'guest' ? 'msg-guest' : 'msg-you'}`}>
            <p className={`bubble ${m.role === 'guest' ? 'bubble-guest' : 'bubble-you'}`}>{m.body}</p>
            <span className="msg-time">
              {m.role === 'host' ? 'You, ' : ''}{messageTime(m.at)}
              {c.needs_reply && i === c.messages.length - 1 && <span className="tag-wait msg-tag">Needs reply</span>}
            </span>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <ReplyBox convo={c} claudeReady={claudeReady} onChange={(x) => { setC(x); onChanged() }} reload={() => { load(false); onChanged() }} />
    </article>
  )
}

const ADJUSTS = [
  { key: 'shorter', label: 'Shorter' },
  { key: 'warmer', label: 'Warmer' },
  { key: 'detail', label: 'More detail' },
]

function ReplyBox({ convo, claudeReady, onChange, reload }: {
  convo: Conversation; claudeReady: boolean; onChange: (c: Conversation) => void; reload: () => void
}) {
  const d = convo.draft
  const id = convo.reservation.id
  const [text, setText] = useState(d?.status === 'ready' ? d.draft_text : '')
  const [edited, setEdited] = useState(false)
  const [busy, setBusy] = useState<'' | 'send' | 'suggest' | 'improve'>('')
  const [msg, setMsg] = useState('')
  const [before, setBefore] = useState<string | null>(null)  // what you had before Rewrite, for Undo
  const area = useRef<HTMLTextAreaElement>(null)
  const lastIsGuest = convo.messages.length > 0 && convo.messages[convo.messages.length - 1].role === 'guest'

  // A new suggestion arrived: show it, unless you're in the middle of typing.
  useEffect(() => {
    if (d?.status === 'ready' && !edited) setText(d.draft_text)
  }, [d?.status, d?.draft_text, edited])

  useEffect(() => {
    const el = area.current
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight + 2, 320)}px` }
  }, [text])

  const drafting = d?.status === 'drafting' || busy === 'suggest' || busy === 'improve'
  const isSuggestion = d?.status === 'ready' && !edited && text === d.draft_text
  const needsFill = /\[ADD:/i.test(text)

  async function send() {
    setBusy('send')
    setMsg('')
    try {
      onChange(await api.reply(id, text))
      setText('')
      setEdited(false)
      setBefore(null)
    } catch (e) {
      setMsg((e as ApiError).message)
    }
    setBusy('')
  }

  async function suggest(adjust = '') {
    setBusy('suggest')
    setMsg('')
    // Something is typed: make that better, never throw it away.
    if (text.trim()) {
      setBusy('improve')
      try {
        const r = await api.improve(id, text, adjust)
        setBefore(text)
        setText(r.text)
        setEdited(true)
      } catch (e) {
        setMsg((e as ApiError).message)
      }
      setBusy('')
      return
    }
    try {
      if (d && (d.status === 'ready' || d.status === 'error')) await api.rewrite(d.id, adjust)
      else await api.suggest(id)
      setEdited(false)
      setTimeout(reload, 600)
    } catch (e) {
      setMsg((e as ApiError).message)
    }
    setTimeout(() => setBusy(''), 1200)
  }

  return (
    <div className="reply-box">
      {drafting ? (
        <p className="writing">{busy === 'improve' ? 'Making your message better…' : 'Writing a reply in your voice…'}</p>
      ) : (
        <>
          {isSuggestion && <span className="reply-label"><Sparkles size={15} aria-hidden="true" /> Suggested reply. Edit it or send as is.</span>}
          {d?.status === 'error' && <p className="error">{d.error}</p>}
          <textarea
            ref={area}
            className={isSuggestion ? 'is-suggestion' : ''}
            value={text}
            onChange={(e) => { setText(e.target.value); setEdited(true); setMsg(''); setBefore(null) }}
            placeholder={`Write to ${convo.reservation.guest_name.split(' ')[0] || 'the guest'}…`}
            aria-label={`Reply to ${convo.reservation.guest_name}`}
            rows={3}
          />
        </>
      )}
      {needsFill && !drafting && <p className="fill-in">Fill in the part in [brackets] before sending.</p>}
      {msg && <p className="error" role="alert"><CircleAlert size={16} aria-hidden="true" /> {msg}</p>}

      <div className="draft-actions">
        <button className="btn btn-send" disabled={!!busy || drafting || !text.trim() || needsFill} onClick={send}>
          <Send size={18} aria-hidden="true" /> {busy === 'send' ? 'Sending…' : 'Send'}
        </button>
        {claudeReady && (lastIsGuest || text.trim()) && (
          <div className="adjusts" role="group" aria-label="Suggested reply">
            <button className="btn btn-small" disabled={!!busy || drafting} onClick={() => suggest('')}>
              {text.trim() ? <><RefreshCw size={15} aria-hidden="true" /> Rewrite</> : <><Sparkles size={15} aria-hidden="true" /> Suggest a reply</>}
            </button>
            {before !== null && (
              <button className="btn btn-small" disabled={!!busy} onClick={() => { setText(before); setBefore(null) }}>
                <Undo2 size={15} aria-hidden="true" /> Undo
              </button>
            )}
            {text.trim() && ADJUSTS.map((a) => (
              <button key={a.key} className="btn btn-small" disabled={!!busy || drafting} onClick={() => suggest(a.key)}>{a.label}</button>
            ))}
          </div>
        )}
        {d && (d.status === 'ready' || d.status === 'error') && (
          <span className="draft-actions-end">
            <button className="link-btn" disabled={!!busy} onClick={() => api.skip(d.id).then(reload)}>No reply needed</button>
          </span>
        )}
      </div>
    </div>
  )
}

// ---------- setup and status ----------

function SetupSteps({ info }: { info: GuestsInfo }) {
  const steps = [
    { done: info.hospitable_connected, label: 'Connect Hospitable', note: 'So Savannah can read guest messages' },
    { done: info.claude_connected, label: 'Add your Claude key', note: 'So Savannah can write drafts' },
  ]
  return (
    <section className="setup-steps">
      <h2>Two steps to get started</h2>
      <ol>
        {steps.map((s) => (
          <li key={s.label} className={s.done ? 'is-done' : ''}>
            <span className="tick">{s.done ? <Check size={18} strokeWidth={2.5} aria-hidden="true" /> : null}</span>
            <span>
              <strong>{s.label}</strong>
              <span className="muted small">{s.done ? 'Done' : s.note}</span>
            </span>
          </li>
        ))}
      </ol>
      <Link to="/settings" className="btn btn-gold">Open Settings</Link>
    </section>
  )
}

function StatusStrip({ info, onChange }: { info: GuestsInfo; onChange: () => void }) {
  const imp = info.import
  const pct = imp.total ? Math.round((imp.done / imp.total) * 100) : 0
  const [checkingNow, setCheckingNow] = useState(false)
  async function act(fn: () => Promise<unknown>) {
    await fn().catch(() => {})
    setTimeout(onChange, 300)
  }
  async function checkNow() {
    setCheckingNow(true)
    await api.checkNow().catch(() => {})
    setCheckingNow(false)
    onChange()
  }
  return (
    <section className="status-strip">
      {imp.running ? (
        <div className="learning">
          <div className="learning-row">
            <Sparkles size={18} aria-hidden="true" />
            <span>Learning from your past conversations</span>
            <span className="muted">{imp.done} of {imp.total || '…'}</span>
          </div>
          <div className="meter"><span style={{ width: `${pct}%` }} /></div>
        </div>
      ) : (
        <div className="chips">
          <span className={`chip ${info.last_error ? 'chip-bad' : 'chip-good'}`}>
            {info.last_error ? <CircleAlert size={16} aria-hidden="true" /> : <span className="dot" />}
            {info.last_error ? info.last_error : info.checking ? 'Checking Hospitable…' : `Checked ${timeAgo(info.last_check_at)}`}
          </span>
          <span className="chip">
            <Sparkles size={16} aria-hidden="true" />
            Learned from {info.memory.conversations} conversations
          </span>
          {imp.error && <span className="chip chip-bad"><CircleAlert size={16} aria-hidden="true" />{imp.error}</span>}
          <span className="chip-actions">
            <button className="btn btn-small" onClick={checkNow} disabled={info.checking || checkingNow}>
              <RefreshCw size={16} aria-hidden="true" className={checkingNow ? 'spin' : ''} /> {checkingNow ? 'Checking…' : 'Check now'}
            </button>
            <button className="btn btn-small" onClick={() => act(api.learn)}>
              <Sparkles size={16} aria-hidden="true" /> Learn again
            </button>
          </span>
        </div>
      )}
    </section>
  )
}

/** Guest's profile photo from Airbnb/VRBO, or their first letter if there's none (or it won't load). */
function Avatar({ name, photo }: { name: string; photo?: string }) {
  const [broken, setBroken] = useState(false)
  if (photo && !broken) {
    return <img className="avatar avatar-photo" src={photo} alt="" aria-hidden="true" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
  }
  return <span className="avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
}
