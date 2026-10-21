// Original illustrated scenes (flat style, theme-coloured, animated). They show real situations the app is for.
import { useEffect, useState } from 'react'
import { ShopScene } from './Illustration'

const SKIN = ['#e9b896', '#c68b66', '#8d5a3c']

function Person({ x, y, skin, shirt, hair, flip = false, arm = 'down', blink = false }: { x: number; y: number; skin: string; shirt: string; hair: string; flip?: boolean; arm?: 'down' | 'up'; blink?: boolean }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${flip ? -1 : 1} 1)`}>
      <rect x="-22" y="40" width="44" height="70" rx="16" fill={shirt} />
      <circle cx="0" cy="18" r="19" fill={skin} />
      <path d="M-19 14 q2-22 19-22 q17 0 19 22 q-10-10-19-10 q-9 0-19 10z" fill={hair} />
      <g className={blink ? 'anim-blink' : undefined}><circle cx="-6" cy="19" r="1.8" fill="#1d1d1d" /><circle cx="7" cy="19" r="1.8" fill="#1d1d1d" /></g>
      <path d="M-5 28 q5 4 10 0" fill="none" stroke="#1d1d1d" strokeWidth="1.6" strokeLinecap="round" />
      {arm === 'up' ? <path d="M18 52 q22 -2 26 -26" fill="none" stroke={shirt} strokeWidth="11" strokeLinecap="round" /> : <path d="M-18 56 q-6 22 0 38" fill="none" stroke={shirt} strokeWidth="11" strokeLinecap="round" />}
    </g>
  )
}

/** A customer holds up a paid screen; the shopkeeper's speaker confirms it. The point of the whole app. */
export function CounterScene({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 420 220" className={className} role="img" aria-label="A customer shows a payment on their phone while the shopkeeper checks it">
      <ellipse cx="210" cy="206" rx="190" ry="9" fill="var(--ink)" opacity="0.07" />
      <rect x="20" y="30" width="380" height="150" rx="14" fill="var(--c-teal)" opacity="0.08" />
      {/* shelves behind */}
      {[0, 1].map((r) => <rect key={r} x="262" y={52 + r * 36} width="122" height="6" rx="3" fill="var(--ink)" opacity="0.12" />)}
      {[0, 1, 2, 3].map((i) => <rect key={i} x={270 + i * 28} y="30" width="18" height="22" rx="3" fill={['var(--c-blue)', 'var(--c-clay)', 'var(--c-olive)', 'var(--c-plum)'][i]} opacity="0.75" />)}
      {[0, 1, 2].map((i) => <rect key={i} x={274 + i * 34} y="66" width="22" height="22" rx="3" fill={['var(--c-teal)', 'var(--c-plum)', 'var(--c-blue)'][i]} opacity="0.65" />)}
      <Person x={300} y={50} skin={SKIN[1]} shirt="var(--brand)" hair="#2b2118" blink />
      <Person x={104} y={44} skin={SKIN[0]} shirt="var(--c-clay)" hair="#5a3a24" arm="up" flip />
      {/* the customer's phone */}
      <g transform="translate(138 46)"><g className="anim-floaty">
        <rect width="34" height="54" rx="7" fill="var(--ink)" />
        <rect x="3.5" y="5" width="27" height="44" rx="4" fill="var(--surface)" />
        <circle cx="17" cy="23" r="9" fill="var(--ok)" />
        <path className="anim-tick" d="M12.5 23 l3.5 3.5 l6.5-7" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="9" y="38" width="16" height="3.5" rx="1.75" fill="var(--line)" />
      </g></g>
      {/* counter and the speaker that announces money received */}
      <rect x="40" y="150" width="340" height="48" rx="8" fill="var(--surface)" stroke="var(--line)" strokeWidth="2" />
      <rect x="40" y="150" width="340" height="9" rx="4" fill="var(--brand)" opacity="0.9" />
      <g transform="translate(206 120)">
        {[0, 1].map((i) => <circle key={i} cx="16" cy="14" r="14" fill="none" stroke="var(--ok)" strokeWidth="2" className="anim-wave" style={{ animationDelay: `${i * 1.2}s` }} />)}
        <rect width="32" height="30" rx="8" fill="var(--ink)" />
        <circle cx="16" cy="14" r="8" fill="var(--ok)" opacity="0.9" />
        <text x="16" y="18" textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff">₹</text>
      </g>
      {[0, 1, 2].map((i) => <g key={i} className="anim-coin" style={{ animationDelay: `${i * 1.1}s` }}><circle cx={220 + i * 14} cy="118" r="7" fill="var(--c-clay)" /><text x={220 + i * 14} y="121.5" textAnchor="middle" fontSize="9" fontWeight="700" fill="#fff">₹</text></g>)}
    </svg>
  )
}

/** An analyst reading charts: for the models and fraud pages. */
export function AnalystScene({ className = '' }: { className?: string }) {
  const bars = [46, 70, 38, 86, 58, 74]
  return (
    <svg viewBox="0 0 420 220" className={className} role="img" aria-label="An analyst studies charts on a large screen">
      <ellipse cx="210" cy="206" rx="190" ry="9" fill="var(--ink)" opacity="0.07" />
      <rect x="40" y="22" width="250" height="150" rx="12" fill="var(--surface)" stroke="var(--line)" strokeWidth="2" />
      <rect x="40" y="22" width="250" height="22" rx="12" fill="var(--brand)" opacity="0.92" />
      {[0, 1, 2].map((i) => <circle key={i} cx={56 + i * 12} cy="33" r="3" fill="#fff" opacity="0.8" />)}
      {bars.map((h, i) => <rect key={i} x={62 + i * 38} y={160 - h} width="24" height={h} rx="4" fill={['var(--c-blue)', 'var(--c-teal)'][i % 2]} className="anim-grow" style={{ animationDelay: `${i * 0.35}s` }} />)}
      <path d="M62 120 q46 -50 92 -6 t92 -46" fill="none" stroke="var(--c-clay)" strokeWidth="3" strokeLinecap="round" strokeDasharray="6 5" />
      <g transform="translate(262 60)"><g className="anim-floaty">
        <circle r="26" fill="none" stroke="var(--c-plum)" strokeWidth="5" />
        <path d="M18 18 l20 20" stroke="var(--c-plum)" strokeWidth="6" strokeLinecap="round" />
        <path d="M-9 0 l6 6 l12 -12" fill="none" stroke="var(--ok)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      </g></g>
      <Person x={344} y={62} skin={SKIN[2]} shirt="var(--c-teal)" hair="#171717" flip blink />
      <rect x="318" y="164" width="80" height="12" rx="5" fill="var(--ink)" opacity="0.15" />
      <rect x="40" y="176" width="250" height="8" rx="4" fill="var(--ink)" opacity="0.12" />
    </svg>
  )
}

/** Files flowing into the analysis: for the upload page. */
export function DataScene({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 420 220" className={className} role="img" aria-label="Spreadsheet files flow into a checked, private analysis">
      <ellipse cx="210" cy="206" rx="190" ry="9" fill="var(--ink)" opacity="0.07" />
      {[0, 1, 2].map((i) => (
        <g key={i} transform={`translate(${46 + i * 30} ${52 + i * 26})`}>
          <g className="anim-slide" style={{ animationDelay: `${i * 1.4}s` }}>
            <rect width="62" height="76" rx="8" fill="var(--surface)" stroke="var(--line)" strokeWidth="2" />
            <rect x="8" y="10" width="46" height="8" rx="3" fill={['var(--c-blue)', 'var(--c-teal)', 'var(--c-plum)'][i]} />
            {[0, 1, 2, 3].map((r) => <rect key={r} x="8" y={26 + r * 10} width={r % 2 ? 34 : 46} height="5" rx="2.5" fill="var(--line)" />)}
            <text x="31" y="73" textAnchor="middle" fontSize="8" fontWeight="700" fill="var(--muted)">CSV</text>
          </g>
        </g>
      ))}
      <path d="M190 118 h60" stroke="var(--brand)" strokeWidth="4" strokeLinecap="round" strokeDasharray="2 9" />
      <path d="M244 108 l14 10 l-14 10" fill="none" stroke="var(--brand)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      <g transform="translate(272 54)"><g className="anim-floaty">
        <path d="M60 0 L114 18 V70 q0 34 -54 56 q-54 -22 -54 -56 V18 Z" fill="var(--brand)" />
        <path d="M60 14 L100 28 V68 q0 24 -40 42 q-40 -18 -40 -42 V28 Z" fill="var(--surface)" opacity="0.14" />
        <path className="anim-tick" d="M38 64 l16 16 l30 -34" fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      </g></g>
      {[0, 1, 2].map((i) => <g key={i} className="anim-coin" style={{ animationDelay: `${i * 1.1}s` }}><circle cx={296 + i * 30} cy="60" r="8" fill="var(--c-clay)" /><text x={296 + i * 30} y="64" textAnchor="middle" fontSize="10" fontWeight="700" fill="#fff">₹</text></g>)}
    </svg>
  )
}

/** Rotates between scenes. Pauses on hover or focus, and each dot is a button. */
export function HeroCarousel({ className = '' }: { className?: string }) {
  const scenes = [
    { id: 'shop', label: 'Your shop', node: <ShopScene className={className} /> },
    { id: 'counter', label: 'At the counter', node: <CounterScene className={className} /> },
    { id: 'analyst', label: 'Spotting problems', node: <AnalystScene className={className} /> },
  ]
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    if (paused || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const id = setInterval(() => setI((n) => (n + 1) % scenes.length), 6500)
    return () => clearInterval(id)
  }, [paused, scenes.length])
  return (
    <div className="relative" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <div className="grid">
        {scenes.map((s, k) => (
          <div key={s.id} className="fade-swap [grid-area:1/1]" style={{ opacity: k === i ? 1 : 0, transform: k === i ? 'none' : 'translateX(14px)' }} aria-hidden={k !== i}>{s.node}</div>
        ))}
      </div>
      <div className="flex justify-center gap-2 mt-1" role="group" aria-label="Choose a scene">
        {scenes.map((s, k) => (
          <button key={s.id} onClick={() => setI(k)} aria-label={s.label} aria-current={k === i} className="h-2.5 rounded-full transition-all" style={{ width: k === i ? 26 : 10, background: k === i ? 'var(--brand)' : 'var(--line)' }} />
        ))}
      </div>
    </div>
  )
}
