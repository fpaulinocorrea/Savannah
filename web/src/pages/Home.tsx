import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type BooksSummary, type GuestsInfo } from '../api'
import { BookOpen, MessageCircle } from 'lucide-react'
import Horizon from '../components/Horizon'
import BuildProgress from '../components/BuildProgress'

function greeting(date: Date) {
  const h = date.getHours()
  if (h < 5) return 'Good evening'
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export default function Home({ name }: { name: string }) {
  const now = new Date()
  const [guests, setGuests] = useState<GuestsInfo | null>(null)
  const [books, setBooks] = useState<BooksSummary | null>(null)
  useEffect(() => {
    const load = () => {
      api.guests().then(setGuests).catch(() => {})
      api.books().then(setBooks).catch(() => {})
    }
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])
  const waiting = guests?.waiting.length ?? 0
  const guestNote = !guests
    ? ' '
    : !guests.hospitable_connected || !guests.claude_connected
      ? 'Connect in Settings to start'
      : waiting === 0
        ? 'All guests answered'
        : `${waiting} ${waiting === 1 ? 'guest is' : 'guests are'} waiting`
  const review = books?.review_count ?? 0
  const booksNote = !books
    ? ' '
    : books.banks.length === 0
      ? 'Connect Chase to start'
      : review > 0
        ? `${review} to review`
        : 'Everything is sorted'
  const today = now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div className="home">
      <header className="home-head">
        <Horizon now={now} />
        <div className="home-hello">
          <h1 className="display">{greeting(now)}, {name}</h1>
          <p className="muted">{today}</p>
        </div>
      </header>

      <div className="doors">
        <Link to="/guests" className="door door-guests">
          <span className="door-icon"><MessageCircle size={30} strokeWidth={1.8} aria-hidden="true" /></span>
          <span className="door-title">Guests</span>
          <span className="door-note">{guestNote}</span>
          {waiting > 0 && <span className="door-badge" aria-hidden="true">{waiting}</span>}
        </Link>
        <Link to="/books" className="door door-books">
          <span className="door-icon"><BookOpen size={30} strokeWidth={1.8} aria-hidden="true" /></span>
          <span className="door-title">Books</span>
          <span className="door-note">{booksNote}</span>
          {review > 0 && <span className="door-badge door-badge-money" aria-hidden="true">{review}</span>}
        </Link>
      </div>

      <BuildProgress done={3} />
    </div>
  )
}
