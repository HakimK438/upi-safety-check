// Original SVG artwork: a market stall with an awning, a UPI-style check badge and floating rupee coins.
// Colours come from the active theme, so the picture changes with it. Motion stops for prefers-reduced-motion.

/** Small mark for the sidebar and top bar: a shop front with a check. */
export function LogoMark({ size = 34, onDark = false }: { size?: number; onDark?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="UPI Safety Check">
      <rect width="40" height="40" rx="11" fill={onDark ? '#fff' : 'var(--brand)'} />
      <path d="M8 16 L10.5 9.5 H29.5 L32 16 Z" fill={onDark ? 'var(--brand)' : '#fff'} />
      <path d="M8 16 q3 3.2 6 0 q3 3.2 6 0 q3 3.2 6 0 q3 3.2 6 0" fill={onDark ? 'var(--brand)' : '#fff'} opacity="0.85" />
      <rect x="10.5" y="19.5" width="19" height="11" rx="1.5" fill={onDark ? 'var(--brand)' : '#fff'} opacity="0.22" />
      <path d="M15.5 25.2 l3.2 3.2 l6-6.4" fill="none" stroke={onDark ? 'var(--brand)' : '#fff'} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Wide scene for the top of the dashboard. */
export function ShopScene({ className = '' }: { className?: string }) {
  const stripes = Array.from({ length: 8 })
  return (
    <svg viewBox="0 0 420 220" className={className} role="img" aria-label="A market stall that accepts UPI payments">
      <defs>
        <clipPath id="awn"><path d="M70 70 L92 22 H328 L350 70 Z" /></clipPath>
      </defs>
      {/* ground and sun */}
      <circle cx="350" cy="52" r="26" fill="var(--c-clay)" opacity="0.18" />
      <ellipse cx="210" cy="205" rx="190" ry="10" fill="var(--ink)" opacity="0.07" />
      {/* stall body */}
      <g className="anim-floaty">
        <rect x="84" y="70" width="252" height="125" rx="6" fill="var(--surface)" stroke="var(--line)" strokeWidth="2" />
        <rect x="84" y="150" width="252" height="45" fill="var(--brand-soft)" />
        <rect x="108" y="92" width="62" height="44" rx="4" fill="var(--c-blue)" opacity="0.2" />
        <rect x="250" y="92" width="62" height="44" rx="4" fill="var(--c-teal)" opacity="0.2" />
        {/* produce crates */}
        <rect x="98" y="158" width="64" height="30" rx="4" fill="var(--c-clay)" opacity="0.85" />
        <circle cx="114" cy="156" r="8" fill="var(--c-olive)" /><circle cx="132" cy="154" r="8" fill="var(--c-clay)" /><circle cx="148" cy="156" r="8" fill="var(--c-plum)" />
        <rect x="258" y="158" width="64" height="30" rx="4" fill="var(--c-teal)" opacity="0.85" />
        <circle cx="274" cy="156" r="8" fill="var(--c-olive)" /><circle cx="292" cy="154" r="8" fill="var(--c-blue)" /><circle cx="308" cy="156" r="8" fill="var(--c-plum)" />
        {/* awning */}
        <g className="anim-sway">
          <path d="M70 70 L92 22 H328 L350 70 Z" fill="var(--surface)" />
          <g clipPath="url(#awn)">
            {stripes.map((_, i) => (i % 2 === 0 ? <rect key={i} x={62 + i * 36} y="18" width="36" height="56" fill="var(--brand)" /> : null))}
          </g>
          <path d="M70 70 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 q13 14 26 0 z" fill="var(--brand)" opacity="0.9" />
        </g>
        {/* counter and phone with UPI check */}
        <rect x="84" y="140" width="252" height="10" rx="3" fill="var(--ink)" opacity="0.14" />
        <g transform="translate(188 96)">
          <rect width="44" height="62" rx="8" fill="var(--ink)" />
          <rect x="4" y="6" width="36" height="50" rx="5" fill="var(--surface)" />
          <circle cx="22" cy="26" r="11" fill="var(--ok)" />
          <path className="anim-tick" d="M16.5 26 l4 4 l7.5-8" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="11" y="43" width="22" height="4" rx="2" fill="var(--line)" />
        </g>
      </g>
      {/* floating coins */}
      {[0, 1, 2].map((i) => (
        <g key={i} className="anim-coin" style={{ animationDelay: `${i * 1.05}s` }}>
          <circle cx={178 + i * 38} cy="92" r="9" fill="var(--c-clay)" opacity="0.95" />
          <text x={178 + i * 38} y="96.5" textAnchor="middle" fontSize="12" fontWeight="700" fill="#fff">₹</text>
        </g>
      ))}
    </svg>
  )
}
