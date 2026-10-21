import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, BookOpenCheck, FileUp, Plus, X } from 'lucide-react'
import { rupees0, useBiz } from '../lib/biz'
import { bizApi } from '../lib/bizApi'
import { isUtr, parseBankCsv, useAddedPayments, type AddedPayment } from '../lib/bankLocal'
import { useBizCtx } from '../lib/bizctx'
import { Pager } from '../components/bizui'
import { EmptyState, PageHeader, StatusChip } from '../components/shell'

const PAGE = 12
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const today = () => new Date().toISOString().slice(0, 10)

/** Small manual form: bank reference, amount, date, customer. */
function AddForm({ initial, onSave, onClose }: { initial: Partial<AddedPayment>; onSave: (p: AddedPayment) => void; onClose: () => void }) {
  const [utr, setUtr] = useState(initial.utr ?? '')
  const [amount, setAmount] = useState(initial.amount ? String(initial.amount) : '')
  const [date, setDate] = useState(initial.date ?? today())
  const [customer, setCustomer] = useState(initial.customer ?? '')
  const ok = isUtr(utr) && Number(amount) > 0 && !!date
  return (
    <div className="fixed inset-0 z-50 grid place-items-end sm:place-items-center" role="dialog" aria-modal="true" aria-label="Add a payment">
      <button className="absolute inset-0 bg-black/30" aria-label="Close" onClick={onClose} />
      <form className="relative w-full max-w-md space-y-4 rounded-t-2xl bg-surface p-5 shadow-xl sm:rounded-2xl" onSubmit={(e) => { e.preventDefault(); if (ok) onSave({ utr: utr.trim(), amount: Number(amount), date, customer: customer.trim() }) }}>
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Add a payment</h2><button type="button" className="grid size-9 place-items-center rounded-full hover:bg-sunken" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <label className="block"><span className="mb-1 block text-sm font-medium">Bank reference (UTR)</span>
          <input className="field font-mono" inputMode="numeric" maxLength={12} value={utr} onChange={(e) => setUtr(e.target.value.replace(/\D/g, ''))} placeholder="12 digits" autoFocus={!initial.utr} /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="mb-1 block text-sm font-medium">Amount (₹)</span><input className="field num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} /></label>
          <label className="block"><span className="mb-1 block text-sm font-medium">Date</span><input type="date" className="field" value={date} max={today()} onChange={(e) => setDate(e.target.value)} /></label>
        </div>
        <label className="block"><span className="mb-1 block text-sm font-medium">Customer (optional)</span><input className="field" value={customer} maxLength={40} onChange={(e) => setCustomer(e.target.value)} /></label>
        <button className="btn btn-primary w-full" disabled={!ok}>Add payment</button>
      </form>
    </div>
  )
}

/** Money in your bank: payments received, plus the ones you added or imported. */
export default function LedgerPage() {
  const { ds, meta } = useBizCtx()
  const added = useAddedPayments(ds)
  const [params, setParams] = useSearchParams()
  const [src, setSrc] = useState<'all' | 'bank' | 'added'>('all')
  const [page, setPage] = useState(1)
  const [note, setNote] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const adding = params.get('add') === '1'
  const closeForm = () => setParams({}, { replace: true })

  const bank = useBiz(() => bizApi.transactions(ds, { tab: 'received', page: src === 'added' ? 1 : page, page_size: PAGE }), `bank-${ds}-${src}-${page}`).data
  const addedSum = added.items.reduce((n, p) => n + p.amount * 100, 0)
  const total = (bank?.total ?? 0) + added.items.length
  const sum = (bank?.sum_amount_paise ?? 0) + addedSum

  type Row = { key: string; date: string; utr: string; amount: number; source: 'Bank' | 'Added by you'; customer?: string }
  const fromAdded: Row[] = added.items.map((p) => ({ key: 'a' + p.utr, date: p.date, utr: p.utr, amount: p.amount * 100, source: 'Added by you', customer: p.customer }))
  const fromBank: Row[] = (bank?.rows ?? []).map((r) => ({ key: r.tid, date: r.ts, utr: r.tid, amount: r.amount_paise, source: 'Bank' }))
  const rows: Row[] = src === 'bank' ? fromBank : src === 'added' ? fromAdded.slice((page - 1) * PAGE, page * PAGE) : [...(page === 1 ? fromAdded.slice(0, 5) : []), ...fromBank]
  const pages = src === 'added' ? Math.ceil(added.items.length / PAGE) : Math.ceil((bank?.total ?? 0) / PAGE)
  const SEGS = [['all', 'All'], ['bank', 'Bank'], ['added', 'Added by you']] as const

  async function importCsv(f: File | undefined) {
    if (!f) return
    const { rows: ok, skipped } = parseBankCsv(await f.text())
    if (ok.length) added.add(ok)
    setNote(ok.length ? `Added ${ok.length} payment${ok.length === 1 ? '' : 's'}${skipped ? `, skipped ${skipped} without a 12-digit reference, an amount or a date` : ''}.` : 'No usable rows. The file needs the columns: UTR, amount, date, customer.')
    if (file.current) file.current.value = ''
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Money in your bank"
        answer={<><b className="num">{total.toLocaleString('en-IN')}</b> payments, <b className="num">{rupees0(sum)}</b>, last updated {meta ? fmtDate(meta.data_end) : '…'}.</>}
        action={
          <div className="flex flex-wrap gap-2">
            <input ref={file} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Import CSV file" onChange={(e) => importCsv(e.target.files?.[0])} />
            <button className="btn btn-ghost !min-h-10 text-sm" onClick={() => file.current?.click()}><FileUp size={16} /> Import CSV</button>
            <button className="btn btn-primary !min-h-10 text-sm" onClick={() => setParams({ add: '1' }, { replace: true })}><Plus size={16} /> Add payment</button>
          </div>
        }
      />
      {note && <p className="rounded-xl bg-sunken px-4 py-2 text-sm" role="status">{note}</p>}

      <section className="card space-y-4 p-4" aria-label="Bank record">
        <div className="seg !p-0.5 !rounded-lg w-fit max-w-full overflow-x-auto" role="tablist" aria-label="Source">
          {SEGS.map(([id, label]) => <button key={id} role="tab" aria-selected={src === id} onClick={() => { setSrc(id); setPage(1) }} className="!min-h-8 !px-3 !text-[0.8rem] !rounded-md whitespace-nowrap">{label}</button>)}
        </div>
        {rows.length === 0 && bank ? (
          <EmptyState icon={BookOpenCheck} title="Nothing here yet." sub="Add a payment you saw in your bank, or import a CSV." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-sm">
              <thead className="bg-sunken text-left text-muted"><tr><th className="p-2.5 font-medium">Date</th><th className="p-2.5 font-medium">Bank reference (UTR)</th><th className="p-2.5 text-right font-medium">Amount</th><th className="p-2.5 font-medium">Source</th></tr></thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td className="whitespace-nowrap p-2.5">{fmtDate(r.date)}</td>
                    <td className="p-2.5 font-mono text-xs">{r.utr}{r.customer ? <span className="ml-2 font-sans text-muted">{r.customer}</span> : null}</td>
                    <td className="num p-2.5 text-right font-medium">{rupees0(r.amount)}</td>
                    <td className="p-2.5"><StatusChip status={r.source === 'Bank' ? 'neutral' : 'ok'}>{r.source}</StatusChip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={src === 'added' ? added.items.length : src === 'bank' ? bank?.total ?? 0 : total} onChange={setPage} />
      </section>

      <Link to="/transactions" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">Next: Payments <ArrowRight size={14} /></Link>
      {adding && <AddForm initial={{ utr: params.get('utr') ?? '', amount: Number(params.get('amount')) || undefined }} onClose={closeForm} onSave={(p) => { added.add([p]); setNote(`Added ${rupees0(p.amount * 100)} (${p.utr}).`); setSrc('all'); closeForm() }} />}
    </div>
  )
}
