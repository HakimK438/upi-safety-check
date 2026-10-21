import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BookOpenCheck, CircleHelp, Database, FileSearch, GitCompareArrows, Gauge, LayoutDashboard, ListChecks, MessageSquareWarning, ReceiptText, RefreshCcw, ScanSearch, ShieldCheck, ShieldAlert, ClipboardCheck, BellRing, type LucideIcon } from 'lucide-react'
import { fraudApi, type Overview } from '../lib/fraudApi'

const FLOW: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Database, title: 'Your data', text: 'Payments, orders, refunds and bank settlements.' },
  { icon: ShieldCheck, title: 'Fraud model', text: 'Scores every payment from its warning signs.' },
  { icon: ScanSearch, title: 'Check', text: 'Safe, Check or Fraud, with the reasons.' },
  { icon: ClipboardCheck, title: 'Review', text: 'You mark flagged payments Fraud or Fine.' },
  { icon: RefreshCcw, title: 'Better model', text: 'Your marks are used at the next retrain.' },
]
const GLOSSARY: [string, string][] = [
  ['Precision', 'Of the payments we flagged, how many really were fraud. High precision means few false alarms.'],
  ['Recall', 'Of all the fraud, how many we caught. High recall means little fraud slips through.'],
  ['F1', 'One number that balances precision and recall.'],
  ['ROC curve', 'Shows how much fraud is caught as more false alarms are allowed. The higher it bends, the better.'],
  ['PR curve', 'Shows precision against recall. It matters most when fraud is rare, as it is here.'],
]
const LIMITS = [
  'The models were trained and tested on synthetic data, so the scores say nothing about real UPI fraud rates.',
  'The Dashboard sample is also synthetic. Its orders, refunds and settlements were generated, with problems planted.',
  'Fraud check judges card-style payment signals. It has not been tested on real UPI payments.',
  'A flag is a reason to look, not proof. Always confirm large amounts in your own bank app.',
  'Scam message results come from template-heavy data, so real messages may score lower.',
]
const PAGES: { to: string; icon: LucideIcon; label: string; text: string }[] = [
  { to: '/', icon: Gauge, label: 'Fraud check', text: 'Score one payment.' },
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard', text: 'Sales, bank money and risk at a glance.' },
  { to: '/check', icon: ScanSearch, label: 'Check a payment', text: 'Did the money arrive?' },
  { to: '/ledger', icon: BookOpenCheck, label: 'Bank record', text: 'Money in your bank.' },
  { to: '/transactions', icon: ReceiptText, label: 'Payments', text: 'Every payment, with filters.' },
  { to: '/reconciliation', icon: GitCompareArrows, label: 'Missing money', text: 'Where sales did not reach the bank.' },
  { to: '/risk', icon: BellRing, label: 'Risk alerts', text: 'Review flagged payments.' },
  { to: '/actions', icon: ListChecks, label: 'Action center', text: 'What to do now and this week.' },
  { to: '/data', icon: Database, label: 'My data', text: 'Add your files, explore the tables.' },
  { to: '/messages', icon: MessageSquareWarning, label: 'Scam messages', text: 'Check an SMS or WhatsApp message.' },
]
const n0 = (v: number) => v.toLocaleString('en-IN')

/** Time split drawn to scale: days 0-119 learn, 120-149 tune, 150-182 test. */
function Split({ train, val, test }: { train: number; val: number; test: number }) {
  const parts = [
    { label: 'Learn', days: 'days 0-119', w: 120, color: '#1F4FD8', text: `${n0(train)} payments (after sampling)` },
    { label: 'Tune', days: 'days 120-149', w: 30, color: '#7C5CDB', text: `${n0(val)} payments` },
    { label: 'Test', days: 'days 150-182', w: 33, color: '#0E8A7E', text: `${n0(test)} payments the models never saw` },
  ]
  return (
    <div role="img" aria-label={`Time split: learn on days 0 to 119 (${n0(train)} payments), tune on days 120 to 149, test on days 150 to 182 (${n0(test)} payments never seen).`}>
      <div className="flex h-12 overflow-hidden rounded-xl">
        {parts.map((p) => <div key={p.label} className="grid place-items-center text-sm font-semibold text-white" style={{ flex: p.w, background: p.color }}>{p.label}</div>)}
      </div>
      <div className="mt-2 flex">
        {parts.map((p) => <div key={p.label} className="pr-3 text-xs" style={{ flex: p.w }}><b className="block text-ink">{p.days}</b><span className="text-muted">{p.text}</span></div>)}
      </div>
    </div>
  )
}

export default function AboutPage() {
  const [ov, setOv] = useState<Overview | null>(null)
  useEffect(() => { fraudApi.overview().then(setOv).catch(() => setOv(null)) }, [])
  const e = ov?.ieee
  return (
    <div className="space-y-10">
      <header className="page-in max-w-3xl">
        <h1 className="text-3xl font-bold leading-tight tracking-tight md:text-4xl">How it works</h1>
        <p className="mt-2 text-base text-ink/80 md:text-lg">Your payments go in, the fraud model scores them, you review the flagged ones, and the model learns from your answers.</p>
      </header>

      <section aria-labelledby="flow">
        <h2 id="flow" className="sr-only">The flow</h2>
        <ol className="grid items-stretch gap-3 md:grid-cols-[repeat(9,auto)]">
          {FLOW.map((f, i) => (
            <Fragment key={f.title}>
              <li className="card flex gap-3 p-4 md:flex-col md:items-start md:gap-2">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><f.icon size={20} aria-hidden /></span>
                <div><div className="font-semibold"><span className="num text-muted">{i + 1}.</span> {f.title}</div><p className="mt-0.5 text-sm text-muted">{f.text}</p></div>
              </li>
              {i < FLOW.length - 1 && <li aria-hidden className="hidden place-items-center text-muted md:grid"><ArrowRight size={20} /></li>}
            </Fragment>
          ))}
        </ol>
      </section>

      <section className="card space-y-4 p-5 md:p-6" aria-labelledby="train">
        <h2 id="train" className="text-xl font-bold">How the models were trained and tested</h2>
        {e ? <Split train={e.train_rows} val={e.val_rows} test={e.test_rows} /> : <div className="skeleton h-24" />}
        <ul className="list-disc space-y-1.5 pl-5">
          <li>The models learned only from the first 120 days. They never saw the test days, so the test scores are an honest check.</li>
          <li>The split is by time, like real life: yesterday teaches the model, tomorrow tests it. Payments are never shuffled.</li>
          <li>The in-between 30 days were used to tune the cut-offs and calibrate the chances, not to judge the models.</li>
          {e && <li>Fraud is rare ({((e.base_rate_test ?? 0) * 100).toFixed(1)}% of test payments), so one cut-off cannot give both 90% precision and 90% recall. Check is the middle zone for that.</li>}
        </ul>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5 md:p-6" aria-labelledby="gloss">
          <h2 id="gloss" className="mb-3 flex items-center gap-2 text-xl font-bold"><CircleHelp size={20} aria-hidden /> Words you will see</h2>
          <dl className="divide-y divide-line">{GLOSSARY.map(([k, v]) => <div key={k} className="py-2.5"><dt className="font-semibold">{k}</dt><dd className="text-sm text-muted">{v}</dd></div>)}</dl>
        </section>
        <section className="card p-5 md:p-6" aria-labelledby="limits">
          <h2 id="limits" className="mb-3 flex items-center gap-2 text-xl font-bold"><ShieldAlert size={20} aria-hidden /> What it cannot do</h2>
          <ul className="list-disc space-y-2 pl-5 text-sm">{LIMITS.map((l) => <li key={l}>{l}</li>)}</ul>
        </section>
      </div>

      <section aria-labelledby="pages">
        <h2 id="pages" className="mb-3 flex items-center gap-2 text-xl font-bold"><FileSearch size={20} aria-hidden /> Every page</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PAGES.map((p) => (
            <li key={p.to}><Link to={p.to} className="card card-link flex h-full items-center gap-3 p-4"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-sunken text-muted"><p.icon size={20} aria-hidden /></span><span><span className="block font-semibold">{p.label}</span><span className="text-sm text-muted">{p.text}</span></span></Link></li>
          ))}
        </ul>
      </section>
    </div>
  )
}
