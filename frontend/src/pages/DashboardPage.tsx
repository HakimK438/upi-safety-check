import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bar, BarChart, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, LabelList } from 'recharts'
import { ArrowRight, Banknote, CircleAlert, Hourglass, IndianRupee, RotateCcw, ShieldAlert, Undo2, X } from 'lucide-react'
import { bizApi, type DashReport } from '../lib/bizApi'
import { rupees0, rupeesCompact } from '../lib/biz'
import { useBizCtx } from '../lib/bizctx'
import { AX, ChartCard, EmptyState, KpiCard, PageHeader, TT, Waterfall, chartHeight } from '../components/shell'

const PRESETS = [
  { id: '7d', label: '7 days', days: 7, word: 'This week' },
  { id: '30d', label: '30 days', days: 30, word: 'This month' },
  { id: '90d', label: '90 days', days: 90, word: 'In the last 3 months' },
  { id: 'all', label: 'All', days: 0, word: 'So far' },
] as const
const STATUS = {
  success: { label: 'Received', color: '#0E8A7E' },
  pending: { label: 'Pending', color: '#B7700B' },
  failed: { label: 'Failed', color: '#C2304A' },
  reversed: { label: 'Reversed', color: '#94A3B8' },
} as const
const ZONE = { safe: { label: 'Safe', color: '#0E8A7E' }, check: { label: 'Check', color: '#B7700B' }, fraud: { label: 'Fraud', color: '#C2304A' } } as const
const BRAND = '#1F4FD8'
const GREY = '#94A3B8'
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** "Outlet 12" is shown as "Branch 12". */
const branchName = (s: string) => s.replace(/^Outlet\b/i, 'Branch')
const plain = (s: string) => s.replace(/\bOutlet\b/g, 'Branch')
const hour12 = (h: number) => `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`
const day0 = (iso: string) => new Date(iso + 'T00:00:00')
const shortDate = (iso: string) => day0(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const paise = (v: unknown) => rupees0(Number(v))

interface Filters {
  preset: string
  from?: string
  to?: string
  branch?: string
  status?: string
  zone?: string
  heat?: { dow: number; hour: number }
  day?: string
}

/** Slicer chip that can be removed with one click. */
function Chip({ children, onClear }: { children: ReactNode; onClear: () => void }) {
  return (
    <span className="chip chip-brand !py-1">
      {children}
      <button type="button" onClick={onClear} aria-label="Remove this filter" className="grid size-4 place-items-center rounded-full hover:bg-black/10"><X size={12} /></button>
    </span>
  )
}

export default function DashboardPage() {
  const { ds } = useBizCtx()
  const nav = useNavigate()
  const [f, setF] = useState<Filters>({ preset: '30d' })
  const [r, setR] = useState<DashReport | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let live = true
    bizApi
      .dashboard(ds, { date_from: f.from, date_to: f.to, branch: f.branch, status: f.status, zone: f.zone, hour: f.heat?.hour, dow: f.heat?.dow, day: f.day })
      .then((d) => live && (setR(d), setErr('')))
      .catch((e: Error) => live && setErr(e.message))
    return () => {
      live = false
    }
  }, [ds, f])

  const set = (patch: Partial<Filters>) => setF((p) => ({ ...p, ...patch }))
  const pick = (key: 'status' | 'zone' | 'branch', v: string) => set({ [key]: f[key] === v ? undefined : v })
  const preset = (id: string) => {
    if (!r) return
    const p = PRESETS.find((x) => x.id === id)!
    const end = day0(r.data_end)
    const from = p.days ? iso(new Date(end.getTime() - (p.days - 1) * 86_400_000)) : r.data_start
    setF((o) => ({ ...o, preset: id, from, to: r.data_end, day: undefined }))
  }
  const reset = () => setF({ preset: '30d' })
  const hasClick = !!(f.status || f.zone || f.heat || f.day || f.branch)

  // Payments page link carrying the current slicers (the Payments page reads these when it is rebuilt).
  const toPayments = (tab: string) => {
    const q = new URLSearchParams({ tab })
    if (r) (q.set('date_from', r.from), q.set('date_to', r.to))
    if (f.branch) q.set('branch', f.branch)
    return `/transactions?${q}`
  }

  if (err && !r) return <EmptyState icon={CircleAlert} title="The dashboard could not load." sub={err} />
  if (!r) return <div className="space-y-4"><div className="skeleton h-20" /><div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-32" />)}</div><div className="skeleton h-80" /></div>

  const k = r.kpis
  const spanDays = Math.round((day0(r.data_end).getTime() - day0(r.data_start).getTime()) / 86_400_000) + 1
  const spark = (key: keyof DashReport['kpis']) => r.series.map((p) => p[key])
  const word = f.day ? `On ${shortDate(f.day)}` : (PRESETS.find((p) => p.id === f.preset)?.word ?? 'In this period')
  const w = r.waterfall
  const totalPay = r.statuses.reduce((n, s) => n + s.count, 0)
  const okPay = r.statuses.find((s) => s.id === 'success')?.count ?? 0
  const failedPay = r.statuses.find((s) => s.id === 'failed')?.count ?? 0
  const zoneTotal = r.zones.safe + r.zones.check + r.zones.fraud
  const topBranch = r.branches[0]
  const peak = r.heatmap.reduce((m, c) => (c.count > m.count ? c : m), { dow: 0, hour: 0, count: 0 })

  const heatMax = Math.max(1, ...r.heatmap.map((c) => c.count))
  const heat = new Map(r.heatmap.map((c) => [`${c.dow}-${c.hour}`, c.count]))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        answer={<>{word} you sold <b className="num">{rupees0(k.sales.value)}</b>. <b className="num">{rupees0(k.in_bank.value)}</b> reached your bank. <b className="num">{rupees0(r.needs_attention_paise)}</b> needs attention.</>}
      />

      {/* slicers */}
      <section aria-label="Filters" className="card p-3 flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="seg !p-0.5 !rounded-lg" role="group" aria-label="Date range">
          {PRESETS.map((p) => (
            <button key={p.id} aria-pressed={f.preset === p.id} disabled={!!p.days && p.days > spanDays} title={p.days > spanDays ? `Your data covers only ${spanDays} days` : undefined} onClick={() => preset(p.id)} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md">{p.label}</button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-muted">From
          <input type="date" className="field !py-1 !px-2 !w-auto !text-sm" value={r.from} min={r.data_start} max={r.data_end} onChange={(e) => e.target.value && set({ preset: 'custom', from: e.target.value, to: r.to, day: undefined })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">To
          <input type="date" className="field !py-1 !px-2 !w-auto !text-sm" value={r.to} min={r.data_start} max={r.data_end} onChange={(e) => e.target.value && set({ preset: 'custom', from: r.from, to: e.target.value, day: undefined })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">Branch
          <select className="field !py-1 !px-2 !w-auto !text-sm" value={f.branch ?? ''} onChange={(e) => set({ branch: e.target.value || undefined })}>
            <option value="">All</option>
            {r.branches_all.map((b) => <option key={b} value={b}>{branchName(b)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">Status
          <select className="field !py-1 !px-2 !w-auto !text-sm" value={f.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">All</option>
            {Object.entries(STATUS).map(([id, s]) => <option key={id} value={id}>{s.label}</option>)}
          </select>
        </label>
        {(hasClick || f.preset !== '30d') && (
          <div className="flex flex-wrap items-center gap-2 w-full border-t border-line pt-3">
            <span className="text-xs text-muted">Showing</span>
            {f.day && <Chip onClear={() => set({ day: undefined })}>{shortDate(f.day)}</Chip>}
            {f.branch && <Chip onClear={() => set({ branch: undefined })}>{branchName(f.branch)}</Chip>}
            {f.status && <Chip onClear={() => set({ status: undefined })}>{STATUS[f.status as keyof typeof STATUS].label}</Chip>}
            {f.zone && <Chip onClear={() => set({ zone: undefined })}>{ZONE[f.zone as keyof typeof ZONE].label}</Chip>}
            {f.heat && <Chip onClear={() => set({ heat: undefined })}>{DAYS[f.heat.dow]} {hour12(f.heat.hour)}</Chip>}
            <button className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline" onClick={reset}><RotateCcw size={13} /> Reset</button>
            <Link className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline" to={toPayments(f.status === 'success' ? 'received' : f.zone && f.zone !== 'safe' ? 'risky' : 'all')}>
              See these {r.payments_in_view.toLocaleString('en-IN')} payments <ArrowRight size={14} />
            </Link>
          </div>
        )}
      </section>

      {/* KPI row: each card opens Payments with that tab */}
      <section aria-label="Key numbers" className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <KpiCard icon={IndianRupee} label="Sales" tip="Orders placed in this period." value={rupeesCompact(k.sales.value)} delta={k.sales.change ?? undefined} spark={spark('sales')} onClick={() => nav(toPayments('all'))} />
        <KpiCard icon={Banknote} label="In your bank" tip={r.bank_basis === 'settlements' ? 'Money that arrived in your bank account.' : 'Payments marked as received. Bank records are not split by branch.'} value={rupeesCompact(k.in_bank.value)} delta={k.in_bank.change ?? undefined} spark={spark('in_bank')} onClick={() => nav(toPayments('received'))} />
        <KpiCard icon={Undo2} label="Refunded" tip="Money you gave back to customers." value={rupeesCompact(k.refunded.value)} delta={k.refunded.change ?? undefined} spark={spark('refunded')} onClick={() => nav(toPayments('refunded'))} />
        <KpiCard icon={Hourglass} label="Not received yet" tip="Customer paid, but the money is not in your bank." value={rupeesCompact(k.not_received.value)} delta={k.not_received.change ?? undefined} spark={spark('not_received')} onClick={() => nav(toPayments('not_received'))} />
        <KpiCard icon={ShieldAlert} label="Looks risky" tip="Payments the fraud model marked Check or Fraud." value={k.risky.value.toLocaleString('en-IN')} delta={k.risky.change ?? undefined} spark={spark('risky')} onClick={() => nav(toPayments('risky'))} />
      </section>

      {/* charts */}
      <section aria-label="Charts" className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Money reaches your bank about a day after the sale." tip="Click a day to look at just that day." alt={`Daily sales against money in the bank, ${shortDate(r.from)} to ${shortDate(r.to)}. Sales ${rupees0(k.sales.value)}, in your bank ${rupees0(k.in_bank.value)}.`}>
          <ResponsiveContainer width="100%" height={chartHeight()}>
            <LineChart data={r.series} margin={{ left: 0, right: 8, top: 8 }} onClick={(e) => { const d = (e as { activeLabel?: string } | null)?.activeLabel; if (d) set({ day: f.day === d ? undefined : d }) }} style={{ cursor: 'pointer' }}>
              <XAxis {...AX} dataKey="date" tickFormatter={shortDate} minTickGap={28} />
              <YAxis {...AX} width={68} tickFormatter={(v) => rupeesCompact(v)} />
              <Tooltip {...TT} formatter={(v, n) => [paise(v), String(n)]} labelFormatter={(l) => shortDate(String(l))} />
              <Line name="Sales" dataKey="sales" stroke={BRAND} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line name="In your bank" dataKey="in_bank" stroke="#0E8A7E" strokeWidth={2} dot={false} strokeDasharray="5 3" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title={`Of ${rupees0(w.sales)} in sales, ${rupees0(w.in_bank)} reached your bank.`} tip="Sales, minus refunds, minus money not received, plus other differences, equals money in your bank." alt={`Where the money went: sales ${rupees0(w.sales)}, refunded ${rupees0(w.refunded)}, not received ${rupees0(w.not_received)}, other differences ${rupees0(w.other)}, in your bank ${rupees0(w.in_bank)}.`}>
          <Waterfall w={w} />
        </ChartCard>

        <ChartCard title={`${totalPay ? Math.round((100 * okPay) / totalPay) : 0}% of payments went through. ${failedPay} failed.`} tip="Click a slice to filter the payment charts." alt={`Payments by status: ${r.statuses.map((s) => `${STATUS[s.id].label} ${s.count}`).join(', ')}.`}>
          <div className="flex flex-wrap items-center justify-center gap-6" style={{ minHeight: chartHeight() }}>
            <div className="relative" style={{ width: 220, height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={r.statuses} dataKey="count" nameKey="id" innerRadius={66} outerRadius={104} paddingAngle={2} stroke="none" isAnimationActive={false} onClick={(d) => pick('status', String((d as unknown as { id: string }).id))} cursor="pointer">
                    {r.statuses.map((s) => <Cell key={s.id} fill={STATUS[s.id].color} opacity={!f.status || f.status === s.id ? 1 : 0.3} />)}
                  </Pie>
                  <Tooltip {...TT} formatter={(v, _n, p) => [`${Number(v).toLocaleString('en-IN')} · ${paise((p.payload as { amount_paise: number }).amount_paise)}`, STATUS[(p.payload as { id: keyof typeof STATUS }).id].label]} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 grid place-items-center text-center"><div><div className="text-2xl font-bold num">{totalPay.toLocaleString('en-IN')}</div><div className="text-xs text-muted">payments</div></div></div>
            </div>
            <ul className="space-y-1.5 text-sm">
              {r.statuses.map((s) => (
                <li key={s.id}><button type="button" onClick={() => pick('status', s.id)} aria-pressed={f.status === s.id} className="flex items-center gap-2 rounded px-1.5 py-1 hover:bg-sunken">
                  <span className="size-3 rounded-sm" style={{ background: STATUS[s.id].color }} aria-hidden /> {STATUS[s.id].label} <b className="num ml-1">{s.count.toLocaleString('en-IN')}</b>
                </button></li>
              ))}
            </ul>
          </div>
        </ChartCard>

        <ChartCard title={topBranch ? `${branchName(topBranch.id)} sold the most: ${rupees0(topBranch.amount_paise)}.` : 'No sales in this period.'} tip="Click a branch to filter the charts." alt={`Sales by branch: ${r.branches.map((b) => `${branchName(b.id)} ${rupees0(b.amount_paise)}`).join(', ')}.`}>
          <ResponsiveContainer width="100%" height={chartHeight()}>
            <BarChart data={r.branches} layout="vertical" margin={{ left: 0, right: 56 }}>
              <XAxis {...AX} type="number" hide />
              <YAxis {...AX} type="category" dataKey="id" width={78} tickFormatter={branchName} interval={0} tick={{ fontSize: 12, fill: 'var(--ink)' }} />
              <Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} formatter={(v) => paise(v)} labelFormatter={(l) => branchName(String(l))} />
              <Bar dataKey="amount_paise" name="Sales" radius={4} isAnimationActive={false} onClick={(d) => pick('branch', String((d as unknown as { id: string }).id))} cursor="pointer">
                {r.branches.map((b) => <Cell key={b.id} fill={BRAND} opacity={!f.branch || f.branch === b.id ? 1 : 0.3} />)}
                <LabelList dataKey="amount_paise" position="right" formatter={(v) => rupeesCompact(Number(v))} style={{ fontSize: 11, fill: 'var(--ink)' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title={peak.count ? `Busiest time: ${DAYS[peak.dow]} ${hour12(peak.hour)}, ${peak.count} payments.` : 'No payments in this period.'} tip="Darker means more payments. Click a cell to filter the payment charts." alt={`Payments by hour and weekday. Busiest: ${DAYS[peak.dow]} ${hour12(peak.hour)} with ${peak.count} payments.`}>
          <div className="overflow-x-auto" style={{ minHeight: chartHeight() }}>
            <div className="min-w-[560px]">
              <div className="grid gap-[3px]" style={{ gridTemplateColumns: '2.4rem repeat(24, minmax(0, 1fr))' }}>
                <span />
                {Array.from({ length: 24 }, (_, h) => <span key={h} className="text-center text-[10px] text-muted">{h % 3 === 0 ? hour12(h).replace(' ', '') : ''}</span>)}
                {DAYS.map((d, di) => (
                  <HeatRow key={d} d={d} di={di} heat={heat} max={heatMax} sel={f.heat} onPick={(h) => set({ heat: f.heat?.dow === di && f.heat.hour === h ? undefined : { dow: di, hour: h } })} />
                ))}
              </div>
            </div>
          </div>
        </ChartCard>

        <ChartCard title={zoneTotal ? `${(r.zones.check + r.zones.fraud).toLocaleString('en-IN')} of ${zoneTotal.toLocaleString('en-IN')} payments look risky.` : 'No payments in this period.'} tip="Safe: fine to accept. Check: confirm the money first. Fraud: do not hand over goods." alt={`Payments by risk: Safe ${r.zones.safe}, Check ${r.zones.check}, Fraud ${r.zones.fraud}.`}>
          <ResponsiveContainer width="100%" height={chartHeight()}>
            <BarChart data={(['safe', 'check', 'fraud'] as const).map((z) => ({ id: z, name: ZONE[z].label, count: r.zones[z] }))} margin={{ left: 0, right: 8, top: 18 }}>
              <XAxis {...AX} dataKey="name" />
              <YAxis {...AX} width={44} allowDecimals={false} />
              <Tooltip {...TT} cursor={{ fill: 'var(--sunken)' }} formatter={(v) => [Number(v).toLocaleString('en-IN'), 'Payments']} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} isAnimationActive={false} onClick={(d) => pick('zone', String((d as unknown as { id: string }).id))} cursor="pointer">
                {(['safe', 'check', 'fraud'] as const).map((z) => <Cell key={z} fill={ZONE[z].color} opacity={!f.zone || f.zone === z ? 1 : 0.3} />)}
                <LabelList dataKey="count" position="top" style={{ fontSize: 11, fill: 'var(--ink)' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>

      {/* needs attention */}
      <section aria-labelledby="needs" className="card p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 id="needs" className="text-lg font-semibold">Needs attention</h2>
          <Link to="/actions" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">All actions <ArrowRight size={14} /></Link>
        </div>
        {r.top_items.length === 0 ? (
          <p className="text-muted">Nothing needs attention in this period.</p>
        ) : (
          <ul className="divide-y divide-line">
            {r.top_items.map((x) => (
              <li key={x.id}>
                <Link to="/actions" className="flex items-center gap-3 py-2.5 hover:bg-sunken -mx-2 px-2 rounded-lg">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: x.severity === 'high' ? ZONE.fraud.color : ZONE.check.color }} aria-label={x.severity === 'high' ? 'Urgent' : 'Worth a look'} />
                  <span className="min-w-0 flex-1"><span className="block truncate font-medium">{plain(x.title)}</span><span className="block truncate text-sm text-muted">{plain(x.summary)}</span></span>
                  {x.paise > 0 && <b className="num shrink-0">{rupees0(x.paise)}</b>}
                  <ArrowRight size={15} className="shrink-0 text-muted" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/** One weekday row of the busy-hours heatmap. Each cell is a button, so the grid works with the keyboard. */
function HeatRow({ d, di, heat, max, sel, onPick }: { d: string; di: number; heat: Map<string, number>; max: number; sel?: { dow: number; hour: number }; onPick: (h: number) => void }) {
  return (
    <>
      <span className="self-center text-xs text-muted">{d}</span>
      {Array.from({ length: 24 }, (_, h) => {
        const n = heat.get(`${di}-${h}`) ?? 0
        const on = sel?.dow === di && sel.hour === h
        return (
          <button
            key={h}
            type="button"
            onClick={() => onPick(h)}
            aria-label={`${d} ${hour12(h)}: ${n} payments`}
            aria-pressed={on}
            title={`${d} ${hour12(h)}: ${n} payments`}
            className="aspect-square min-h-6 rounded-[3px] outline-offset-1 focus-visible:outline-2"
            style={{ background: n ? `color-mix(in srgb, ${BRAND} ${Math.max(14, Math.round((100 * n) / max))}%, white)` : 'var(--sunken)', outline: on ? `2px solid var(--ink)` : undefined }}
          />
        )
      })}
    </>
  )
}
