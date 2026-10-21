import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CircleCheck, ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX, ThumbsUp, type LucideIcon } from 'lucide-react'
import { rupees0, useBiz } from '../lib/biz'
import { bizApi, branchName, dtFmt, fraudLink, type RiskAlertItem } from '../lib/bizApi'
import { useBizCtx } from '../lib/bizctx'
import { Pager } from '../components/bizui'
import { EmptyState, PageHeader, Tip } from '../components/shell'

const PRESETS = [{ id: '7', label: '7 days', days: 7 }, { id: '30', label: '30 days', days: 30 }, { id: 'all', label: 'All', days: 0 }] as const
const ZONES = {
  safe: { label: 'Safe', icon: ShieldCheck, color: 'var(--ok)', text: 'Fine to accept.' },
  check: { label: 'Check', icon: ShieldQuestion, color: 'var(--warn)', text: 'Confirm the money first.' },
  fraud: { label: 'Fraud', icon: ShieldX, color: 'var(--bad)', text: 'Do not hand over goods.' },
} as const
const day0 = (iso: string) => new Date(iso.slice(0, 10) + 'T00:00:00')
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function Card({ id, n, active, onClick }: { id: keyof typeof ZONES; n: number; active: boolean; onClick: () => void }) {
  const z = ZONES[id]
  const Icon: LucideIcon = z.icon
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={`card card-link p-4 text-left ${active ? 'ring-2 ring-brand' : ''}`}>
      <div className="flex items-center gap-2 text-sm text-muted"><span style={{ color: z.color }}><Icon size={18} aria-hidden /></span> {z.label}</div>
      <div className="num mt-1 text-3xl font-bold tracking-tight">{n.toLocaleString('en-IN')}</div>
      <p className="mt-1 text-sm text-muted">{z.text}</p>
    </button>
  )
}

/** One flagged payment: the verdict, up to 3 plain reasons, and the review buttons. */
function Item({ it, mark, onMark }: { it: RiskAlertItem; mark?: 'fraud' | 'fine'; onMark: (l: 'fraud' | 'fine' | null) => void }) {
  const z = it.level === 'high' ? ZONES.fraud : ZONES.check
  const btn = (l: 'fraud' | 'fine', text: string, Icon: LucideIcon) => (
    <button type="button" aria-pressed={mark === l} onClick={() => onMark(mark === l ? null : l)} className={`btn !min-h-9 !px-3 text-sm ${mark === l ? 'btn-primary' : 'btn-ghost'}`}><Icon size={15} aria-hidden /> {text}</button>
  )
  return (
    <li className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="inline-flex items-center gap-1.5 font-semibold"><span className="size-2.5 rounded-full" style={{ background: z.color }} aria-hidden />{z.label}</span>
        <b className="num text-lg">{rupees0(it.amount_paise)}</b>
        {it.chance != null && <span className="text-sm text-muted">{it.chance >= 0.995 ? '>99' : Math.round(it.chance * 100)}% fraud chance</span>}
        <span className="text-sm text-muted">{dtFmt(it.ts)} · {branchName(it.outlet)}</span>
        <span className="ml-auto font-mono text-xs text-muted">{it.tid}</span>
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-sm">{it.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <div className="flex flex-wrap items-center gap-2">
        {btn('fraud', 'Fraud', ShieldAlert)}
        {btn('fine', 'Fine', ThumbsUp)}
        {mark && <span className="inline-flex items-center gap-1 text-xs text-muted"><CircleCheck size={13} aria-hidden /> Saved for the next retrain</span>}
        <Link to={fraudLink(it.fraud_inputs)} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Open in Fraud check <ArrowRight size={14} /></Link>
      </div>
    </li>
  )
}

/** Risk alerts: Safe / Check / Fraud counts and the queue of flagged payments to review. */
export default function RiskPage() {
  const { ds, meta } = useBizCtx()
  const [preset, setPreset] = useState<(typeof PRESETS)[number]['id']>('30')
  const [zone, setZone] = useState<'check' | 'fraud' | ''>('')
  const [page, setPage] = useState(1)
  const [marks, setMarks] = useState<Record<string, 'fraud' | 'fine'>>({})
  useEffect(() => { bizApi.labels(ds).then(setMarks).catch(() => setMarks({})) }, [ds])

  const p = PRESETS.find((x) => x.id === preset)!
  const to = meta?.data_end.slice(0, 10)
  const from = meta && p.days ? iso(new Date(day0(meta.data_end).getTime() - (p.days - 1) * 86_400_000)) : meta?.data_start.slice(0, 10)
  const { data, error } = useBiz(() => bizApi.riskAlerts(ds, { date_from: from, date_to: to, level: zone === 'fraud' ? 'high' : zone === 'check' ? 'medium' : undefined, page, page_size: 8 }), `risk-${ds}-${from}-${to}-${zone}-${page}`)
  const counts = useBiz(() => bizApi.riskAlerts(ds, { date_from: from, date_to: to, page_size: 1 }), `riskc-${ds}-${from}-${to}`).data

  const mark = (tid: string, l: 'fraud' | 'fine' | null) => {
    setMarks((m) => { const n = { ...m }; l ? (n[tid] = l) : delete n[tid]; return n })
    bizApi.setLabel(ds, tid, l).then(setMarks).catch(() => undefined)
  }
  const z = counts?.zones
  const reviewed = Object.keys(marks).length

  return (
    <div className="space-y-6">
      <PageHeader
        title="Risk alerts"
        answer={z ? <><b className="num">{(z.check + z.fraud).toLocaleString('en-IN')}</b> payments need a look. <b className="num">{z.fraud.toLocaleString('en-IN')}</b> look like fraud.</> : 'Loading…'}
        action={<div className="seg !p-0.5 !rounded-lg" role="group" aria-label="Period">{PRESETS.map((x) => <button key={x.id} aria-pressed={preset === x.id} onClick={() => { setPreset(x.id); setPage(1) }} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md">{x.label}</button>)}</div>}
      />

      <section aria-label="Zones" className="grid gap-4 sm:grid-cols-3">
        <Link to="/transactions?tab=received" className="card card-link p-4">
          <div className="flex items-center gap-2 text-sm text-muted"><span style={{ color: ZONES.safe.color }}><ShieldCheck size={18} aria-hidden /></span> Safe</div>
          <div className="num mt-1 text-3xl font-bold tracking-tight">{z ? z.safe.toLocaleString('en-IN') : '…'}</div>
          <p className="mt-1 text-sm text-muted">Fine to accept. See payments →</p>
        </Link>
        <Card id="check" n={z?.check ?? 0} active={zone === 'check'} onClick={() => { setZone(zone === 'check' ? '' : 'check'); setPage(1) }} />
        <Card id="fraud" n={z?.fraud ?? 0} active={zone === 'fraud'} onClick={() => { setZone(zone === 'fraud' ? '' : 'fraud'); setPage(1) }} />
      </section>

      <section className="card" aria-labelledby="queue">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-4">
          <h2 id="queue" className="text-lg font-semibold">Review queue <Tip text="Mark each payment Fraud or Fine. Your marks are saved and used when the model is retrained." /></h2>
          <span className="text-sm text-muted">{reviewed.toLocaleString('en-IN')} reviewed</span>
        </div>
        {error ? <p className="p-4 text-sm text-bad">{error}</p> : data && data.items.length === 0 ? (
          <EmptyState icon={ShieldCheck} title="Nothing to review." sub="No payments were flagged in this period." />
        ) : (
          <ul className="divide-y divide-line">
            {data?.items.map((it) => <Item key={it.tid} it={it} mark={marks[it.tid]} onMark={(l) => mark(it.tid, l)} />)}
          </ul>
        )}
        {data && <div className="px-4 pb-4"><Pager page={page} pages={Math.ceil(data.total / data.page_size)} total={data.total} onChange={setPage} /></div>}
      </section>

      <Link to="/actions" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: Action center <ArrowRight size={14} /></Link>
    </div>
  )
}
