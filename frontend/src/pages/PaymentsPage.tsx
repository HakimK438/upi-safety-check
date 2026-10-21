import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, ChevronRight, Download, ReceiptText, Search, ShieldCheck, X } from 'lucide-react'
import { rupees0, useBiz } from '../lib/biz'
import { bizApi, branchName, dtFmt, fraudLink, type TxnDetail, type TxnRow } from '../lib/bizApi'
import { useBizCtx } from '../lib/bizctx'
import { Pager } from '../components/bizui'
import { EmptyState, PageHeader, StatusChip, Tip, type Status } from '../components/shell'

const TABS = [
  { id: 'all', label: 'All', tip: 'Every payment in the period.' },
  { id: 'received', label: 'Received', tip: 'Payments marked successful.' },
  { id: 'refunded', label: 'Refunded', tip: 'Payments you gave money back for.' },
  { id: 'not_received', label: 'Not received', tip: 'Payments that failed or are still pending.' },
  { id: 'risky', label: 'Risky', tip: 'Payments the fraud model marked Check or Fraud.' },
] as const
type TabId = (typeof TABS)[number]['id']
const STATUS: Record<string, { label: string; tone: Status }> = {
  success: { label: 'Received', tone: 'ok' }, failed: { label: 'Failed', tone: 'bad' }, pending: { label: 'Pending', tone: 'warn' }, reversed: { label: 'Reversed', tone: 'neutral' },
}
const RISK = { high: { label: 'Fraud', color: 'var(--bad)' }, medium: { label: 'Check', color: 'var(--warn)' } } as const

function RiskDot({ level }: { level: TxnRow['risk_level'] }) {
  if (level !== 'high' && level !== 'medium') return <span className="text-muted">Safe</span>
  return <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: RISK[level].color }} aria-hidden />{RISK[level].label}</span>
}

/** Side drawer: what this payment is, what it matched, and a plain reason if it looks risky. */
function Drawer({ tid, onClose }: { tid: string; onClose: () => void }) {
  const { ds } = useBizCtx()
  const { data: d, error } = useBiz<TxnDetail>(() => bizApi.transaction(ds, tid), `txn-${ds}-${tid}`)
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  const reasons = d?.risk?.risk_model?.reasons ?? []
  const Row = ({ k, v }: { k: string; v: React.ReactNode }) => <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-muted">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Payment details">
      <button className="absolute inset-0 bg-black/30" aria-label="Close" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 w-full max-w-md overflow-y-auto bg-surface p-5 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div><h2 className="text-lg font-semibold">Payment details</h2><p className="font-mono text-xs text-muted break-all">{tid}</p></div>
          <button className="grid size-9 place-items-center rounded-full hover:bg-sunken" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </div>
        {error && <p className="text-sm text-bad">{error}</p>}
        {!d && !error && <div className="space-y-3"><div className="skeleton h-24" /><div className="skeleton h-40" /></div>}
        {d && (
          <>
            <div className="mb-1 flex items-center gap-3"><b className="text-3xl num">{rupees0(d.amount_paise)}</b><StatusChip status={STATUS[d.status].tone}>{STATUS[d.status].label}</StatusChip></div>
            <dl className="divide-y divide-line">
              <Row k="When" v={dtFmt(d.ts)} />
              <Row k="Branch" v={branchName(d.outlet)} />
              <Row k="Customer" v={d.payer ?? 'Not given'} />
              <Row k="Risk" v={<RiskDot level={d.risk_level} />} />
            </dl>
            <h3 className="mt-5 mb-1 text-sm font-semibold">Matched records</h3>
            <dl className="divide-y divide-line">
              <Row k="Order" v={d.order ? `${d.order.order_id} · ${rupees0(d.order.amount_paise)}` : 'No order found'} />
              <Row k="Refund" v={d.refunds.length ? d.refunds.map((r) => rupees0(r.amount_paise)).join(', ') : 'None'} />
              {d.same_order_payments.length > 0 && <Row k="Other payments for the order" v={d.same_order_payments.length} />}
            </dl>
            {(reasons.length > 0 && (d.risk_level === 'high' || d.risk_level === 'medium')) && (
              <div className="mt-5 rounded-xl bg-sunken p-3">
                <h3 className="mb-1 text-sm font-semibold">Why it looks risky</h3>
                <ul className="list-disc space-y-1 pl-5 text-sm">{reasons.slice(0, 3).map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            )}
            {d.discrepancy_items.length > 0 && (
              <div className="mt-4 rounded-xl bg-sunken p-3 text-sm"><h3 className="mb-1 font-semibold">Records that do not agree</h3>
                <ul className="space-y-1">{d.discrepancy_items.slice(0, 3).map((x) => <li key={x.id}>{x.title}</li>)}</ul>
                <Link className="mt-2 inline-flex items-center gap-1 font-medium text-brand hover:underline" to="/reconciliation">See missing money <ArrowRight size={14} /></Link>
              </div>
            )}
            <Link to={fraudLink(d.fraud_inputs)} className="btn btn-primary mt-6 w-full"><ShieldCheck size={18} /> Check for fraud</Link>
          </>
        )}
      </aside>
    </div>
  )
}

export default function PaymentsPage() {
  const { ds, meta } = useBizCtx()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.id === params.get('tab'))?.id ?? 'all') as TabId
  const [q, setQ] = useState(params.get('q') ?? '')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<string | null>(null)
  const from = params.get('date_from') ?? ''
  const to = params.get('date_to') ?? ''
  const branch = params.get('branch') ?? ''
  const patch = (o: Record<string, string>) => {
    const n = new URLSearchParams(params)
    for (const [k, v] of Object.entries(o)) v ? n.set(k, v) : n.delete(k)
    setParams(n, { replace: true })
    setPage(1)
  }
  const scope = { date_from: from, date_to: to, outlet: branch, q }

  // counts for the five tabs, under the same filters
  const counts = useBiz(async () => {
    const r = await Promise.all(TABS.map((t) => bizApi.transactions(ds, { ...scope, tab: t.id, page_size: 1 })))
    return Object.fromEntries(TABS.map((t, i) => [t.id, r[i]])) as Record<TabId, Awaited<ReturnType<typeof bizApi.transactions>>>
  }, `pay-counts-${ds}-${from}-${to}-${branch}-${q}`).data
  const { data, loading, error } = useBiz(() => bizApi.transactions(ds, { ...scope, tab, page, page_size: 12 }), `pay-${ds}-${tab}-${from}-${to}-${branch}-${q}-${page}`)
  const n = (id: TabId) => (counts ? counts[id].total.toLocaleString('en-IN') : '…')
  const risky = counts?.risky.total ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="Payments"
        answer={counts ? <><b className="num">{counts.all.total.toLocaleString('en-IN')}</b> payments, <b className="num">{rupees0(counts.all.sum_amount_paise)}</b>. <b className="num">{risky.toLocaleString('en-IN')}</b> look risky.</> : 'Loading your payments…'}
        action={<a className="btn btn-ghost !min-h-10 text-sm" href={bizApi.paymentsCsv(ds, { ...scope, tab })} download><Download size={16} /> Export CSV</a>}
      />

      <section className="card p-4 space-y-4" aria-label="Payments">
        <div className="flex flex-wrap items-center gap-3">
          <div className="seg !p-0.5 !rounded-lg max-w-full overflow-x-auto" role="tablist" aria-label="Payment view">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => patch({ tab: t.id })} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md whitespace-nowrap">
                {t.label} <span className="num opacity-70">{n(t.id)}</span>
              </button>
            ))}
          </div>
          <Tip text={TABS.find((t) => t.id === tab)!.tip} />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <label className="relative min-w-[12rem] flex-1 max-w-xs">
            <span className="sr-only">Search by bank reference</span>
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <input className="field !pl-9 !min-h-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Search bank reference (UTR)" maxLength={60} />
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">From<input type="date" className="field !py-1 !px-2 !w-auto !text-sm" value={from} onChange={(e) => patch({ date_from: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm text-muted">To<input type="date" className="field !py-1 !px-2 !w-auto !text-sm" value={to} onChange={(e) => patch({ date_to: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm text-muted">Branch
            <select className="field !py-1 !px-2 !w-auto !text-sm" value={branch} onChange={(e) => patch({ branch: e.target.value })}>
              <option value="">All</option>
              {(meta?.outlets ?? []).map((b) => <option key={b} value={b}>{branchName(b)}</option>)}
            </select>
          </label>
          {(from || to || branch || q) && <button className="text-sm font-medium text-brand hover:underline" onClick={() => { setQ(''); patch({ date_from: '', date_to: '', branch: '' }) }}>Clear</button>}
        </div>

        {error ? <p className="text-sm text-bad">{error}</p> : data && data.rows.length === 0 ? (
          <EmptyState icon={ReceiptText} title="No payments match." sub="Try another tab or clear the filters." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line" style={{ opacity: loading ? 0.6 : 1 }}>
            <table className="w-full text-sm">
              <thead className="bg-sunken text-left text-muted"><tr>
                <th className="p-2.5 font-medium">Bank reference (UTR)</th><th className="hidden p-2.5 font-medium md:table-cell">When</th><th className="p-2.5 text-right font-medium">Amount</th>
                <th className="p-2.5 font-medium">Status</th><th className="hidden p-2.5 font-medium sm:table-cell">Risk</th><th className="w-8 p-2.5"><span className="sr-only">Open</span></th>
              </tr></thead>
              <tbody className="divide-y divide-line">
                {data?.rows.map((r) => (
                  <tr key={r.tid} tabIndex={0} className="cursor-pointer outline-none hover:bg-sunken focus:bg-sunken" onClick={() => setOpen(r.tid)} onKeyDown={(e) => e.key === 'Enter' && setOpen(r.tid)}>
                    <td className="p-2.5"><div className="font-mono text-xs">{r.tid}</div><div className="text-xs text-muted">{branchName(r.outlet)}{r.payer ? ` · ${r.payer}` : ''}</div></td>
                    <td className="hidden whitespace-nowrap p-2.5 md:table-cell">{dtFmt(r.ts)}</td>
                    <td className="num p-2.5 text-right font-medium">{rupees0(r.amount_paise)}</td>
                    <td className="p-2.5"><StatusChip status={STATUS[r.status].tone}>{STATUS[r.status].label}</StatusChip></td>
                    <td className="hidden p-2.5 sm:table-cell"><RiskDot level={r.risk_level} /></td>
                    <td className="p-2.5 text-muted"><ChevronRight size={16} aria-hidden /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager page={page} pages={Math.ceil(data.total / data.page_size)} total={data.total} onChange={setPage} />}
      </section>

      <Link to="/reconciliation" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: Missing money <ArrowRight size={14} /></Link>
      {open && <Drawer tid={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
