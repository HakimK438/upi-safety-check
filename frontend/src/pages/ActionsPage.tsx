import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BookOpenCheck, Copy, FileWarning, Hourglass, PackageX, ReceiptText, ShieldAlert, ShieldQuestion, Undo2, Undo, CircleCheck, type LucideIcon } from 'lucide-react'
import { rupees0, useBiz } from '../lib/biz'
import { bizApi } from '../lib/bizApi'
import { useBizCtx } from '../lib/bizctx'
import { EmptyState, PageHeader } from '../components/shell'

interface Item {
  id: string
  icon: LucideIcon
  line: string
  paise: number
  to: string
  button: string
  urgent: boolean
}

// One plain sentence per kind of finding, and the page that shows the records behind it.
const KINDS: Record<string, { icon: LucideIcon; text: (n: number) => string; to: string; button: string }> = {
  pending_payment: { icon: Hourglass, text: (n) => `${n} payments paid but not in the bank`, to: '/transactions?tab=not_received', button: 'Payments' },
  order_without_payment: { icon: PackageX, text: (n) => `${n} orders with no payment`, to: '/transactions?tab=not_received', button: 'Payments' },
  settlement_shortfall: { icon: BookOpenCheck, text: (n) => `Bank paid less than sales on ${n} days`, to: '/ledger', button: 'Bank record' },
  settlement_excess: { icon: BookOpenCheck, text: (n) => `Bank paid more than sales on ${n} days`, to: '/ledger', button: 'Bank record' },
  duplicate_payment: { icon: Copy, text: (n) => `${n} orders paid twice`, to: '/transactions', button: 'Payments' },
  possible_duplicate_payment: { icon: Copy, text: (n) => `${n} payments that may be doubles`, to: '/transactions', button: 'Payments' },
  duplicate_reference: { icon: Copy, text: (n) => `${n} bank references recorded twice`, to: '/transactions', button: 'Payments' },
  amount_mismatch: { icon: FileWarning, text: (n) => `${n} payments that differ from the order amount`, to: '/transactions?tab=received', button: 'Payments' },
  payment_without_order: { icon: ReceiptText, text: (n) => `${n} payments with no order`, to: '/transactions?tab=received', button: 'Payments' },
  ambiguous_match: { icon: ReceiptText, text: (n) => `${n} payments that fit more than one order`, to: '/transactions', button: 'Payments' },
  refund_review: { icon: Undo2, text: (n) => `${n} refunds to double-check`, to: '/transactions?tab=refunded', button: 'Payments' },
  reversal_review: { icon: Undo, text: (n) => `${n} reversed payments`, to: '/transactions', button: 'Payments' },
}
const DONE_KEY = (ds: string) => `actions-done:${ds}`

function Row({ it, done, onToggle }: { it: Item; done: boolean; onToggle: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-sunken text-muted"><it.icon size={20} aria-hidden /></span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 font-medium">
          {!done && <span className="size-2 shrink-0 rounded-full" style={{ background: 'var(--warn)' }} aria-hidden />}
          <span className={done ? 'text-muted line-through' : ''}>{it.line}</span>
        </div>
        {it.paise > 0 && <div className="num text-sm text-muted">{rupees0(it.paise)}</div>}
      </div>
      <button type="button" onClick={onToggle} className="text-sm text-muted hover:text-ink hover:underline">{done ? 'Undo' : 'Mark done'}</button>
      {!done && <Link to={it.to} className="btn btn-ghost !min-h-9 !px-3 text-sm">{it.button} <ArrowRight size={14} aria-hidden /></Link>}
    </li>
  )
}

/** Action center: what to do now, what can wait a week, and what is done. */
export default function ActionsPage() {
  const { ds } = useBizCtx()
  const recon = useBiz(() => bizApi.recon(ds, { page_size: 1 }), `act-recon-${ds}`).data
  const risk = useBiz(() => bizApi.riskAlerts(ds, { page_size: 1 }), `act-risk-${ds}`).data
  const [done, setDone] = useState<Record<string, true>>({})
  useEffect(() => {
    try {
      setDone(JSON.parse(localStorage.getItem(DONE_KEY(ds)) ?? '{}'))
    } catch {
      setDone({})
    }
  }, [ds])
  const toggle = (id: string) =>
    setDone((d) => {
      const n = { ...d }
      n[id] ? delete n[id] : (n[id] = true)
      try {
        localStorage.setItem(DONE_KEY(ds), JSON.stringify(n))
      } catch {
        /* storage can be blocked */
      }
      return n
    })

  const items = useMemo<Item[]>(() => {
    if (!recon || !risk) return []
    const out: Item[] = []
    if (risk.zones.fraud) out.push({ id: 'risk-fraud', icon: ShieldAlert, line: `${risk.zones.fraud.toLocaleString('en-IN')} payments look like fraud`, paise: 0, to: '/risk', button: 'Risk alerts', urgent: true })
    if (risk.zones.check) out.push({ id: 'risk-check', icon: ShieldQuestion, line: `${risk.zones.check.toLocaleString('en-IN')} payments to check first`, paise: 0, to: '/risk', button: 'Risk alerts', urgent: false })
    for (const [type, s] of Object.entries(recon.summary)) {
      const k = KINDS[type]
      if (k && s.count) out.push({ id: type, icon: k.icon, line: k.text(s.count), paise: s.amount_at_stake_paise, to: k.to, button: k.button, urgent: ['pending_payment', 'order_without_payment', 'settlement_shortfall', 'duplicate_payment'].includes(type) })
    }
    return out.sort((a, b) => b.paise - a.paise)
  }, [recon, risk])

  const open = items.filter((i) => !done[i.id])
  const now = open.filter((i) => i.urgent)
  const week = open.filter((i) => !i.urgent)
  const finished = items.filter((i) => done[i.id])

  const List = ({ title, list, empty, isDone = false }: { title: string; list: Item[]; empty: string; isDone?: boolean }) => (
    <section className="card" aria-labelledby={title}>
      <h2 id={title} className="flex items-center justify-between border-b border-line p-4 text-lg font-semibold">{title}<span className="num text-sm font-normal text-muted">{list.length}</span></h2>
      {list.length === 0 ? <p className="p-4 text-sm text-muted">{empty}</p> : <ul className="divide-y divide-line">{list.map((i) => <Row key={i.id} it={i} done={isDone} onToggle={() => toggle(i.id)} />)}</ul>}
    </section>
  )

  if (!recon || !risk) return <div className="space-y-4"><div className="skeleton h-16" /><div className="skeleton h-56" /><div className="skeleton h-56" /></div>
  if (items.length === 0) return <EmptyState icon={CircleCheck} title="Nothing to do." sub="Your records agree and no payment was flagged." />

  return (
    <div className="space-y-6">
      <PageHeader title="Action center" answer={now.length ? <><b className="num">{now.length}</b> things need you now, <b className="num">{week.length}</b> can wait this week.</> : 'Nothing urgent. A few things can wait this week.'} />
      <List title="Do now" list={now} empty="Nothing urgent." />
      <List title="This week" list={week} empty="Nothing waiting." />
      <List title="Done" list={finished} empty="Items you mark done show here." isDone />
      <Link to="/data" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: My data <ArrowRight size={14} /></Link>
    </div>
  )
}
