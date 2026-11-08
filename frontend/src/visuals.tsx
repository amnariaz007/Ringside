/* Ringside's visual language: the ring. Risk scores are rings that fill as risk
   grows; decorative concentric rings echo the logo's "ring of accounts". */

import type { Level } from './api'

export function RiskRing({ score, level, size = 30 }: { score: number | null; level: Level | null; size?: number }) {
  const stroke = size >= 60 ? 6 : 3
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const value = Math.max(0, Math.min(100, score ?? 0))
  return (
    <span
      className={`risk-ring ${size >= 60 ? 'lg' : ''}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={score === null ? 'Not scored' : `Risk ${score} of 100, ${level}`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        {score !== null && level && value > 0 && (
          <circle
            className={`arc-${level}`}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${(value / 100) * c} ${c}`}
          />
        )}
      </svg>
      <span>{score ?? '–'}</span>
    </span>
  )
}

export function RiskCell({ score, level }: { score: number | null; level: Level | null }) {
  return (
    <span className="risk-cell">
      <RiskRing score={score} level={level} />
      {level && <span className={`level-word level-${level}`}>{level}</span>}
    </span>
  )
}

/** Concentric rings with five nodes and one flagged: the logo, as a backdrop. */
export function RingsArt({ size = 420, className = '' }: { size?: number; className?: string }) {
  const nodes = [-90, -18, 54, 126, 198].map((deg) => {
    const a = (deg * Math.PI) / 180
    return { x: 210 + 120 * Math.cos(a), y: 210 + 120 * Math.sin(a) }
  })
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 420 420" aria-hidden="true">
      {[200, 165, 120, 75].map((r, i) => (
        <circle key={r} cx="210" cy="210" r={r} fill="none" stroke="#c9d2e3" strokeOpacity={0.08 + i * 0.05}
          strokeWidth={i === 2 ? 2 : 1} strokeDasharray={i === 0 ? '2 6' : undefined} />
      ))}
      {nodes.map((n, i) => (
        <circle key={i} cx={n.x} cy={n.y} r={i === 1 ? 11 : 8} fill={i === 1 ? '#e2685c' : '#ffffff'}
          fillOpacity={i === 1 ? 0.95 : 0.55} stroke={i === 1 ? '#ffffff' : 'none'} strokeWidth="3" />
      ))}
    </svg>
  )
}

const ICONS: Record<string, string> = {
  overview: 'M3 12 12 4l9 8M5 10v10h5v-6h4v6h5V10',
  orders: 'M4 6h16M4 12h16M4 18h10',
  rings: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4.5a1.5 1.5 0 1 0 0 .01M5.5 12a1.5 1.5 0 1 0 0 .01M18.5 12a1.5 1.5 0 1 0 0 .01',
  disputes: 'M12 3 4 6v6c0 4.5 3.4 8.4 8 9 4.6-.6 8-4.5 8-9V6l-8-3Zm0 6v4m0 3v.01',
  audit: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
}

export function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  )
}
