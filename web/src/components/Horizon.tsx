// A savannah horizon whose sun follows the real time of day.
// Sunrise ~6am on the left, sunset ~7pm on the right; at night a moon and a few stars.

function sunPosition(date: Date) {
  const hours = date.getHours() + date.getMinutes() / 60
  const day = hours >= 6 && hours <= 19
  const t = day ? (hours - 6) / 13 : ((hours + 24 - 19) % 24) / 11
  const x = 60 + t * 880
  const y = 140 - Math.sin(t * Math.PI) * 52
  return { x, y, day }
}

export default function Horizon({ now = new Date() }: { now?: Date }) {
  const { x, y, day } = sunPosition(now)
  return (
    <svg className="horizon" viewBox="0 0 1000 200" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
      {!day && (
        <g className="stars">
          <circle cx="120" cy="84" r="2" />
          <circle cx="260" cy="104" r="1.5" />
          <circle cx="430" cy="78" r="2" />
          <circle cx="610" cy="96" r="1.5" />
          <circle cx="820" cy="82" r="2" />
        </g>
      )}
      <circle className={day ? 'sun' : 'moon'} cx={x} cy={y} r={day ? 22 : 15} />
      <path className="hill-far" d="M0 150 C180 128 320 138 480 134 C650 130 820 118 1000 126 V200 H0Z" />
      <path className="hill-near" d="M0 172 C200 158 380 166 560 162 C740 158 880 152 1000 158 V200 H0Z" />
      <g className="acacia">
        <path d="M770 166 V118" strokeWidth="5" strokeLinecap="round" />
        <path d="M770 140 L752 124 M770 132 L790 118" strokeWidth="4" strokeLinecap="round" />
        <ellipse cx="770" cy="110" rx="52" ry="12" />
        <path d="M232 160 V136" strokeWidth="3" strokeLinecap="round" />
        <ellipse cx="232" cy="132" rx="24" ry="6" />
      </g>
    </svg>
  )
}
