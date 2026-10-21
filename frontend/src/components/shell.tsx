// Shared building blocks for every page (Page 0: Shell). Plain cards, one answer line, no coloured edges.
import { useId, useState, type ReactNode } from 'react'
import { Info, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react'
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { rupees0, rupeesCompact } from '../lib/biz'

/** Chart axis and tooltip style shared by all charts (same as the Fraud check page). */
export const AX = { tick: { fontSize: 12, fill: 'var(--muted)' }, stroke: 'var(--line)', tickLine: false } as const
export const TT = { contentStyle: { borderRadius: 12, border: '1px solid var(--line)', background: 'var(--surface)', fontSize: 12 } }
/** Chart height in px: 300 normally, 240 when compact. */
export const chartHeight = (compact = false) => (compact ? 240 : 300)

/** Rupee amount with Indian digit grouping. Input is in paise. */
export function Money({ paise, compact = false, className = '' }: { paise: number; compact?: boolean; className?: string }) {
  return <span className={`num ${className}`}>{compact ? rupeesCompact(paise) : rupees0(paise)}</span>
}

/** Small ⓘ that explains a term on hover, focus or tap. One short sentence only. */
export function Tip({ text }: { text: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        className="grid size-5 place-items-center rounded-full text-muted hover:text-ink focus-visible:outline-2"
        aria-label={text}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
      >
        <Info size={14} aria-hidden />
      </button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-1/2 top-full z-40 mt-1.5 w-56 -translate-x-1/2 rounded-lg border border-line bg-surface p-2.5 text-xs font-normal leading-snug text-ink shadow-lg">
          {text}
        </span>
      )}
    </span>
  )
}

export type Status = 'ok' | 'warn' | 'bad' | 'neutral'
const STATUS_CLS: Record<Status, string> = { ok: 'chip-ok', warn: 'chip-warn', bad: 'chip-bad', neutral: '' }
/** Small status label. Colour is for risk or status only. */
export function StatusChip({ status = 'neutral', children }: { status?: Status; children: ReactNode }) {
  return <span className={`chip ${STATUS_CLS[status]}`}>{children}</span>
}

/** Page title plus the one plain answer sentence. */
export function PageHeader({ title, answer, action }: { title: string; answer?: ReactNode; action?: ReactNode }) {
  return (
    <header className="page-in mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight leading-tight">{title}</h1>
        {answer && <p className="mt-2 text-base md:text-lg text-ink/80">{answer}</p>}
      </div>
      {action}
    </header>
  )
}

/** Chart in an equal-height card. The title is the one-line takeaway; `alt` is the text summary for screen readers. */
export function ChartCard({ title, alt, tip, compact = false, children }: { title: string; alt: string; tip?: string; compact?: boolean; children: ReactNode }) {
  return (
    <figure className="card p-5 h-full min-w-0 flex flex-col">
      <figcaption className="mb-3 font-semibold leading-snug">
        {title} {tip && <Tip text={tip} />}
      </figcaption>
      <div role="img" aria-label={alt} className="min-w-0 flex-1" style={{ minHeight: chartHeight(compact) }}>
        {children}
      </div>
    </figure>
  )
}

/** Tiny trend line, drawn as plain SVG so it costs no chart-library weight. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null
  const lo = Math.min(...values)
  const span = Math.max(...values) - lo || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${22 - ((v - lo) / span) * 20}`).join(' ')
  return (
    <svg viewBox="0 0 100 24" className="h-6 w-full" preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke="var(--brand)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

/** Headline number with optional sparkline and "vs last period". Becomes a link when `onClick` is given. */
export function KpiCard({ label, value, delta, spark, tip, icon: Icon, onClick }: {
  label: string
  value: ReactNode
  /** Change versus the last period, as a fraction (0.12 = +12%). */
  delta?: number
  spark?: number[]
  tip?: string
  icon?: LucideIcon
  onClick?: () => void
}) {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-sm text-muted">
        {Icon && <Icon size={15} aria-hidden />} {label} {tip && <Tip text={tip} />}
      </div>
      <div className="mt-1 text-2xl md:text-[1.75rem] font-bold tracking-tight num">{value}</div>
      {spark && <div className="mt-2"><Sparkline values={spark} /></div>}
      {delta !== undefined && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-muted">
          {delta >= 0 ? <TrendingUp size={13} aria-hidden /> : <TrendingDown size={13} aria-hidden />}
          <span className="num font-medium text-ink">{delta >= 0 ? '+' : ''}{(delta * 100).toFixed(0)}%</span> vs last period
        </div>
      )}
    </>
  )
  // The whole card is clickable through an overlay button, so the ⓘ tooltip is never nested inside another button.
  return (
    <div className={`card p-4 h-full relative ${onClick ? 'card-link' : ''}`}>
      {onClick && <button type="button" onClick={onClick} className="absolute inset-0 rounded-[inherit]" aria-label={`${label}: see payments`} />}
      <div className="relative pointer-events-none [&_button]:pointer-events-auto">{body}</div>
    </div>
  )
}

/** Nothing to show yet: say so and give one next step. */
export function EmptyState({ icon: Icon, title, sub, action }: { icon: LucideIcon; title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-2 px-4 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-sunken text-muted"><Icon size={22} aria-hidden /></span>
      <p className="font-semibold">{title}</p>
      {sub && <p className="max-w-sm text-sm text-muted">{sub}</p>}
      {action}
    </div>
  )
}

/** Money waterfall: sales, minus refunds, minus money not received, other differences, equals money in the bank. */
export function Waterfall({ w, height = chartHeight() }: { w: { sales: number; refunded: number; not_received: number; other: number; in_bank: number }; height?: number }) {
  const afterRefund = w.sales - w.refunded
  const afterMissing = afterRefund - w.not_received
  // Each bar floats between a low and a high value (a range bar), so the steps hang from the running total.
  const step = (name: string, low: number, v: number, fill: string) => ({ name, range: [low, low + v] as [number, number], v, fill })
  const bars = [
    step('Sales', 0, w.sales, '#1F4FD8'),
    step('Refunds', afterRefund, w.refunded, '#94A3B8'),
    step('Missing', afterMissing, w.not_received, '#B7700B'),
    step('Other', Math.min(afterMissing, afterMissing + w.other), Math.abs(w.other), '#CBD5E1'),
    step('In bank', 0, w.in_bank, '#1F4FD8'),
  ]
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={bars} margin={{ left: 0, right: 8, top: 18 }}>
        <XAxis {...AX} dataKey="name" interval={0} />
        <YAxis {...AX} width={68} tickFormatter={(v) => rupeesCompact(v)} />
        <Tooltip {...TT} cursor={false} formatter={(_v, _n, p) => [rupees0((p.payload as { v: number }).v), 'Amount']} />
        <Bar dataKey="range" name="Amount" radius={[4, 4, 4, 4]} isAnimationActive={false}>
          {bars.map((x) => <Cell key={x.name} fill={x.fill} />)}
          <LabelList dataKey="v" position="top" formatter={(v) => rupeesCompact(Number(v))} style={{ fontSize: 11, fill: 'var(--ink)' }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
