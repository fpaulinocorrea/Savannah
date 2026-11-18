// The Savannah mark: an acacia tree and a low sun.
export default function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <rect width="512" height="512" rx="112" fill="#2E6A4F" />
      <circle cx="340" cy="250" r="64" fill="#E3A93A" />
      <path d="M0 360 C120 330 220 345 300 340 C390 334 450 322 512 330 V512 H0Z" fill="#245640" />
      <path d="M168 360 V262" stroke="#14271E" strokeWidth="16" strokeLinecap="round" />
      <path d="M168 300 L132 268 M168 286 L204 258" stroke="#14271E" strokeWidth="12" strokeLinecap="round" />
      <ellipse cx="168" cy="244" rx="92" ry="26" fill="#14271E" />
    </svg>
  )
}
