import { Link } from 'react-router-dom'
import { ArrowRight, CircleAlert, Hourglass, Landmark, PackageX, Undo2, type LucideIcon } from 'lucide-react'
import { rupees0, useBiz } from '../lib/biz'
import { bizApi } from '../lib/bizApi'
import { useBizCtx } from '../lib/bizctx'
import { ChartCard, EmptyState, PageHeader, Waterfall } from '../components/shell'

interface Cause {
  icon: LucideIcon
  title: string
  hint: string
  count: number
  paise: number
  to: string
}

/** Where the money went missing: one waterfall and four plain causes, each linking to the records behind it. */
export default function MissingMoneyPage() {
  const { ds, meta } = useBizCtx()
  const from = meta?.data_start.slice(0, 10)
  const to = meta?.data_end.slice(0, 10)
  const dash = useBiz(() => bizApi.dashboard(ds, { date_from: from, date_to: to }), `missing-${ds}-${from}-${to}`)
  const recon = useBiz(() => bizApi.recon(ds, { page_size: 1 }), `missing-recon-${ds}`)

  if (dash.error || recon.error) return <EmptyState icon={CircleAlert} title="This page could not load." sub={dash.error ?? recon.error ?? ''} />
  if (!dash.data || !recon.data || !meta) return <div className="space-y-4"><div className="skeleton h-16" /><div className="skeleton h-80" /><div className="skeleton h-64" /></div>

  const r = dash.data
  const sum = recon.data.summary
  const by = (k: string) => ({ count: sum[k]?.count ?? 0, paise: sum[k]?.amount_at_stake_paise ?? 0 })
  const causes: Cause[] = [
    { icon: Hourglass, title: 'Paid but not in the bank', hint: 'The customer paid, but it is still pending.', ...by('pending_payment'), to: '/transactions?tab=not_received' },
    { icon: Undo2, title: 'Refunded', hint: 'Money you gave back to customers.', count: meta.counts.refunds, paise: r.kpis.refunded.value, to: '/transactions?tab=refunded' },
    { icon: PackageX, title: 'Order with no payment', hint: 'An order was placed, but no payment arrived.', ...by('order_without_payment'), to: '/transactions?tab=not_received' },
    { icon: Landmark, title: 'Settlement lower than sales', hint: 'The bank paid you less than the day sales.', ...by('settlement_shortfall'), to: '/ledger' },
  ]
  const missing = r.kpis.not_received.value
  const w = r.waterfall

  return (
    <div className="space-y-6">
      <PageHeader title="Missing money" answer={missing > 0 ? <><b className="num">{rupees0(missing)}</b> of your sales did not reach the bank.</> : 'All your sales reached the bank.'} />

      <ChartCard
        title={`Of ${rupees0(w.sales)} in sales, ${rupees0(w.in_bank)} reached your bank.`}
        tip="Sales, minus refunds, minus money not received, plus other differences, equals money in your bank."
        alt={`Sales ${rupees0(w.sales)}, refunds ${rupees0(w.refunded)}, not received ${rupees0(w.not_received)}, other differences ${rupees0(w.other)}, in your bank ${rupees0(w.in_bank)}.`}
      >
        <Waterfall w={w} />
      </ChartCard>

      <section aria-label="Causes" className="card divide-y divide-line">
        {causes.map((c) => (
          <div key={c.title} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-sunken text-muted"><c.icon size={20} aria-hidden /></span>
            <div className="min-w-0 flex-1"><div className="font-semibold">{c.title}</div><p className="text-sm text-muted">{c.hint}</p></div>
            <div className="text-right"><div className="num text-lg font-bold">{rupees0(c.paise)}</div><div className="num text-sm text-muted">{c.count.toLocaleString('en-IN')} {c.count === 1 ? 'item' : 'items'}</div></div>
            <Link to={c.to} className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">See payments <ArrowRight size={14} /></Link>
          </div>
        ))}
      </section>

      <Link to="/risk" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: Risk alerts <ArrowRight size={14} /></Link>
    </div>
  )
}
