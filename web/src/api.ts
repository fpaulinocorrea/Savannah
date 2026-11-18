// Small helper for talking to the Savannah server.

export type Status = { set_up: boolean; signed_in: boolean; name: string; version: string }
export type SystemInfo = {
  version: string
  phone_urls: string[]
  data_folder: string
  conversations_folder: string
}

export type KeyInfo = { saved: boolean; ending: string }
export type Connections = { hospitable: KeyInfo; claude: KeyInfo; plaid?: KeyInfo }
export type TestResult = { ok: boolean; message: string; homes?: string[] }

export type Draft = {
  id: number
  reservation_id: string
  guest_name: string
  property_name: string
  platform: string
  arrival: string
  departure: string
  guest_message: string
  draft_text: string
  status: 'drafting' | 'ready' | 'error' | 'sent'
  error: string
  created_at: string
  sent_at: string | null
}

export type GuestsInfo = {
  hospitable_connected: boolean
  claude_connected: boolean
  mode: 'suggest' | 'auto'
  last_check_at: string | null
  checking: boolean
  last_error: string
  import: { running: boolean; done: number; total: number; finished_at: string | null; error: string }
  memory: { conversations: number; examples: number }
  waiting: Draft[]
  sent: Draft[]
}

export type HooksInfo = { host: string; link: string; last_at: string | null; last_action: string; count: number }
export type Message = { id: string; role: 'guest' | 'host'; body: string; at: string }

export type InboxRow = {
  reservation_id: string; guest_name: string; property_name: string; platform: string; photo?: string
  arrival: string; departure: string; last_role: 'guest' | 'host'; last_body: string; last_at: string
  needs_reply: boolean; draft_status: '' | 'drafting' | 'ready' | 'error'; kind?: 'stay' | 'inquiry'
}
export type Conversation = {
  reservation: { id: string; guest_name: string; property_name: string; platform: string; arrival: string; departure: string; status: string; kind?: 'stay' | 'inquiry'; photo?: string }
  messages: Message[]
  draft: Draft | null
}

export function whenShort(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const mins = (Date.now() - d.getTime()) / 60000
  if (mins < 1) return 'now'
  if (mins < 60) return `${Math.round(mins)}m`
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h`
  if (mins < 60 * 24 * 6) return d.toLocaleDateString(undefined, { weekday: 'short' })
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function messageTime(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export type Bank = {
  id: string; name: string; mask: string; type: string; balance_cents: number | null
  ledger_account_id: number | null; ledger_name: string; institution: string; error: string; item_id: string
}
export type BooksSummary = {
  chart_count: number; chart_from_quickbooks: boolean; quickbooks_history: number
  plaid_keys: boolean; plaid_items_used: number; plaid_item_limit: number; plaid_institutions: string[]; claude_connected: boolean; start_date: string | null; review_count: number
  month: { label: string; in_cents: number; out_cents: number }
  banks: Bank[]; syncing: boolean; last_sync_at: string | null; last_error: string
  last_result: { new: number; rule: number; learned: number; ai: number; unsure: number } | null
}
export type LedgerAccount = { id: number; name: string; type: string; kind: 'income' | 'expense' | 'transfer' | 'owner'; active: boolean; source: string }
export type Txn = {
  id: number; date: string; description: string; merchant: string; amount_cents: number; source: string
  account: string; category_id: number | null; category: string; category_source: string
  needs_review: boolean; suggested_rule: string
  splits: { category_id: number | null; category: string; amount_cents: number; memo: string }[]
}
export type ImportFile = { name: string; size: number; kind: '' | 'accounts' | 'transactions' | 'journal' }
export type JournalPreview = {
  blocks: number; splits_filled: number; splits_still_missing: number; journal_entries: number
  unknown_accounts: string[]; pl_effect: { name: string; cents: number; label: string }[]
  samples: { date: string; name: string; parts: { category: string; cents: number }[] }[]
}
export type Preview = {
  count: number; first: string; last: string; money_in_cents: number; money_out_cents: number
  accounts: { name: string; count: number }[]; skipped: number; skipped_reasons: Record<string, number>
  samples: { date: string; description: string; amount_cents: number; account: string; category: string }[]
}
export type StatementSplit = {
  lines: { part: string; label: string; category_id: number | null; amount_cents: number }[]
  where: string; statement_date: string; lender: string; warning: string
}
export type RuleMode = 'auto' | 'suggest'
export type Rule = { id: number; match: string; direction: string; category: string; times_used: number; mode: RuleMode; split: boolean }

export type ReportRow = { path: string; name: string; depth: number; values: number[]; parent: boolean }
export type ReportSection = { key: string; title: string; rows: ReportRow[]; total: number[] }
export type PL = {
  columns: string[]; ranges: [string, string][]; has_prev: boolean; prev_label: string; range_label: string
  sections: ReportSection[]
  lines: { total_income: number[]; gross_profit: number[] | null; net_operating_income: number[]; net_income: number[] }
  unsorted: { in_cents: number; out_cents: number }
}
export type CashFlow = { columns: string[]; ranges: [string, string][]; range_label: string; sections: ReportSection[]; net_change: number[]; bank_accounts: string[] }
export type Booking = {
  id: string; guest_name: string; property_name: string; platform: string; arrival: string; departure: string
  status: string; payout_cents: number | null; nights: number | null
}
export type Upcoming = {
  saved_at: string | null; error: string; bookings: Booking[]
  months: { month: string; count: number; payout_cents: number; missing: number }[]
  total_cents: number; missing: number
}
export type BalanceSheet = {
  dates: string[]; columns: string[]; sections: (ReportSection & { side: 'assets' | 'liabilities' | 'equity' })[]
  totals: { assets: number[]; liabilities: number[]; equity: number[] }; balanced: boolean; liabilities_and_equity: number[]
}
export type Detail = {
  count: number; total_cents: number
  items: { id: number; date: string; description: string; account: string; source: string; cents: number }[]
}
export type BalanceCheck = {
  bank_account_id: string; name: string; card: boolean; ledger_name: string
  chase_cents: number; savannah_cents: number; difference_cents: number; matches: boolean
  balance_at: string | null; suggestion: { id: number; name: string; why?: string } | null; left_out: boolean; full_history: boolean
  counted_twice?: boolean; in_quickbooks?: boolean
}
export type ReportConfig = {
  preset: string; start: string; end: string
  breakdown: '' | 'month' | 'quarter' | 'year'
  compare: '' | 'prev_period' | 'prev_year'
  show: { total: boolean; pct: boolean; prev: boolean; change: boolean }
  expand: boolean
}
export type SavedView = { id: number; name: string; report: 'pl' | 'cashflow' | 'upcoming' | 'bs'; config: ReportConfig }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, "Can't reach Savannah. Check that your computer is on and Savannah is running.")
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'Something went wrong. Try again.'
    throw new ApiError(res.status, detail)
  }
  return data as T
}

export const api = {
  status: () => request<Status>('GET', '/status'),
  setup: (name: string, password: string) => request('POST', '/setup', { name, password }),
  login: (password: string) => request('POST', '/login', { password }),
  logout: () => request('POST', '/logout'),
  system: () => request<SystemInfo>('GET', '/system'),
  changePassword: (current: string, next: string) => request('POST', '/password', { current, new: next }),

  connections: () => request<Connections>('GET', '/connections'),
  hooks: () => request<HooksInfo>('GET', '/hooks'),
  setHookHost: (host: string) => request<HooksInfo>('POST', '/hooks', { host }),
  testHooks: () => request<{ ok: boolean; message: string }>('POST', '/hooks/test'),
  saveKey: (name: 'hospitable' | 'claude', key: string) => request<TestResult>('POST', `/connections/${name}`, { key }),
  testKey: (name: 'hospitable' | 'claude') => request<TestResult>('POST', `/connections/${name}/test`),
  removeKey: (name: 'hospitable' | 'claude') => request('DELETE', `/connections/${name}`),

  guests: () => request<GuestsInfo>('GET', '/guests'),
  checkNow: () => request('POST', '/guests/check'),
  learn: () => request('POST', '/guests/learn'),
  inbox: (view: 'all' | 'waiting', q = '', offset = 0) =>
    request<{ total: number; waiting: number; items: InboxRow[] }>(
      'GET', `/guests/inbox?view=${view}&q=${encodeURIComponent(q)}&offset=${offset}`,
    ),
  conversation: (reservationId: string, fresh = false) =>
    request<Conversation>('GET', `/guests/conversation/${encodeURIComponent(reservationId)}${fresh ? '?fresh=true' : ''}`),
  reply: (reservationId: string, text: string) =>
    request<Conversation>('POST', `/guests/conversation/${encodeURIComponent(reservationId)}/send`, { text }),
  suggest: (reservationId: string) =>
    request('POST', `/guests/conversation/${encodeURIComponent(reservationId)}/suggest`),
  send: (id: number, text: string) => request('POST', `/drafts/${id}/send`, { text }),
  rewrite: (id: number, adjust = '') => request('POST', `/drafts/${id}/rewrite`, { adjust }),
  improve: (reservationId: string, text: string, adjust = '') => request<{ text: string }>('POST', `/guests/conversation/${reservationId}/improve`, { text, adjust }),
  skip: (id: number) => request('POST', `/drafts/${id}/skip`),

  books: () => request<BooksSummary>('GET', '/books/summary'),
  accounts: () => request<LedgerAccount[]>('GET', '/books/accounts'),
  addAccount: (name: string, type: string) => request<LedgerAccount>('POST', '/books/accounts', { name, type }),
  starterChart: () => request<{ added: number }>('POST', '/books/starter-chart'),
  importFiles: () => request<{ folder: string; files: ImportFile[] }>('GET', '/books/imports'),
  importAccounts: (file: string) => request<{ added: number; updated: number }>('POST', '/books/import/accounts', { file }),
  previewHistory: (file: string, flip: boolean) => request<Preview>('POST', '/books/import/transactions/preview', { file, flip }),
  importHistory: (file: string, flip: boolean) =>
    request<{ added: number; already_there: number; start_date: string }>('POST', '/books/import/transactions', { file, flip }),
  setStartDate: (date: string) => request('POST', '/books/start-date', { date }),
  transactions: (view: 'review' | 'all', q = '', month = '', offset = 0) =>
    request<{ total: number; items: Txn[] }>(
      'GET', `/books/transactions?view=${view}&q=${encodeURIComponent(q)}&month=${month}&offset=${offset}`,
    ),
  setCategory: (id: number, category_id: number, always = false, match = '', mode: RuleMode = 'auto') =>
    request<{ ok: boolean; also_sorted: number }>('POST', `/books/transactions/${id}/category`, { category_id, always, match, mode }),
  setRuleMode: (id: number, mode: RuleMode) => request<{ ok: boolean; filed: number }>('POST', `/books/rules/${id}/mode`, { mode }),
  rules: () => request<Rule[]>('GET', '/books/rules'),
  splitTxn: (id: number, lines: { category_id: number; amount_cents: number; memo: string }[], remember: boolean, match: string) =>
    request('POST', `/books/transactions/${id}/split`, { lines, remember, match }),
  previewJournal: (file: string) => request<JournalPreview>('POST', '/books/import/journal/preview', { file }),
  importJournal: (file: string) => request<{ splits_filled: number; journal_entries: number }>('POST', '/books/import/journal', { file }),
  deleteRule: (id: number) => request('DELETE', `/books/rules/${id}`),
  runRules: () => request<{ sorted: number }>('POST', '/books/rules/run'),

  pl: (c: ReportConfig) =>
    request<PL>('GET', `/reports/pl?start=${c.start}&end=${c.end}&breakdown=${c.breakdown}&compare=${c.compare}`),
  cashflow: (c: ReportConfig) => request<CashFlow>('GET', `/reports/cashflow?start=${c.start}&end=${c.end}&breakdown=${c.breakdown}`),
  upcoming: (refresh = false) => request<Upcoming>('GET', `/reports/upcoming${refresh ? '?refresh=true' : ''}`),
  balanceSheet: (asOf: string, compare: string) => request<BalanceSheet>('GET', `/reports/balance-sheet?as_of=${asOf}&compare=${compare}`),
  detail: (report: 'pl' | 'cashflow' | 'bs', path: string, start: string, end: string) =>
    request<Detail>('GET', `/reports/detail?report=${report}&path=${encodeURIComponent(path)}&start=${start}&end=${end}`),
  balanceCheck: () => request<BalanceCheck[]>('GET', '/books/balance-check'),
  leaveOut: (id: string, leave_out: boolean) => request('POST', `/books/bank-accounts/${id}/leave-out`, { leave_out }),
  useHistory: (id: string) => request<{ transactions: number; starting_balance_cents: number }>('POST', `/books/bank-accounts/${id}/use-history`),
  dataRange: () => request<{ first: string | null; last: string | null }>('GET', '/reports/range'),
  views: () => request<SavedView[]>('GET', '/reports/views'),
  saveView: (name: string, report: SavedView['report'], config: ReportConfig) =>
    request<SavedView>('POST', '/reports/views', { name, report, config }),
  deleteView: (id: number) => request('DELETE', `/reports/views/${id}`),
  syncBank: () => request('POST', '/books/sync'),
  mapBank: (id: string, ledger_account_id: number) => request('POST', `/books/bank-accounts/${id}`, { ledger_account_id }),
  savePlaid: (client_id: string, secret: string) => request<TestResult>('POST', '/connections/plaid', { client_id, secret }),
  removePlaid: () => request('DELETE', '/connections/plaid'),
  plaidLinkToken: (item_id = '') => request<{ link_token: string }>('POST', '/plaid/link-token', { item_id }),
  plaidExchange: (public_token: string, institution: string, reconnected_item = '') =>
    request('POST', '/plaid/exchange', { public_token, institution, reconnected_item }),
  readStatement: async (txnId: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`/api/books/transactions/${txnId}/statement`, { method: 'POST', body, credentials: 'same-origin' })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(res.status, data.detail || 'Could not read that statement.')
    return data as StatementSplit
  },
  upload: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch('/api/books/imports/upload', { method: 'POST', body, credentials: 'same-origin' })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(res.status, typeof data.detail === 'string' ? data.detail : 'Upload failed. Try again.')
    return data as { name: string; kind: string }
  },
}

export function money(cents: number, sign = false) {
  const s = (Math.abs(cents) / 100).toLocaleString(undefined, { style: 'currency', currency: 'USD' })
  if (!sign) return s
  return cents > 0 ? `+${s}` : cents < 0 ? `−${s}` : s
}

export function shortDate(iso: string) {
  return new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function longDate(iso: string) {
  return new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })
}

// ---------- small display helpers ----------

export function platformName(p: string) {
  const k = p.toLowerCase()
  if (k.includes('airbnb')) return 'Airbnb'
  if (k.includes('homeaway') || k.includes('vrbo')) return 'Vrbo'
  if (k.includes('booking')) return 'Booking.com'
  if (k.includes('direct') || k.includes('manual')) return 'Direct'
  return p || 'Booking'
}

export function stayDates(arrival: string, departure: string) {
  const fmt = (s: string) =>
    s ? new Date(s + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''
  return arrival ? `${fmt(arrival)} – ${fmt(departure)}` : ''
}

export function timeAgo(iso: string | null) {
  if (!iso) return 'not yet'
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  if (h < 24) return `${h} hr ago`
  return `${Math.round(h / 24)} days ago`
}
