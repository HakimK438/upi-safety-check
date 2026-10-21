import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, CircleCheck, CircleX, Clock, FileSearch, Keyboard, PlusCircle, ScanSearch, ShieldCheck, Sparkles } from 'lucide-react'
import { rupees0 } from '../lib/biz'
import { bizApi, branchName, dtFmt, fraudLink, type TxnDetail } from '../lib/bizApi'
import { isUtr, useAddedPayments } from '../lib/bankLocal'
import { useBizCtx } from '../lib/bizctx'
import { PageHeader, Tip } from '../components/shell'

type Kind = 'match' | 'differs' | 'status' | 'missing'
type Found = { kind: Kind; amount?: number; detail?: TxnDetail; added?: { date: string; customer: string } }
interface Recent { utr: string; amount: number; kind: Kind }

const RECENT_KEY = 'recent-checks'
const readRecent = (): Recent[] => {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
  } catch {
    return []
  }
}
const KIND_LABEL: Record<Kind, string> = { match: 'Amount matches', differs: 'Amount differs', status: 'Not received', missing: 'Not found' }

const STEPS = [
  { icon: Keyboard, title: 'Type two things', text: 'The 12-digit bank reference (UTR) and the amount the customer says they paid.' },
  { icon: FileSearch, title: 'We look in your records', text: 'Your bank record and your payments are searched for that exact reference.' },
  { icon: ShieldCheck, title: 'You get one clear answer', text: 'Found and matching, found but different, or not found. Then check it for fraud.' },
] as const
const MEANINGS = [
  { color: 'var(--ok)', icon: CircleCheck, title: 'Found, amount matches', text: 'The money is in your records. You can hand over the goods.' },
  { color: 'var(--warn)', icon: CircleAlert, title: 'Found, but different', text: 'The reference exists but the amount or status is off. Ask the customer to show their screen.' },
  { color: 'var(--bad)', icon: CircleX, title: 'Not found', text: 'Nothing arrived under this reference. Wait a few minutes, or ask for another way to pay.' },
] as const

/** Check one payment: two fields, one button, one of three plain answers. */
export default function CheckPage() {
  const { ds } = useBizCtx()
  const added = useAddedPayments(ds)
  const [utr, setUtr] = useState('')
  const [amount, setAmount] = useState('')
  const [res, setRes] = useState<{ utr: string; amount: number; r: Found } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [recent, setRecent] = useState<Recent[]>(readRecent)
  const [samples, setSamples] = useState<{ utr: string; amount: number }[]>([])
  const ok = isUtr(utr) && Number(amount) > 0

  useEffect(() => {
    bizApi
      .transactions(ds, { tab: 'received', page_size: 2 })
      .then((p) => setSamples(p.rows.map((r) => ({ utr: r.tid, amount: Math.round(r.amount_paise / 100) }))))
      .catch(() => setSamples([]))
  }, [ds])

  const remember = (r: Recent) => {
    const next = [r, ...recent.filter((x) => x.utr !== r.utr)].slice(0, 5)
    setRecent(next)
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(next))
    } catch {
      /* storage can be blocked */
    }
  }
  const examples = [
    ...(samples[0] ? [{ label: 'A payment that arrived', utr: samples[0].utr, amount: samples[0].amount }] : []),
    ...(samples[1] ? [{ label: 'Wrong amount', utr: samples[1].utr, amount: samples[1].amount + 500 }] : []),
    { label: 'Not in records', utr: '999999999999', amount: 1500 },
  ]
  const fill = (u: string, a: number) => { setUtr(u); setAmount(String(a)); setRes(null) }

  async function check(e: React.FormEvent) {
    e.preventDefault()
    if (!ok) return
    setBusy(true)
    setErr('')
    const want = Number(amount)
    const id = utr.trim()
    try {
      const mine = added.items.find((p) => p.utr === id)
      if (mine) {
        const k: Kind = Math.abs(mine.amount - want) < 0.5 ? 'match' : 'differs'
        setRes({ utr: id, amount: want, r: { kind: k, amount: mine.amount, added: { date: mine.date, customer: mine.customer } } })
        remember({ utr: id, amount: want, kind: k })
        return
      }
      const page = await bizApi.transactions(ds, { q: id, page_size: 5 })
      const hit = page.rows.find((r) => r.tid === id)
      if (!hit) {
        setRes({ utr: id, amount: want, r: { kind: 'missing' } })
        remember({ utr: id, amount: want, kind: 'missing' })
        return
      }
      const detail = await bizApi.transaction(ds, hit.tid)
      const have = hit.amount_paise / 100
      const kind: Kind = hit.status !== 'success' ? 'status' : Math.abs(have - want) < 0.5 ? 'match' : 'differs'
      setRes({ utr: id, amount: want, r: { kind, amount: have, detail } })
      remember({ utr: id, amount: want, kind })
    } catch (x) {
      setErr((x as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const d = res?.r.detail
  const kind = res?.r.kind
  const tone = kind === 'match' ? 'var(--ok)' : kind === 'missing' ? 'var(--bad)' : 'var(--warn)'
  const Icon = kind === 'match' ? CircleCheck : kind === 'missing' ? CircleX : CircleAlert
  const title = kind ? { match: 'Found, amount matches', differs: 'Found, but the amount differs', status: `Found, but the payment is ${d?.status ?? 'not received'}`, missing: 'Not found in your records' }[kind] : ''

  return (
    <div className="space-y-6">
      <PageHeader title="Check a payment" answer="Did this customer's money really arrive? Type the bank reference and the amount." />

      <ol className="grid gap-3 md:grid-cols-3" aria-label="How it works">
        {STEPS.map((st, i) => (
          <li key={st.title} className="card flex gap-3 p-4">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><st.icon size={20} aria-hidden /></span>
            <div><div className="font-semibold"><span className="num text-muted">{i + 1}.</span> {st.title}</div><p className="mt-0.5 text-sm text-muted">{st.text}</p></div>
          </li>
        ))}
      </ol>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-6">
          <form onSubmit={check} className="card space-y-4 p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="inline-flex items-center gap-1 text-muted"><Sparkles size={14} aria-hidden /> Try one:</span>
              {examples.map((x) => (
                <button key={x.label} type="button" className="rounded-full border border-line px-3 py-1.5 hover:bg-brand-soft" onClick={() => fill(x.utr, x.amount)}>{x.label}</button>
              ))}
            </div>
            <label className="block">
              <span className="mb-1.5 flex items-center gap-1.5 font-medium">Bank reference (UTR) <Tip text="The 12-digit number on the customer's payment screen or in your bank message." /></span>
              <input className="field font-mono tracking-wider" inputMode="numeric" autoComplete="off" value={utr} maxLength={12} onChange={(e) => setUtr(e.target.value.replace(/\D/g, ''))} placeholder="12 digits" aria-invalid={utr.length > 0 && !isUtr(utr)} />
              {utr.length > 0 && !isUtr(utr) && <span className="mt-1 block text-xs text-muted">{12 - utr.length} more digits</span>}
            </label>
            <label className="block">
              <span className="mb-1.5 block font-medium">Amount (₹)</span>
              <input className="field num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} placeholder="e.g. 1500" />
            </label>
            <button className="btn btn-primary w-full !min-h-14 text-lg" disabled={!ok || busy}><ScanSearch size={20} /> {busy ? 'Checking…' : 'Check'}</button>
            {err && <p className="text-sm text-bad">{err}</p>}
          </form>

          {res && (
            <section className="card p-5 md:p-6" aria-live="polite">
              <div className="flex items-center gap-3">
                <span className="grid size-11 shrink-0 place-items-center rounded-full text-white" style={{ background: tone }}><Icon size={24} aria-hidden /></span>
                <h2 className="text-xl font-bold">{title}</h2>
              </div>
              {kind === 'differs' && <p className="mt-3">You typed <b className="num">{rupees0(res.amount * 100)}</b>. Your records show <b className="num">{rupees0((res.r.amount ?? 0) * 100)}</b>.</p>}
              {kind === 'missing' && <p className="mt-3 text-muted">No payment with this reference is in your records yet. Ask the customer to wait a few minutes, or add it yourself if you saw the money in your bank.</p>}
              {d && (
                <dl className="mt-4 divide-y divide-line text-sm">
                  <div className="flex justify-between py-2"><dt className="text-muted">Customer</dt><dd className="font-medium">{d.payer ?? 'Not given'}</dd></div>
                  <div className="flex justify-between py-2"><dt className="text-muted">Time</dt><dd className="font-medium">{dtFmt(d.ts)}</dd></div>
                  <div className="flex justify-between py-2"><dt className="text-muted">Branch</dt><dd className="font-medium">{branchName(d.outlet)}</dd></div>
                </dl>
              )}
              {res.r.added && <p className="mt-3 text-sm text-muted">Added by you on {res.r.added.date}{res.r.added.customer ? ` · ${res.r.added.customer}` : ''}.</p>}
              <div className="mt-5 flex flex-wrap gap-3">
                {d && <Link to={fraudLink(d.fraud_inputs)} className="btn btn-primary"><ShieldCheck size={18} /> Check for fraud</Link>}
                {!res.r.added && <Link to={`/ledger?add=1&utr=${res.utr}&amount=${res.amount}`} className="btn btn-ghost"><PlusCircle size={18} /> Add this payment</Link>}
              </div>
            </section>
          )}
        </div>

        <aside className="space-y-4" aria-label="Help">
          <section className="card p-4">
            <h2 className="mb-3 font-semibold">What the answers mean</h2>
            <ul className="space-y-3">
              {MEANINGS.map((m) => (
                <li key={m.title} className="flex gap-3"><span className="mt-0.5 shrink-0" style={{ color: m.color }}><m.icon size={20} aria-hidden /></span><div><div className="text-sm font-medium">{m.title}</div><p className="text-sm text-muted">{m.text}</p></div></li>
              ))}
            </ul>
          </section>
          <section className="card p-4">
            <h2 className="mb-3 flex items-center gap-1.5 font-semibold"><Clock size={16} aria-hidden /> Recent checks</h2>
            {recent.length === 0 ? <p className="text-sm text-muted">Your last 5 checks will show here.</p> : (
              <ul className="divide-y divide-line">
                {recent.map((r) => (
                  <li key={r.utr}>
                    <button type="button" className="flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:text-brand" onClick={() => fill(r.utr, r.amount)}>
                      <span><span className="block font-mono text-xs">{r.utr}</span><span className="text-muted">{KIND_LABEL[r.kind]}</span></span><b className="num">{rupees0(r.amount * 100)}</b>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <Link to="/ledger" className="inline-block text-sm font-medium text-brand hover:underline">Next: Bank record →</Link>
        </aside>
      </div>
    </div>
  )
}
