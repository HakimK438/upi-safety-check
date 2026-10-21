import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, MessageSquareWarning, ShieldAlert, ShieldCheck, ShieldQuestion, Loader2 } from 'lucide-react'
import { spamApi, type SpamResult, type SpamSummary } from '../lib/bizApi'
import { useBiz } from '../lib/biz'
import { AX, PageHeader, Tip, TT } from '../components/shell'

const SAMPLES = [
  'Dear SBI user, your account will be blocked today. Update KYC at http://sbi-kyc-update.top/login within 24 hours',
  'Congratulations! You won Rs 25,00,000 in the Jio Lucky Draw. Pay Rs 1,999 processing fee to claim your prize.',
  'HDFC Bank: Rs 450.00 debited from a/c XX4821 to VPA chaiwala@okaxis (UPI Ref 628451093322).',
]
// One colour per message model, the same on every chart.
const MC: Record<string, string> = { nb: '#0E8A7E', logreg: '#94A3B8', svm: '#7C5CDB' }
const VERDICT = {
  spam: { title: 'Scam', icon: ShieldAlert, color: 'var(--bad)' },
  suspicious: { title: 'Possibly a scam', icon: ShieldQuestion, color: 'var(--warn)' },
  ok: { title: 'Not a scam', icon: ShieldCheck, color: 'var(--ok)' },
} as const
const pct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`
const CH = 240
type Model = SpamSummary['models'][number]

/** Paste a message, press Check: Scam or Not a scam, with up to three reasons and what to do. */
function Checker({ out, setOut }: { out: SpamResult | null; setOut: (o: SpamResult | null) => void }) {
  const [params] = useSearchParams()
  const [text, setText] = useState(params.get('text') ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const run = () => {
    setBusy(true); setErr('')
    spamApi.predict(text).then(setOut).catch((e: Error) => setErr(e.message)).finally(() => setBusy(false))
  }
  const v = out ? VERDICT[out.verdict] : null
  const reasons = out ? [...out.flags.map((f) => f.text), ...(out.triggers.length ? [`Words that raised the alarm: ${out.triggers.slice(0, 4).join(', ')}.`] : [])].slice(0, 3) : []
  return (
    <section className="card p-5 md:p-6" aria-label="Check a message">
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim().length > 5) run() }} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Try an example:</span>
          {['Account blocked', 'Lucky draw', 'Bank debit'].map((l, i) => <button key={l} type="button" className="rounded-full border border-line px-3 py-1.5 hover:bg-brand-soft" onClick={() => { setText(SAMPLES[i]); setOut(null) }}>{l}</button>)}
        </div>
        <label className="block"><span className="mb-1.5 block font-medium">Paste the message</span>
          <textarea className="field min-h-32" value={text} maxLength={2000} onChange={(e) => { setText(e.target.value); setOut(null) }} placeholder="Paste an SMS or WhatsApp message here" /></label>
        <button className="btn btn-primary w-full !min-h-12" disabled={busy || text.trim().length < 6}>{busy ? <Loader2 size={18} className="animate-spin" /> : <MessageSquareWarning size={18} />} Check</button>
        {err && <p className="text-sm text-bad" role="alert">{err}</p>}
      </form>
      {out && v && (
        <div className="mt-5 rounded-2xl border border-line p-4" aria-live="polite">
          <div className="flex items-center gap-3"><span className="grid size-11 place-items-center rounded-full text-white" style={{ background: v.color }}><v.icon size={24} aria-hidden /></span><h2 className="text-2xl font-bold">{v.title}</h2><span className="ml-auto text-sm text-muted">{Math.round(out.probability * 100)}% scam chance</span></div>
          {reasons.length > 0 && <><h3 className="mt-4 text-sm font-semibold">Why</h3><ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{reasons.map((r) => <li key={r}>{r}</li>)}</ul></>}
          <h3 className="mt-4 text-sm font-semibold">What to do</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{out.next_steps.map((r) => <li key={r}>{r}</li>)}</ul>
          {out.verdict !== 'ok' && (
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-3 text-sm font-medium">
              <Link to="/check" className="inline-flex items-center gap-1 text-brand hover:underline">Already paid? Check the payment <ArrowRight size={14} /></Link>
              <Link to="/" className="inline-flex items-center gap-1 text-brand hover:underline">Score a payment in Fraud check <ArrowRight size={14} /></Link>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/** The words one model leans on most to call a message a scam, as bars. */
function TopWords({ m }: { m: Model }) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-sm font-semibold">Words that give scams away</figcaption>
      <div role="img" aria-label={`Top scam words for ${m.name}: ${m.top_words.map((w) => w.word).join(', ')}.`}>
        <ResponsiveContainer width="100%" height={CH}>
          <BarChart data={m.top_words.map((w) => ({ ...w, pct: Math.round(w.weight * 100) }))} layout="vertical" margin={{ left: 0, right: 36 }}>
            <XAxis {...AX} type="number" hide domain={[0, 100]} />
            <YAxis {...AX} type="category" dataKey="word" width={92} tick={{ fontSize: 12, fill: 'var(--ink)' }} interval={0} />
            <Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} formatter={(v) => [`${v}% of the strongest word`, 'Weight']} />
            <Bar dataKey="pct" fill={MC[m.id]} radius={4} isAnimationActive={false}><LabelList dataKey="pct" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: 'var(--ink)' }} /></Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

/** This model's own score for the message pasted above, so the checker and the comparison are one thing. */
function YourMessage({ out, id }: { out: SpamResult | null; id: string }) {
  const p = out?.all_models.find((x) => x.id === id)?.probability
  return (
    <div className="rounded-xl bg-sunken p-4">
      <div className="text-sm font-semibold">Your message</div>
      {p == null ? <p className="mt-1 text-sm text-muted">Paste a message above and every model scores it here.</p> : (
        <>
          <div className="num mt-1 text-3xl font-bold tracking-tight">{pct(p, 0)}</div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-line" aria-hidden><span className="block h-full rounded-full" style={{ width: pct(p, 0), background: MC[id] }} /></div>
          <p className="mt-2 text-sm text-muted">{p >= 0.5 ? 'This model calls it a scam.' : 'This model does not call it a scam.'}</p>
        </>
      )}
    </div>
  )
}

function Block({ m, best, out }: { m: Model; best: boolean; out: SpamResult | null }) {
  const c = m.confusion
  const cells = [
    { label: 'Scams caught', n: c.tp, good: true }, { label: 'Real messages blocked', n: c.fp, good: false },
    { label: 'Scams missed', n: c.fn, good: false }, { label: 'Real messages passed', n: c.tn, good: true },
  ]
  return (
    <article className="card space-y-5 p-5" aria-labelledby={`m-${m.id}`}>
      <header className="flex flex-wrap items-center gap-3">
        <span className="size-3 rounded-sm" style={{ background: MC[m.id] }} aria-hidden />
        <h3 id={`m-${m.id}`} className="text-xl font-bold">{m.name}</h3>
        {best && <span className="chip chip-brand">In use</span>}
        <p className="basis-full text-sm text-muted">{m.about}</p>
      </header>
      <dl className="grid grid-cols-3 gap-3">
        {[['Precision', m.precision, 'Of the messages it called scams, how many really were.'], ['Recall', m.recall, 'Of all real scams, how many it caught.'], ['F1', m.f1, 'One number that balances precision and recall.']].map(([k, v, tip]) => (
          <div key={String(k)} className="rounded-xl bg-sunken p-3"><dt className="flex items-center gap-1 text-sm text-muted">{k} <Tip text={String(tip)} /></dt><dd className="num text-2xl font-bold">{pct(Number(v))}</dd></div>
        ))}
      </dl>
      <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)_14rem]">
        <div className="grid grid-cols-2 gap-2 self-start" role="img" aria-label={`Confusion matrix: ${cells.map((x) => `${x.label} ${x.n}`).join(', ')}.`}>
          {cells.map((x) => (
            <div key={x.label} className="rounded-xl p-3 text-center" style={{ background: `color-mix(in srgb, ${x.good ? 'var(--ok)' : 'var(--bad)'} 12%, white)` }}>
              <div className="num text-2xl font-bold">{x.n.toLocaleString('en-IN')}</div><div className="text-xs">{x.label}</div>
            </div>
          ))}
        </div>
        <TopWords m={m} />
        <YourMessage out={out} id={m.id} />
      </div>
    </article>
  )
}

export default function MessagesPage() {
  const sum = useBiz(() => spamApi.summary(), 'spam-summary')
  const [out, setOut] = useState<SpamResult | null>(null)
  const s = sum.data
  return (
    <div className="space-y-8">
      <PageHeader title="Scam messages" answer="Got a strange SMS or WhatsApp? Paste it here and find out in a second." />
      <Checker out={out} setOut={setOut} />
      <section className="space-y-4" aria-labelledby="cmp">
        <div>
          <h2 id="cmp" className="text-2xl font-bold tracking-tight">How well do the models spot scams?</h2>
          {s && <p className="mt-1 text-muted">Tested on {s.info.test.toLocaleString('en-IN')} messages the models never saw ({s.info.test_spam.toLocaleString('en-IN')} were scams).</p>}
        </div>
        {sum.error && <p className="text-sm text-bad">{sum.error}</p>}
        {!s && !sum.error && <div className="space-y-4"><div className="skeleton h-72" /><div className="skeleton h-72" /></div>}
        {s && s.models.map((m) => <Block key={m.id} m={m} best={m.id === s.best} out={out} />)}
        {s && <p className="text-sm text-muted">{s.info.caveats[1]}</p>}
      </section>
      <Link to="/about" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: How it works <ArrowRight size={14} /></Link>
    </div>
  )
}
