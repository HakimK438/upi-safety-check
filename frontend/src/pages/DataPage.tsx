import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, LabelList } from 'recharts'
import { ArrowDown, ArrowRight, ArrowUp, CircleCheck, CircleX, Database, Download, FileUp, Loader2, RotateCcw, Search } from 'lucide-react'
import { rupees0, rupeesCompact, useBiz } from '../lib/biz'
import { bizApi, type ExploreTable } from '../lib/bizApi'
import { useBizCtx } from '../lib/bizctx'
import { Pager } from '../components/bizui'
import { AX, ChartCard, PageHeader, TT } from '../components/shell'

type Kind = 'transactions' | 'orders' | 'refunds' | 'settlements'
interface Box { kind: Kind; title: string; required: string[]; optional: string[]; example: string[] }

// Required columns follow backend/app/merchant/model.py. `aliases` lets common spellings through the quick check.
const BOXES: Box[] = [
  { kind: 'transactions', title: 'Payments', required: ['txn_ref', 'timestamp', 'amount', 'status'],
    optional: ['order_id', 'outlet', 'payer_ref', 'new_device_flag', 'ip_location_mismatch', 'failed_attempts_last_24h', 'user_loyalty_score', 'user_avg_txn_value', 'recurring_payment_flag'],
    example: ['600012345678', '2025-03-14 16:42', '1250.50', 'success'] },
  { kind: 'orders', title: 'Orders', required: ['order_id', 'timestamp', 'amount'], optional: ['outlet'], example: ['ORD-1001', '2025-03-14 16:40', '1250.50'] },
  { kind: 'refunds', title: 'Refunds', required: ['txn_ref', 'timestamp', 'amount'], optional: ['refund_id'], example: ['600012345678', '2025-03-15 10:05', '250.00'] },
  { kind: 'settlements', title: 'Settlements', required: ['date', 'amount'], optional: [], example: ['2025-03-15', '41250.00'] },
]
const ALIASES: Record<string, string[]> = {
  txn_ref: ['txn_ref', 'transaction_id', 'transaction_ref', 'txn_id', 'reference', 'ref_no', 'utr', 'rrn'],
  timestamp: ['timestamp', 'ts', 'datetime', 'date_time', 'time', 'transaction_time', 'date'],
  amount: ['amount', 'amt', 'amount_inr', 'amount_rs', 'txn_amount'],
  status: ['status', 'payment_status', 'txn_status'],
  order_id: ['order_id', 'order', 'order_ref', 'order_no'],
  date: ['date', 'settlement_date', 'timestamp'],
}
const TABLES = [{ id: 'payments', label: 'Payments' }, { id: 'orders', label: 'Orders' }, { id: 'refunds', label: 'Refunds' }, { id: 'settlements', label: 'Settlements' }] as const
const DICTIONARY: [string, string][] = [
  ['reference', 'The 12-digit bank reference (UTR) of the payment.'], ['time', 'When the payment happened.'], ['amount', 'How much the customer paid, in rupees.'],
  ['status', 'Received, failed, pending or reversed.'], ['branch', 'The branch that took the payment.'], ['customer', 'Who paid. Used to spot repeat customers.'],
  ['order', 'The order this payment paid for. Empty means no order was matched.'], ['risk', 'Safe, Check or Fraud, from the fraud model.'],
]
const CORR_COLOR = (v: number) => (v >= 0 ? `color-mix(in srgb, #1F4FD8 ${Math.round(Math.abs(v) * 100)}%, white)` : `color-mix(in srgb, #B7700B ${Math.round(Math.abs(v) * 100)}%, white)`)
const pctTxt = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`
const hour12 = (h: number) => `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}`
const shortDate = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const csvEscape = (s: string) => s

/* ------------------------------------------------------------------ Tab A: add your data */
function download(b: Box) {
  const text = [[...b.required, ...b.optional.slice(0, 1)].join(','), [...b.example, ...b.optional.slice(0, 1).map(() => '')].join(',')].map(csvEscape).join('\n') + '\n'
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  a.download = `${b.title.toLowerCase()}_template.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function UploadBox({ b, file, check, onPick }: { b: Box; file: File | null; check: { ok: boolean; missing: string[] } | null; onPick: (f: File | null) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <div className="card flex min-w-0 flex-col p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">{b.title}</h3>
        {check && (check.ok ? <CircleCheck size={22} style={{ color: 'var(--ok)' }} aria-label="File looks right" /> : <CircleX size={22} style={{ color: 'var(--bad)' }} aria-label="File has a problem" />)}
      </div>
      <dl className="mt-3 space-y-2 text-sm">
        <div><dt className="text-muted">Required</dt><dd className="mt-1 flex flex-wrap gap-1.5">{b.required.map((c) => <code key={c} className="rounded bg-sunken px-1.5 py-0.5 text-xs">{c}</code>)}</dd></div>
        {b.optional.length > 0 && <div><dt className="text-muted">Optional</dt><dd className="mt-1 flex flex-wrap gap-1.5">{b.optional.map((c) => <code key={c} className="rounded border border-line px-1.5 py-0.5 text-xs text-muted">{c}</code>)}</dd></div>}
        <div><dt className="text-muted">Example row</dt><dd className="mt-1 overflow-x-auto rounded bg-sunken px-2 py-1.5 font-mono text-xs whitespace-nowrap">{b.example.join(', ')}</dd></div>
      </dl>
      {check && !check.ok && <p className="mt-3 text-sm" style={{ color: 'var(--bad)' }}>Missing: {check.missing.join(', ')}</p>}
      <input ref={ref} type="file" accept=".csv,text/csv" hidden onChange={(e) => { onPick(e.target.files?.[0] ?? null); e.target.value = '' }} />
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
        <button className="btn btn-ghost !min-h-9 !px-3 text-sm" onClick={() => ref.current?.click()}><FileUp size={15} /> {file ? 'Change file' : 'Choose CSV'}</button>
        <button className="btn btn-ghost !min-h-9 !px-3 text-sm" onClick={() => download(b)}><Download size={15} /> Download template</button>
        {file && <span className="w-full truncate text-xs text-muted" title={file.name}>{file.name}</span>}
      </div>
    </div>
  )
}

function AddData() {
  const { ds, meta, useDataset, useSample } = useBizCtx()
  const [files, setFiles] = useState<Record<Kind, File | null>>({ transactions: null, orders: null, refunds: null, settlements: null })
  const [checks, setChecks] = useState<Partial<Record<Kind, { ok: boolean; missing: string[] }>>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  async function pick(b: Box, f: File | null) {
    setFiles((x) => ({ ...x, [b.kind]: f }))
    setOk('')
    if (!f) return setChecks((c) => ({ ...c, [b.kind]: undefined }))
    const header = (await f.slice(0, 4000).text()).split(/\r?\n/)[0].split(',').map((h) => h.trim().toLowerCase().replace(/^"|"$/g, ''))
    const missing = b.required.filter((c) => !(ALIASES[c] ?? [c]).some((a) => header.includes(a)))
    setChecks((c) => ({ ...c, [b.kind]: { ok: missing.length === 0, missing } }))
  }
  const ready = !!files.transactions && Object.values(checks).every((c) => !c || c.ok)

  async function analyse() {
    if (!files.transactions) return
    setBusy(true); setErr(''); setOk('')
    try {
      const m = await bizApi.upload({ transactions: files.transactions, orders: files.orders, refunds: files.refunds, settlements: files.settlements })
      useDataset(m)
      setOk(`Done. ${m.counts.transactions.toLocaleString('en-IN')} payments loaded.`)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">{BOXES.map((b) => <UploadBox key={b.kind} b={b} file={files[b.kind]} check={checks[b.kind] ?? null} onPick={(f) => pick(b, f)} />)}</div>
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <button className="btn btn-primary" disabled={!ready || busy} onClick={analyse}>{busy ? <Loader2 size={18} className="animate-spin" /> : null} Use my data</button>
        {!files.transactions && <span className="text-sm text-muted">Choose at least the Payments file.</span>}
        {ds !== 'sample' && <button className="btn btn-ghost" onClick={useSample}><RotateCcw size={16} /> Back to sample data</button>}
        {ok && <span className="text-sm" role="status" style={{ color: 'var(--ok)' }}>{ok}</span>}
        {err && <span className="text-sm" role="alert" style={{ color: 'var(--bad)' }}>{err}</span>}
        <span className="ml-auto text-sm text-muted">Now showing: {meta ? `${meta.source === 'sample' ? 'Sample data' : 'Your data'} · ${meta.counts.transactions.toLocaleString('en-IN')} payments` : '…'}</span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ Tab B: data explorer */
function Viewer() {
  const { ds } = useBizCtx()
  const [name, setName] = useState<(typeof TABLES)[number]['id']>('payments')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<string | undefined>()
  const [desc, setDesc] = useState(true)
  const [page, setPage] = useState(1)
  const { data } = useBiz<ExploreTable>(() => bizApi.exploreTable(ds, { name, q, sort, desc, page, page_size: 10 }), `ex-${ds}-${name}-${q}-${sort}-${desc}-${page}`)
  const th = (c: string) => { if (sort === c) setDesc(!desc); else { setSort(c); setDesc(false) } setPage(1) }
  const KIND = { text: 'text', number: 'number', date: 'date' } as const
  return (
    <section className="card space-y-4 p-4" aria-label="Table viewer">
      <div className="flex flex-wrap items-center gap-3">
        <div className="seg !p-0.5 !rounded-lg max-w-full overflow-x-auto" role="tablist" aria-label="Table">
          {TABLES.map((t) => <button key={t.id} role="tab" aria-selected={name === t.id} onClick={() => { setName(t.id); setSort(undefined); setQ(''); setPage(1) }} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md whitespace-nowrap">{t.label}</button>)}
        </div>
        <label className="relative ml-auto min-w-[12rem] max-w-xs flex-1"><span className="sr-only">Search this table</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
          <input className="field !pl-9 !min-h-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Search" maxLength={60} /></label>
      </div>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead className="bg-sunken text-left">
            <tr>{data?.columns.map((c) => (
              <th key={c.name} className="p-2.5 align-top font-medium" aria-sort={sort === c.name ? (desc ? 'descending' : 'ascending') : 'none'}>
                <button className="inline-flex items-center gap-1 capitalize hover:text-brand" onClick={() => th(c.name)}>{c.name}{sort === c.name && (desc ? <ArrowDown size={13} /> : <ArrowUp size={13} />)}</button>
                <div className="mt-1 flex flex-wrap gap-1 text-[0.68rem] font-normal text-muted"><span className="chip !py-0 !px-1.5 !text-[0.68rem]">{KIND[c.kind]}</span><span>{pctTxt(c.missing, 0)} missing</span></div>
              </th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data?.rows.map((r, i) => <tr key={i}>{data.columns.map((c) => <td key={c.name} className={`p-2.5 ${c.kind === 'number' ? 'num text-right' : ''} ${c.name === 'reference' ? 'font-mono text-xs' : ''}`}>{c.name === 'amount' ? rupees0(Number(r[c.name]) * 100) : String(r[c.name] ?? '')}</td>)}</tr>)}
            {data && data.rows.length === 0 && <tr><td className="p-6 text-center text-muted" colSpan={8}>{data.total === 0 && !q ? 'This table was not provided.' : 'Nothing matches.'}</td></tr>}
          </tbody>
        </table>
      </div>
      {data && <Pager page={page} pages={Math.ceil(data.total / data.page_size)} total={data.total} onChange={setPage} />}
    </section>
  )
}

function Dictionary() {
  const { ds } = useBizCtx()
  const first = useBiz<ExploreTable>(() => bizApi.exploreTable(ds, { name: 'payments', page_size: 1 }), `dict-${ds}`).data?.rows[0]
  const rows = DICTIONARY.filter(([c]) => !first || c in first)
  return (
    <section className="card p-4" aria-labelledby="dict">
      <h2 id="dict" className="mb-3 text-lg font-semibold">What each column means</h2>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm"><thead className="bg-sunken text-left text-muted"><tr><th className="p-2.5 font-medium">Column</th><th className="p-2.5 font-medium">Meaning</th><th className="p-2.5 font-medium">Example</th></tr></thead>
          <tbody className="divide-y divide-line">{rows.map(([c, t]) => <tr key={c}><td className="p-2.5 font-medium capitalize">{c}</td><td className="p-2.5">{t}</td><td className="p-2.5 font-mono text-xs">{first && first[c] != null ? (c === 'amount' ? rupees0(Number(first[c]) * 100) : String(first[c])) : ''}</td></tr>)}</tbody></table>
      </div>
    </section>
  )
}

function Explorer() {
  const { ds } = useBizCtx()
  const { data: e } = useBiz(() => bizApi.eda(ds), `eda-${ds}`)
  if (!e) return <div className="space-y-4"><div className="skeleton h-72" /><div className="skeleton h-72" /></div>
  const tot = e.status.reduce((n, s) => n + s.count, 0) || 1
  const share = (s: string) => (e.status.find((x) => x.status === s)?.count ?? 0) / tot
  const peak = e.by_hour.reduce((m, h) => (h.count > m.count ? h : m), e.by_hour[0])
  const topBand = e.amount.reduce((m, a) => (a.count > m.count ? a : m), e.amount[0])
  const noOrder = e.missing.find((m) => m.column === 'order')?.missing ?? 0
  const top = [...e.factors].filter((f) => f.count >= 30).sort((a, b) => b.rate - a.rate)[0]
  const H = 240
  const STATUS_LABEL: Record<string, string> = { success: 'Received', failed: 'Failed', pending: 'Pending', reversed: 'Reversed' }
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard compact title={`Most payments are ${topBand.band} rupees.`} alt={`Payments by amount: ${e.amount.map((a) => `${a.band} ${a.count}`).join(', ')}.`}>
          <ResponsiveContainer width="100%" height={H}><BarChart data={e.amount} margin={{ left: 0, right: 8, top: 8 }}><XAxis {...AX} dataKey="band" interval={0} tick={{ fontSize: 10, fill: 'var(--muted)' }} /><YAxis {...AX} width={44} /><Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} /><Bar dataKey="count" name="Payments" fill="#1F4FD8" radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title={`Payments peak around ${hour12(peak.hour)}.`} alt={`Payments by hour of day. Peak at ${hour12(peak.hour)} with ${peak.count} payments.`}>
          <ResponsiveContainer width="100%" height={H}><BarChart data={e.by_hour} margin={{ left: 0, right: 8, top: 8 }}><XAxis {...AX} dataKey="hour" tickFormatter={hour12} interval={2} /><YAxis {...AX} width={44} /><Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} labelFormatter={(h) => hour12(Number(h))} /><Bar dataKey="count" name="Payments" fill="#1F4FD8" radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title={`${pctTxt(share('success'), 0)} of payments were received; ${pctTxt(share('failed'), 0)} failed.`} alt={`Payments by status: ${e.status.map((s) => `${STATUS_LABEL[s.status] ?? s.status} ${s.count}`).join(', ')}.`}>
          <ResponsiveContainer width="100%" height={H}><BarChart data={e.status.map((s) => ({ ...s, name: STATUS_LABEL[s.status] ?? s.status }))} layout="vertical" margin={{ left: 0, right: 48 }}><XAxis {...AX} type="number" hide /><YAxis {...AX} type="category" dataKey="name" width={70} tick={{ fontSize: 12, fill: 'var(--ink)' }} /><Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} /><Bar dataKey="count" name="Payments" radius={4} isAnimationActive={false}>{e.status.map((s) => <Cell key={s.status} fill={{ success: '#0E8A7E', failed: '#C2304A', pending: '#B7700B', reversed: '#94A3B8' }[s.status] ?? '#94A3B8'} />)}<LabelList dataKey="count" position="right" style={{ fontSize: 11, fill: 'var(--ink)' }} /></Bar></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title={noOrder > 0.01 ? `${pctTxt(noOrder, 0)} of payments have no order, so they cannot be matched.` : 'Almost every payment has its order.'} alt={`Share of empty cells per payments column: ${e.missing.map((m) => `${m.column} ${pctTxt(m.missing, 0)}`).join(', ')}.`}>
          <ResponsiveContainer width="100%" height={H}><BarChart data={e.missing.map((m) => ({ ...m, pct: Math.round(m.missing * 1000) / 10 }))} layout="vertical" margin={{ left: 0, right: 40 }}><XAxis {...AX} type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} /><YAxis {...AX} type="category" dataKey="column" width={70} tick={{ fontSize: 12, fill: 'var(--ink)' }} interval={0} /><Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} formatter={(v) => [`${v}%`, 'Missing']} /><Bar dataKey="pct" name="Missing" fill="#94A3B8" radius={4} isAnimationActive={false}><LabelList dataKey="pct" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: 'var(--ink)' }} /></Bar></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title="Daily payments over the period." alt={`Payments per day, ${e.trend.length} days.`}>
          <ResponsiveContainer width="100%" height={H}><LineChart data={e.trend} margin={{ left: 0, right: 8, top: 8 }}><XAxis {...AX} dataKey="date" tickFormatter={shortDate} minTickGap={28} /><YAxis {...AX} width={52} /><Tooltip {...TT} labelFormatter={(l) => shortDate(String(l))} formatter={(v, n) => [n === 'Amount' ? rupeesCompact(Number(v) * 100) : Number(v).toLocaleString('en-IN'), n]} /><Line name="Payments" dataKey="count" stroke="#1F4FD8" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title={top ? `${top.factor} is flagged most often: ${pctTxt(top.rate, 0)}.` : 'How often each kind of payment is flagged.'} tip="Share of payments the fraud model marked Check or Fraud." alt={`Share flagged by factor: ${e.factors.map((f) => `${f.factor} ${pctTxt(f.rate, 1)}`).join(', ')}.`}>
          <ResponsiveContainer width="100%" height={H + 90}><BarChart data={e.factors.map((f) => ({ ...f, pct: Math.round(f.rate * 1000) / 10 }))} layout="vertical" margin={{ left: 0, right: 40 }}><XAxis {...AX} type="number" tickFormatter={(v) => `${v}%`} /><YAxis {...AX} type="category" dataKey="factor" width={118} tick={{ fontSize: 11, fill: 'var(--ink)' }} interval={0} /><Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} formatter={(v) => [`${v}%`, 'Flagged']} /><Bar dataKey="pct" name="Flagged" fill="#1F4FD8" radius={4} isAnimationActive={false}><LabelList dataKey="pct" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 10, fill: 'var(--ink)' }} /></Bar></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard compact title="Amount, hour and weekday barely move together." tip="Blue: rise together. Amber: one rises as the other falls. Near zero: no link." alt={`Correlation between ${e.corr.labels.join(', ')}.`}>
          <div className="overflow-x-auto" style={{ minHeight: H }}>
            <div className="grid min-w-[360px] gap-[3px]" style={{ gridTemplateColumns: `5.5rem repeat(${e.corr.labels.length}, minmax(0, 1fr))` }}>
              <span />{e.corr.labels.map((l) => <span key={l} className="text-center text-[11px] text-muted">{l}</span>)}
              {e.corr.matrix.map((row, i) => (
                <div key={e.corr.labels[i]} className="contents"><span className="self-center text-xs text-muted">{e.corr.labels[i]}</span>
                  {row.map((v, j) => <span key={j} className="num grid h-10 place-items-center rounded text-[11px]" style={{ background: CORR_COLOR(v) }} title={`${e.corr.labels[i]} vs ${e.corr.labels[j]}: ${v}`}>{v.toFixed(2)}</span>)}</div>
              ))}
            </div>
          </div>
        </ChartCard>
      </div>

      <section className="card p-5" aria-labelledby="means">
        <h2 id="means" className="mb-2 text-lg font-semibold">What this means for missing money</h2>
        <ul className="list-disc space-y-1.5 pl-5">
          <li>{pctTxt(share('failed') + share('pending'), 1)} of payments failed or are still pending. That is money you may not have received.</li>
          <li>{noOrder > 0.01 ? `${pctTxt(noOrder, 0)} of payments have no order attached, so they cannot be matched to a sale.` : 'Payments have their orders attached, so most can be matched to a sale.'}</li>
          <li>{pctTxt(e.base_rate, 1)} of payments look risky. Reversed payments ({pctTxt(share('reversed'), 1)}) are also money coming back out.</li>
        </ul>
        <Link to="/reconciliation" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">See missing money <ArrowRight size={14} /></Link>
      </section>
    </div>
  )
}

export default function DataPage() {
  const [tab, setTab] = useState<'add' | 'explore'>('add')
  const { meta } = useBizCtx()
  return (
    <div className="space-y-5">
      <PageHeader
        title="My data"
        answer={meta ? <>Showing <b className="num">{meta.counts.transactions.toLocaleString('en-IN')}</b> payments from {meta.source === 'sample' ? 'the sample business' : 'your files'}. Add yours, or explore what is here.</> : 'Loading…'}
      />
      <div className="seg !p-0.5 !rounded-lg w-fit" role="tablist" aria-label="My data">
        <button role="tab" aria-selected={tab === 'add'} onClick={() => setTab('add')} className="!min-h-9 !px-4 !rounded-md">Add your data</button>
        <button role="tab" aria-selected={tab === 'explore'} onClick={() => setTab('explore')} className="!min-h-9 !px-4 !rounded-md"><Database size={15} className="mr-1.5 inline" aria-hidden />Data explorer</button>
      </div>
      {tab === 'add' ? <AddData /> : <><Viewer /><Dictionary /><Explorer /></>}
    </div>
  )
}
