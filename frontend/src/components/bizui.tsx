import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const EDGES = ['var(--c-blue)', 'var(--c-teal)', 'var(--c-plum)', 'var(--c-clay)', 'var(--c-olive)']
export const edgeFor = (title: string) => EDGES[[...title].reduce((n, c) => n + c.charCodeAt(0), 0) % EDGES.length]

export function Panel({ title, sub, action, children, className = '' }: { title: string; sub?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card panel p-5 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="font-semibold text-[1.02rem] leading-tight">{title}</h2>
          {sub && <p className="text-sm text-muted mt-1">{sub}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Tabs<T extends string>({ items, value, onChange, label }: { items: readonly { id: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg !p-0.5 !rounded-lg max-w-full overflow-x-auto" role="tablist" aria-label={label}>
      {items.map((i) => (
        <button key={i.id} role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md whitespace-nowrap">
          {i.label}
        </button>
      ))}
    </div>
  )
}

/** Page heading: large title on the page background. `art` is accepted for older callers and no longer drawn. */
export function PageHead({ title, sub, action }: { title: string; sub?: string; action?: ReactNode; art?: ReactNode }) {
  return (
    <header className="page-head mb-6 page-in">
      <div className="max-w-3xl">
        <h1>{title}</h1>
        {sub && <p className="mt-2 text-base md:text-lg">{sub}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </header>
  )
}

const SEV = { high: ['chip-bad', 'High priority'], medium: ['chip-warn', 'Medium priority'], low: ['', 'Low priority'] } as const
export function SevChip({ level }: { level: 'high' | 'medium' | 'low' }) {
  return <span className={`chip ${SEV[level][0]}`}>{SEV[level][1]}</span>
}

export function Pager({ page, pages, onChange, total }: { page: number; pages: number; onChange: (p: number) => void; total: number }) {
  return (
    <div className="flex items-center justify-between gap-3 pt-4 text-sm text-muted">
      <span>{total.toLocaleString('en-IN')} in total</span>
      <div className="flex items-center gap-2">
        <button className="btn btn-ghost !min-h-9 !px-2.5" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page"><ChevronLeft size={16} /></button>
        <span>Page <b className="text-ink num">{page}</b> of <span className="num">{Math.max(1, pages)}</span></span>
        <button className="btn btn-ghost !min-h-9 !px-2.5" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page"><ChevronRight size={16} /></button>
      </div>
    </div>
  )
}

export type Review = 'open' | 'checking' | 'ok' | 'issue'
export const REVIEW_LABEL: Record<Review, string> = { open: 'Not reviewed', checking: 'Checking', ok: 'Checked: no problem', issue: 'Checked: real problem' }

/** The merchant's own review status per item, kept in this browser (nothing is sent anywhere). */
export function useReviews(ds: string) {
  const key = `reviews:${ds}`
  const [map, setMap] = useState<Record<string, Review>>({})
  useEffect(() => {
    try {
      setMap(JSON.parse(localStorage.getItem(key) ?? '{}'))
    } catch {
      setMap({})
    }
  }, [key])
  const set = useCallback(
    (id: string, r: Review) =>
      setMap((m) => {
        const next = { ...m, [id]: r }
        try {
          localStorage.setItem(key, JSON.stringify(next))
        } catch {
          /* storage can be blocked */
        }
        return next
      }),
    [key],
  )
  return { get: (id: string): Review => map[id] ?? 'open', set }
}

export function ReviewSelect({ value, onChange, id }: { value: Review; onChange: (r: Review) => void; id: string }) {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <span className="sr-only">Review status for {id}</span>
      <select className="field !py-1.5 !px-2.5 !w-auto !text-sm" value={value} onChange={(e) => onChange(e.target.value as Review)}>
        {(Object.keys(REVIEW_LABEL) as Review[]).map((r) => <option key={r} value={r}>{REVIEW_LABEL[r]}</option>)}
      </select>
    </label>
  )
}
