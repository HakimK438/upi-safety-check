import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  AlertTriangle, AtSign, CalendarDays, CheckCircle2, ChevronDown, Clock, CreditCard, Fingerprint, IndianRupee, KeyRound, MapPin, Network,
  Repeat, RotateCcw, ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX, Smartphone, Undo2, UserRound, UserX, Users, Zap, type LucideIcon,
} from 'lucide-react'
import { DEFAULT_PAYMENT, INR_PER_USD, fraudApi, inr, type Experiment, type ModelResult, type Overview, type Payment, type ScoreOut } from '../lib/fraudApi'

// One colour per model, the same on every chart (colour-blind safe).
const MC: Record<string, string> = { xgb: '#1F4FD8', mlp: '#7C5CDB', rf: '#0E8A7E', logreg: '#94A3B8' }
const ORDER = ['xgb', 'mlp', 'rf', 'logreg']
const NAMES: Record<string, string> = { xgb: 'XGBoost', mlp: 'Neural network', rf: 'Random forest', logreg: 'Logistic regression' }
const CH = 300
const AX = { tick: { fontSize: 12, fill: 'var(--muted)' }, stroke: 'var(--line)', tickLine: false } as const
const TT = { contentStyle: { borderRadius: 12, border: '1px solid var(--line)', background: 'var(--surface)', fontSize: 12 } }
const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`
const name = (m: string) => NAMES[m] ?? m
const n0 = (v: number) => v.toLocaleString('en-IN')

type ZoneId = 'approve' | 'check' | 'block'
const zoneOf = (p: number, check: number, block: number): ZoneId => (p >= block ? 'block' : p >= check ? 'check' : 'approve')
const ZC: Record<ZoneId, string> = { approve: 'var(--ok)', check: 'var(--warn)', block: 'var(--bad)' }
const VERDICT: Record<ZoneId, { Icon: LucideIcon; title: string; line: string; todo: string[] }> = {
  approve: { Icon: ShieldCheck, title: 'Safe', line: 'This looks like a normal payment. You can accept it.', todo: ['Complete the sale as usual.'] },
  check: { Icon: ShieldQuestion, title: 'Check first', line: 'Something is unusual. Make sure the money has arrived before you hand over goods.', todo: ['Open your bank or UPI app and confirm the money is there.', 'For a large amount, ask for ID or another way to pay.'] },
  block: { Icon: ShieldX, title: 'Likely fraud', line: 'This matches known fraud patterns. Do not hand over goods yet.', todo: ['Ask for another way to pay, such as cash.', 'If they insist, wait until the money is in your bank account.'] },
}

/* ------------------------------------------------------------------ layout */
function Section({ n, id, title, line, children }: { n: number; id: string; title: string; line?: string; children: ReactNode }) {
  return (
    <section className="space-y-5" aria-labelledby={id}>
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-brand text-on-brand text-sm font-semibold num mt-0.5" aria-hidden>{n}</span>
        <div>
          <h2 id={id} className="text-2xl font-bold tracking-tight">{title}</h2>
          {line && <p className="text-muted mt-1 max-w-3xl">{line}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}
function ChartCard({ title, how, alt, children }: { title: string; how?: string; alt: string; children: ReactNode }) {
  return (
    <figure className="card p-5 h-full min-w-0 flex flex-col">
      <figcaption className="mb-3">
        <div className="font-semibold">{title}</div>
        {how && <div className="text-sm text-muted mt-0.5">{how}</div>}
      </figcaption>
      <div role="img" aria-label={alt} className="flex-1 min-w-0">{children}</div>
    </figure>
  )
}

/* ------------------------------------------------------------------ page */
export default function FraudPage() {
  const [ov, setOv] = useState<Overview | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { fraudApi.overview().then(setOv).catch((e) => setErr(e.message)) }, [])

  if (err) return <div className="card p-6"><p className="font-semibold">The fraud check is not ready.</p><p className="text-muted mt-1">{err}</p></div>
  if (!ov) return <div className="space-y-4"><div className="skeleton h-24" /><div className="skeleton h-96" /></div>
  const e = ov.ieee

  return (
    <div className="fraud-page space-y-12">
      <header className="page-in flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-line">
        <div className="flex items-center gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-brand text-on-brand"><ShieldCheck size={26} aria-hidden /></span>
          <div>
            <h1 className="text-3xl md:text-4xl font-bold tracking-tight leading-tight">Fraud check</h1>
            <p className="text-muted">Enter a payment, press <b className="text-ink">Check payment</b>, and get a clear answer with the reasons.</p>
          </div>
        </div>
        <div className="text-sm text-muted rounded-full border border-line bg-surface px-4 py-2">
          Model: <b className="text-ink">{name(e.best)}</b> · learned from {n0(e.rows)} payments
        </div>
      </header>
      <CheckFlow />
      <ModelSection e={e} />
      {ov.eda && <PatternSection ov={ov} />}
    </div>
  )
}

/* ------------------------------------------------------------------ 1: check a payment */
type Opt<T extends string> = { v: T; label: string }
interface Answers {
  amount: number
  time: 'morning' | 'afternoon' | 'evening' | 'night'
  burst: number
  distance: 'near' | 'city' | 'other_city' | 'far' | 'unknown'
  lastPaid: 'never' | 'hour' | 'today' | 'week' | 'older'
  prior: number
  usual: number | null
  age: 'week' | 'month' | 'year' | 'older' | 'unknown'
  reported: boolean
  newPhone: boolean
  handle: 'regular' | 'throwaway' | 'none'
  shared: number
}
const START: Answers = { amount: 1000, time: 'afternoon', burst: 0, distance: 'near', lastPaid: 'week', prior: 5, usual: 800, age: 'older', reported: false, newPhone: false, handle: 'regular', shared: 1 }
const EXAMPLES: { label: string; a: Answers }[] = [
  { label: 'Regular customer', a: START },
  { label: 'Unusual payment', a: { ...START, amount: 6000, time: 'night', lastPaid: 'older' } },
  { label: 'Fraud pattern', a: { ...START, amount: 25000, time: 'night', burst: 3, lastPaid: 'hour', prior: 1, usual: 500, age: 'week', newPhone: true, shared: 4, distance: 'far', handle: 'throwaway' } },
]
const TIME: Opt<Answers['time']>[] = [{ v: 'morning', label: 'Morning' }, { v: 'afternoon', label: 'Afternoon' }, { v: 'evening', label: 'Evening' }, { v: 'night', label: 'Night (12-6 am)' }]
const DIST: Opt<Answers['distance']>[] = [{ v: 'near', label: 'Nearby' }, { v: 'city', label: 'Same city' }, { v: 'other_city', label: 'Another city' }, { v: 'far', label: 'Far away' }, { v: 'unknown', label: "Don't know" }]
const LAST: Opt<Answers['lastPaid']>[] = [{ v: 'never', label: 'Never (first time)' }, { v: 'hour', label: 'In the last hour' }, { v: 'today', label: 'Earlier today' }, { v: 'week', label: 'This week' }, { v: 'older', label: 'Longer ago' }]
const AGE: Opt<Answers['age']>[] = [{ v: 'week', label: 'This week' }, { v: 'month', label: 'This month' }, { v: 'year', label: 'This year' }, { v: 'older', label: 'Over a year ago' }, { v: 'unknown', label: "Don't know" }]
const HANDLE: Opt<Answers['handle']>[] = [{ v: 'regular', label: 'Normal (gmail.com, @okaxis)' }, { v: 'throwaway', label: 'Throwaway (protonmail, anonymous)' }, { v: 'none', label: 'Not given' }]

function toPayment(a: Answers): Payment {
  const first = a.lastPaid === 'never'
  return {
    ...DEFAULT_PAYMENT,
    amount: a.amount / INR_PER_USD,
    hour: { morning: 10, afternoon: 15, evening: 20, night: 2 }[a.time],
    customer_prior_payments: first ? 0 : Math.max(1, a.prior),
    customer_usual_amount: first || a.usual == null ? null : a.usual / INR_PER_USD,
    hours_since_last_payment: first ? null : { hour: 0.5, today: 6, week: 72, older: 400, never: null }[a.lastPaid],
    payments_last_hour: a.burst,
    payments_last_24h: a.burst,
    account_age_days: { week: 3, month: 20, year: 180, older: 500, unknown: null }[a.age],
    prior_fraud: a.reported ? 1 : 0,
    new_device: a.newPhone && !first,
    accounts_on_device_7d: a.shared,
    distance_km: { near: 5, city: 30, other_city: 250, far: 900, unknown: null }[a.distance],
    email_domain: { regular: 'gmail.com', throwaway: 'anonymous.com', none: null }[a.handle],
  }
}
/** The same yes/no warning signs the model uses, computed live from the answers. */
function redFlags(a: Answers): Record<string, string> {
  const f: Record<string, string> = {}
  const first = a.lastPaid === 'never'
  if (!first && a.usual && a.amount / a.usual > 3) f.amount = `${(a.amount / a.usual).toFixed(1)}x what they usually pay`
  if (a.time === 'night') f.time = 'Late at night'
  if (a.burst >= 2) f.burst = 'Many payments in a short time'
  if (a.distance === 'other_city' || a.distance === 'far') f.distance = 'Far from where they usually pay'
  if (a.age === 'week') f.age = 'Brand-new account'
  if (a.reported) f.reported = 'Reported for fraud before'
  if (a.newPhone && !first) f.newPhone = 'Paying from a new phone'
  if (a.handle === 'throwaway') f.handle = 'Throwaway email or UPI ID'
  if (a.shared >= 3) f.shared = `${a.shared} accounts on one phone`
  return f
}

function Q({ icon: Icon, label, hint, flag, children }: { icon: LucideIcon; label: string; hint?: string; flag?: string; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-sm font-semibold"><Icon size={15} className="text-brand shrink-0" aria-hidden />{label}</div>
      {hint && <div className="text-xs text-muted mt-0.5">{hint}</div>}
      <div className="mt-2">{children}</div>
      {flag && <div className="mt-1.5 flex items-center gap-1 text-xs font-semibold text-bad"><AlertTriangle size={13} aria-hidden />{flag}</div>}
    </div>
  )
}
function Choice<T extends string>({ value, options, onChange, label }: { value: T; options: Opt<T>[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button type="button" role="radio" aria-checked={value === o.v} key={o.v} onClick={() => onChange(o.v)}
          className={`rounded-full border px-3 py-1.5 text-sm transition-colors min-h-9 ${value === o.v ? 'bg-brand text-on-brand border-transparent font-medium' : 'border-line bg-surface hover:bg-brand-soft'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
const YesNo = ({ value, onChange, label }: { value: boolean; onChange: (v: boolean) => void; label: string }) => (
  <Choice label={label} value={value ? 'yes' : 'no'} options={[{ v: 'no', label: 'No' }, { v: 'yes', label: 'Yes' }]} onChange={(v) => onChange(v === 'yes')} />
)
function Group({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 space-y-5">
      <legend className="flex items-center gap-2 font-semibold text-lg mb-4"><Icon size={20} className="text-brand" aria-hidden />{title}</legend>
      {children}
    </fieldset>
  )
}

/** Answers pre-filled from a link (Payments, Risk alerts, Check a payment): ?amount=&time=&burst=&prior=&lastPaid=&usual=&auto=1 */
function fromLink(p: URLSearchParams): Answers {
  if (!p.has('amount')) return START
  const pick = <T extends string>(k: string, ok: readonly T[], d: T): T => (ok.includes(p.get(k) as T) ? (p.get(k) as T) : d)
  const usual = Number(p.get('usual'))
  return {
    ...START, amount: Math.max(1, Number(p.get('amount')) || START.amount), time: pick('time', ['morning', 'afternoon', 'evening', 'night'], START.time),
    burst: Math.max(0, Number(p.get('burst')) || 0), prior: Math.max(0, Number(p.get('prior')) || 0), lastPaid: pick('lastPaid', ['never', 'hour', 'today', 'week', 'older'], 'week'),
    usual: usual > 0 ? usual : null, newPhone: p.get('newPhone') === '1',
  }
}

function CheckFlow() {
  const [params] = useSearchParams()
  const [a, setA] = useState<Answers>(() => fromLink(params))
  const [out, setOut] = useState<ScoreOut | null>(null)
  const [checked, setChecked] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [more, setMore] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)
  const set = <K extends keyof Answers>(k: K, v: Answers[K]) => setA((x) => ({ ...x, [k]: v }))
  const num = (k: 'amount' | 'prior' | 'burst' | 'shared', min = 0) => (ev: React.ChangeEvent<HTMLInputElement>) => set(k, Math.max(min, Number(ev.target.value)))
  const flags = redFlags(a)
  const nFlags = Object.keys(flags).length
  const first = a.lastPaid === 'never'
  const run = () => {
    setBusy(true)
    setMsg('')
    const snap = a
    fraudApi.score(toPayment(snap))
      .then((r) => {
        setOut(r)
        setChecked(JSON.stringify(snap))
        const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        requestAnimationFrame(() => resultRef.current?.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' }))
      })
      .catch((x) => setMsg(x.message))
      .finally(() => setBusy(false))
  }
  useEffect(() => { if (params.get('auto') === '1') run() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const stale = out != null && checked !== JSON.stringify(a)
  const I = 'w-full rounded-xl border border-line bg-surface px-3 py-2 min-h-11'

  return (
    <Section n={1} id="sec-check" title="Check a payment" line="Answer what you know about this payment. Anything unusual is marked in red as you go.">
      <form className="card p-5 md:p-7" onSubmit={(ev) => { ev.preventDefault(); run() }}>
        <div className="flex flex-wrap items-center gap-2 mb-6 text-sm">
          <span className="text-muted mr-1">Try an example:</span>
          {EXAMPLES.map((x) => (
            <button key={x.label} type="button" onClick={() => setA(x.a)} className="rounded-full border border-line px-3 py-1.5 hover:bg-brand-soft">{x.label}</button>
          ))}
        </div>

        <div className="grid gap-8 lg:grid-cols-3 lg:divide-x divide-line">
          <Group icon={IndianRupee} title="The payment">
            <Q icon={IndianRupee} label="Amount (₹)" hint="How much the customer is paying now" flag={flags.amount}>
              <input className={I} type="number" min={1} aria-label="Amount in rupees" value={a.amount} onChange={num('amount', 1)} />
            </Q>
            <Q icon={Clock} label="Time of payment" flag={flags.time}><Choice label="Time of payment" value={a.time} options={TIME} onChange={(v) => set('time', v)} /></Q>
            <Q icon={Zap} label="Other payments from them in the last hour" flag={flags.burst}>
              <input className={I} type="number" min={0} aria-label="Payments from them in the last hour" value={a.burst} onChange={num('burst')} />
            </Q>
            <Q icon={MapPin} label="Where are they paying from?" flag={flags.distance}><Choice label="Where they are paying from" value={a.distance} options={DIST} onChange={(v) => set('distance', v)} /></Q>
          </Group>

          <div className="lg:pl-8">
            <Group icon={UserRound} title="The customer">
              <Q icon={Repeat} label="When did they last pay you?"><Choice label="When they last paid you" value={a.lastPaid} options={LAST} onChange={(v) => set('lastPaid', v)} /></Q>
              {!first && (
                <div className="grid grid-cols-2 gap-3">
                  <Q icon={Repeat} label="Times paid before"><input className={I} type="number" min={1} aria-label="Times they paid you before" value={a.prior} onChange={num('prior', 1)} /></Q>
                  <Q icon={IndianRupee} label="Usual amount (₹)" flag={undefined}>
                    <input className={I} type="number" min={1} aria-label="What they usually pay in rupees" value={a.usual ?? ''} placeholder="Not sure"
                      onChange={(x) => set('usual', x.target.value === '' ? null : Math.max(1, Number(x.target.value)))} />
                  </Q>
                </div>
              )}
              <Q icon={CalendarDays} label="When was their account created?" flag={flags.age}><Choice label="When their account was created" value={a.age} options={AGE} onChange={(v) => set('age', v)} /></Q>
              <Q icon={UserX} label="Reported for fraud before?" flag={flags.reported}><YesNo label="Reported for fraud before" value={a.reported} onChange={(v) => set('reported', v)} /></Q>
            </Group>
          </div>

          <div className="lg:pl-8">
            <Group icon={Smartphone} title="Phone and ID">
              {!first && <Q icon={Fingerprint} label="Paying from a new phone?" hint="Not the phone they used before" flag={flags.newPhone}><YesNo label="New phone" value={a.newPhone} onChange={(v) => set('newPhone', v)} /></Q>}
              <Q icon={AtSign} label="Email or UPI ID" flag={flags.handle}><Choice label="Email or UPI ID" value={a.handle} options={HANDLE} onChange={(v) => set('handle', v)} /></Q>
              <div>
                <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className="flex items-center gap-1 text-sm font-medium text-brand">
                  <ChevronDown size={16} className={`transition-transform ${more ? 'rotate-180' : ''}`} aria-hidden />More details (optional)
                </button>
                {more && (
                  <div className="mt-4">
                    <Q icon={Users} label="Accounts used on this phone this week" hint="From your payment app, if it shows it. 1 = only this customer." flag={flags.shared}>
                      <input className={I} type="number" min={0} aria-label="Accounts seen on this phone this week" value={a.shared} onChange={num('shared')} />
                    </Q>
                  </div>
                )}
                {!more && flags.shared && <div className="mt-1.5 flex items-center gap-1 text-xs font-semibold text-bad"><AlertTriangle size={13} aria-hidden />{flags.shared}</div>}
              </div>
            </Group>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-line flex flex-col items-center gap-2 text-center">
          <button type="submit" className="btn btn-primary w-full sm:w-80 !min-h-14 text-lg" disabled={busy}>
            <ShieldCheck size={22} aria-hidden /><span>{busy ? 'Checking…' : 'Check payment'}</span>
          </button>
          <p className="text-sm text-muted" aria-live="polite">
            {nFlags === 0 ? 'No warning signs so far.' : `${nFlags} warning sign${nFlags > 1 ? 's' : ''} so far. The model weighs them all together.`}
          </p>
          {msg && <p className="text-bad text-sm" role="alert">{msg}</p>}
        </div>
      </form>

      <div ref={resultRef} className="scroll-mt-4" aria-live="polite">
        {out && <ResultCard out={out} stale={stale} />}
      </div>
    </Section>
  )
}

/** Ring that fills with the fraud chance, in the verdict colour. */
function ChanceRing({ p, color }: { p: number; color: string }) {
  const r = 52
  const c = 2 * Math.PI * r
  const shown = p < 0.01 ? 'under 1%' : pct(p)
  return (
    <div className="relative size-44 shrink-0" role="img" aria-label={`Chance of fraud ${shown}`}>
      <svg viewBox="0 0 120 120" className="size-full -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--sunken)" strokeWidth="12" />
        <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={`${Math.max(0.015, p) * c} ${c}`} className="transition-[stroke-dasharray] duration-700 motion-reduce:transition-none" />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div><div className="text-3xl font-bold num" style={{ color }}>{shown}</div><div className="text-xs text-muted">chance of fraud</div></div>
      </div>
    </div>
  )
}

function ResultCard({ out, stale }: { out: ScoreOut; stale: boolean }) {
  const { low_to_medium: check, medium_to_high: block } = out.gauge
  const z = zoneOf(out.probability, check, block)
  const v = VERDICT[z]
  const color = ZC[z]
  const ids = Object.keys(out.models)
  const agree = ids.filter((m) => zoneOf(out.models[m].probability, check, block) === z).length
  const up = z === 'approve' ? [] : out.reasons_up.slice(0, 3)
  const reasons = up.length ? up.map((r) => ({ k: r.feature, text: r.text, bad: true })) : out.reasons_down.slice(0, 3).map((r) => ({ k: r.feature, text: r.text.replace('Reassuring: ', 'Normal: '), bad: false }))
  const levels: { id: ZoneId; range: string }[] = [
    { id: 'approve', range: `under ${pct(check)}` }, { id: 'check', range: `${pct(check)} to ${pct(block)}` }, { id: 'block', range: `over ${pct(block)}` },
  ]

  return (
    <div className={`card overflow-hidden transition-opacity ${stale ? 'opacity-60' : ''}`}>
      {stale && <p className="px-6 pt-4 text-sm font-medium" role="status">You changed the details. Press Check payment again.</p>}
      <div className="flex items-center gap-4 px-6 py-6 text-white" style={{ background: color }}>
        <span className={`grid size-16 shrink-0 place-items-center rounded-full bg-white/20 ${z === 'block' ? 'animate-pulse motion-reduce:animate-none' : ''}`}><v.Icon size={36} strokeWidth={2.2} aria-hidden /></span>
        <div>
          <div className="text-3xl md:text-4xl font-bold leading-tight">{v.title}</div>
          <div className="text-base mt-0.5 text-white/90">{v.line}</div>
        </div>
      </div>

      <div className="flex flex-col md:flex-row items-center gap-8 p-6 border-b border-line">
        <ChanceRing p={out.probability} color={color} />
        <div className="flex-1 w-full space-y-2">
          {levels.map((l) => {
            const on = l.id === z
            const L = VERDICT[l.id]
            return (
              <div key={l.id} className={`flex items-center gap-3 rounded-xl px-4 py-3 border-2 ${on ? '' : 'opacity-40 border-transparent bg-sunken'}`}
                style={on ? { borderColor: ZC[l.id], background: `color-mix(in srgb, ${ZC[l.id]} 10%, var(--surface))` } : undefined} aria-current={on ? 'true' : undefined}>
                <L.Icon size={22} style={{ color: ZC[l.id] }} aria-hidden />
                <span className="font-semibold flex-1" style={on ? { color: ZC[l.id] } : undefined}>{L.title}</span>
                <span className="text-sm text-muted num">{l.range}</span>
                {on && <span className="text-xs font-bold text-white rounded-full px-2 py-0.5 whitespace-nowrap" style={{ background: ZC[l.id] }}>This payment</span>}
              </div>
            )
          })}
          <p className="text-sm text-muted pt-1">A normal payment: {out.typical_rate_percent.toFixed(1)}% · {agree} of {ids.length} models agree</p>
        </div>
      </div>

      <div className="grid gap-6 p-6 md:grid-cols-2">
        <div>
          <h3 className="font-semibold mb-2">{up.length ? 'Why' : 'What looks normal'}</h3>
          <ul className="space-y-2">
            {reasons.map((r) => (
              <li key={r.k} className="flex items-start gap-2.5">
                {r.bad ? <AlertTriangle size={18} className="mt-0.5 shrink-0 text-bad" aria-hidden /> : <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-ok" aria-hidden />}{r.text}
              </li>
            ))}
            {reasons.length === 0 && <li className="text-muted">Nothing stands out either way.</li>}
          </ul>
        </div>
        <div className="rounded-2xl bg-sunken p-4">
          <h3 className="font-semibold mb-1.5">What to do</h3>
          <ol className="list-decimal pl-5 space-y-1">{v.todo.map((t) => <li key={t}>{t}</li>)}</ol>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ 2: model comparison */
function mergeCurves(e: Experiment, key: 'roc' | 'pr', ids: string[], maxX = 1) {
  return e.models[ids[0]].curves[key].map((p, i) => {
    const row: Record<string, number> = { x: p[0] }
    ids.forEach((m) => { row[m] = e.models[m].curves[key][i][1] })
    return row
  }).filter((r) => r.x <= maxX + 1e-9)
}
// Simplest model first, the model in use last.
const TABLE_ORDER = ['logreg', 'rf', 'mlp', 'xgb']

function ModelSection({ e }: { e: Experiment }) {
  const ids = TABLE_ORDER.filter((m) => e.models[m])
  const roc = useMemo(() => Object.fromEntries(ids.map((m) => [m, mergeCurves(e, 'roc', [m], 0.1)])), [e])
  const pr = useMemo(() => Object.fromEntries(ids.map((m) => [m, mergeCurves(e, 'pr', [m])])), [e])

  return (
    <Section n={2} id="sec-models" title="Model comparison"
      line={`We tested 4 models on payments they had never seen. ${name(e.best)} is the one in use.`}>
      <div className="space-y-6">
        {ids.map((m, i) => {
          const r = e.models[m]
          const a = r.at_threshold
          const stats: [string, number][] = [
            ['Precision', a.precision],
            ['Recall', a.recall],
            ['F1 score', a.f1],
          ]
          return (
            <article key={m} className="card overflow-hidden" aria-labelledby={`model-${m}`}>
              <header className="flex items-center gap-3 px-5 py-3 border-b border-line">
                <span className="grid size-7 place-items-center rounded-full text-white text-sm font-bold num" style={{ background: MC[m] }} aria-hidden>{i + 1}</span>
                <h3 id={`model-${m}`} className="text-lg font-bold">{name(m)}</h3>
                {m === e.best && <span className="text-xs font-bold text-white rounded-full px-2.5 py-0.5 bg-brand">In use</span>}
              </header>
              <div className="grid gap-6 p-5 lg:grid-cols-[11rem_17rem_minmax(0,1fr)_minmax(0,1fr)] items-start">
                <dl className="grid grid-cols-3 gap-3 lg:grid-cols-1 lg:pt-7">
                  {stats.map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-sm font-normal text-ink">{k}</dt>
                      <dd className="text-2xl font-bold num leading-tight">{pct(v, 1)}</dd>
                    </div>
                  ))}
                </dl>
                <Matrix r={r} label={name(m)} />
                <div>
                  <div className="text-sm font-normal text-ink mb-2">ROC curve <span className="font-normal text-muted">· score {pct(r.test.roc_auc, 1)}</span></div>
                  <div role="img" aria-label={`ROC curve for ${name(m)}, score ${pct(r.test.roc_auc, 1)}`}><CurveChart data={roc[m]} ids={[m]} best={m} kind="roc" height={210} /></div>
                </div>
                <div>
                  <div className="text-sm font-normal text-ink mb-2">Precision-recall curve <span className="font-normal text-muted">· score {pct(r.test.pr_auc, 1)}</span></div>
                  <div role="img" aria-label={`Precision-recall curve for ${name(m)}, score ${pct(r.test.pr_auc, 1)}`}><CurveChart data={pr[m]} ids={[m]} best={m} kind="pr" height={210} /></div>
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </Section>
  )
}

/** Plain 2x2 confusion matrix: rows = what really happened, columns = what the model predicted. */
function Matrix({ r, label }: { r: ModelResult; label: string }) {
  const a = r.at_threshold
  const b = 'border border-line px-1.5 py-1.5 text-center'
  const h = 'border border-line px-1.5 py-1 text-[11px] font-semibold'
  // Green = right answer, red = mistake.
  const cell = (v: number, what: string, ok: boolean) => (
    <td className={b} style={{ background: `color-mix(in srgb, ${ok ? 'var(--ok)' : 'var(--bad)'} ${ok ? 14 : 12}%, var(--surface))` }}>
      <div className="font-bold text-base">{n0(v)}</div><div className="text-[11px] text-muted">{what}</div>
    </td>
  )
  const fraud = <span>Fraud</span>
  const genuine = <span>Genuine</span>
  return (
    <div>
    <div className="mb-2 text-sm font-normal text-ink">Confusion matrix</div>
    <table className="table-fixed border-collapse w-full" aria-label={`${label} confusion matrix: fraud caught ${a.tp}, fraud missed ${a.fn}, false alarms ${a.fp}, genuine passed ${a.tn}`}>
      <thead>
        <tr>
          <th className={`${h} w-16 text-muted`}>Real \ Said</th>
          <th className={h} scope="col">{fraud}</th><th className={h} scope="col">{genuine}</th>
        </tr>
      </thead>
      <tbody>
        <tr><th className={`${h} text-left`} scope="row">{fraud}</th>{cell(a.tp, 'True positive', true)}{cell(a.fn, 'False negative', false)}</tr>
        <tr><th className={`${h} text-left`} scope="row">{genuine}</th>{cell(a.fp, 'False positive', false)}{cell(a.tn, 'True negative', true)}</tr>
      </tbody>
    </table>
    </div>
  )
}

function CurveChart({ data, ids, best, kind, height = CH }: { data: Record<string, number>[]; ids: string[]; best: string; kind: 'roc' | 'pr'; height?: number }) {
  const roc = kind === 'roc'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ left: 0, right: 12, top: 4, bottom: 4 }}>
        <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
        <XAxis {...AX} type="number" dataKey="x" domain={roc ? [0, 0.1] : [0, 1]} ticks={roc ? [0, 0.025, 0.05, 0.075, 0.1] : [0, 0.25, 0.5, 0.75, 1]} tickFormatter={(v) => pct(v, roc && v % 0.05 ? 1 : 0)} height={44}
          label={{ value: roc ? 'False alarms' : 'Fraud caught', position: 'insideBottom', offset: 0, fontSize: 12, fill: 'var(--muted)' }} />
        <YAxis {...AX} width={52} domain={roc ? [0.5, 1] : [0, 1]} allowDataOverflow tickFormatter={(v) => pct(v)}
          label={{ value: roc ? 'Fraud caught' : 'Flags that are real fraud', angle: -90, position: 'insideLeft', offset: 10, fontSize: 12, fill: 'var(--muted)', style: { textAnchor: 'middle' } }} />
        <Tooltip {...TT} formatter={(v, n) => [pct(Number(v), 1), name(String(n))]} labelFormatter={(l) => `${roc ? 'False alarms' : 'Fraud caught'} ${pct(Number(l), 1)}`} />
        {ids.map((m) => <Line isAnimationActive={false} key={m} dataKey={m} stroke={MC[m]} dot={false} strokeWidth={m === best ? 3 : 1.6} strokeOpacity={m === best ? 1 : 0.8} />)}
        {ids.length > 1 && <Legend verticalAlign="top" height={40} wrapperStyle={{ fontSize: 12 }} formatter={(v) => name(String(v))} />}
      </LineChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------------------ 3: how fraud shows up */
const FLAG_NAME: Record<string, string> = {
  flag_new_account: 'Brand-new account', flag_burst: 'Many payments in an hour', flag_amount_spike: '3x their usual amount or more',
  flag_new_device: 'New phone', flag_far: 'Far from usual place', flag_night: 'Late at night (12-6 am)',
  flag_shared_device: 'Phone shared by 3+ accounts', flag_anon_email: 'Throwaway email or UPI ID',
}
const PATTERN_INFO: Record<string, { Icon: LucideIcon; title: string; story: string }> = {
  account_takeover: { Icon: KeyRound, title: 'Stolen account', story: "Someone pays from a real customer's account using a new phone, several times, for big amounts." },
  card_testing: { Icon: CreditCard, title: 'Testing a stolen card', story: 'A new account makes tiny test payments, then one big one.' },
  mule_ring: { Icon: Network, title: 'One phone, many accounts', story: 'Many fresh accounts on one phone move stolen money fast.' },
  repeat_offender: { Icon: RotateCcw, title: 'Caught before, trying again', story: 'An account already reported for fraud pays again.' },
  friendly_fraud: { Icon: Undo2, title: 'False claim by a real customer', story: 'A regular customer pays, then tells the bank it was not them.' },
}

function PatternSection({ ov }: { ov: Overview }) {
  const ins = ov.insights
  const flags = [...ins.flags].sort((a, b) => b.fraud_rate - a.fraud_rate)
  const pats = [...ov.eda!.patterns].sort((a, b) => b.share - a.share)
  const data = flags.map((f) => ({ name: FLAG_NAME[f.flag] ?? f.label, rate: +(f.fraud_rate * 100).toFixed(1) }))

  return (
    <Section n={3} id="sec-patterns" title="How fraud shows up" line={`Learned from ${n0(ins.rows)} payments. A normal payment is fraud ${pct(ins.base_rate, 1)} of the time.`}>
      <div className="grid gap-6 lg:grid-cols-2 items-stretch">
        <ChartCard title="Each warning sign makes fraud far more likely" how="Share of payments with this sign that were fraud. Dashed line = a normal payment."
          alt={`Fraud rate per warning sign: ${data.map((d) => `${d.name} ${d.rate}%`).join('; ')}`}>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart layout="vertical" data={data} margin={{ left: 0, right: 44 }}>
              <CartesianGrid horizontal={false} stroke="var(--line)" strokeDasharray="3 3" />
              <XAxis {...AX} type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
              <YAxis {...AX} type="category" dataKey="name" width={215} tick={{ fontSize: 12, fill: 'var(--ink)' }} interval={0} />
              <Tooltip {...TT} formatter={(v) => [`${v}% were fraud`, 'With this sign']} />
              <ReferenceLine x={ins.base_rate * 100} stroke="var(--muted)" strokeDasharray="4 4" />
              <Bar isAnimationActive={false} dataKey="rate" fill="var(--bad)" radius={[0, 4, 4, 0]}>
                <LabelList dataKey="rate" position="right" fontSize={11} fill="var(--ink)" formatter={(v: unknown) => `${Number(v).toFixed(0)}%`} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <div className="card p-5">
          <div className="font-semibold mb-3">The 5 kinds of fraud</div>
          <ul className="divide-y divide-line">
            {pats.map((q) => {
              const info = PATTERN_INFO[q.pattern] ?? { Icon: ShieldAlert, title: q.name, story: '' }
              return (
                <li key={q.pattern} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunken"><info.Icon size={18} aria-hidden /></span>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="font-semibold">{info.title}</span>
                      <span className="text-sm text-muted num">{pct(q.share)} of fraud{q.caught != null && ` · ${pct(q.caught)} caught`}</span>
                    </div>
                    <p className="text-sm text-muted">{info.story} Typical amount {inr(q.median_amount)}.</p>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </Section>
  )
}
