import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { BookOpen, ChartColumn, House, MessageCircle, Settings } from 'lucide-react'
import Logo from './Logo'

const links = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/guests', label: 'Guests', icon: MessageCircle, end: false },
  { to: '/books', label: 'Books', icon: BookOpen, end: false },
  { to: '/reports', label: 'Reports', icon: ChartColumn, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
]

export default function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="nav-brand">
          <Logo size={32} />
          <span>Savannah</span>
        </div>
        <ul>
          {links.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink to={to} end={end} className="nav-link">
                <Icon size={22} strokeWidth={1.8} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="page">{children}</main>
    </div>
  )
}
