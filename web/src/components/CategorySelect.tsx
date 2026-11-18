import type { LedgerAccount } from '../api'

const GROUPS: { kind: LedgerAccount['kind']; label: string }[] = [
  { kind: 'income', label: 'Money in (income)' },
  { kind: 'expense', label: 'Money out (expenses)' },
  { kind: 'transfer', label: 'Between my accounts' },
  { kind: 'owner', label: 'Owner' },
]

// A plain dropdown: works well on phones and with the keyboard.
export default function CategorySelect({
  accounts, value, onChange, label, moneyIn,
}: {
  accounts: LedgerAccount[]
  value: number | null
  onChange: (id: number) => void
  label: string
  moneyIn?: boolean
}) {
  // Show the most likely group first.
  const order = moneyIn ? GROUPS : [GROUPS[1], GROUPS[0], GROUPS[2], GROUPS[3]]
  return (
    <select
      className="cat-select"
      value={value ?? ''}
      onChange={(e) => e.target.value && onChange(Number(e.target.value))}
      aria-label={label}
    >
      <option value="" disabled>Choose a category…</option>
      {order.map((g) => {
        const items = accounts.filter((a) => a.kind === g.kind && a.active)
        return items.length ? (
          <optgroup key={g.kind} label={g.label}>
            {items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </optgroup>
        ) : null
      })}
    </select>
  )
}
