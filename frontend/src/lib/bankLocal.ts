// Payments the merchant added by hand or imported (kept in this browser only, per dataset).
import { useCallback, useEffect, useState } from 'react'

export interface AddedPayment {
  utr: string
  amount: number // rupees
  date: string // YYYY-MM-DD
  customer: string
}
const MAX = 5000
const key = (ds: string) => `bank-added:${ds}`
const read = (ds: string): AddedPayment[] => {
  try {
    return JSON.parse(localStorage.getItem(key(ds)) ?? '[]')
  } catch {
    return []
  }
}

export function useAddedPayments(ds: string) {
  const [items, setItems] = useState<AddedPayment[]>(() => read(ds))
  useEffect(() => setItems(read(ds)), [ds])
  const save = useCallback((next: AddedPayment[]) => {
    const n = next.slice(0, MAX)
    setItems(n)
    try {
      localStorage.setItem(key(ds), JSON.stringify(n))
    } catch {
      /* storage can be blocked */
    }
  }, [ds])
  return {
    items,
    add: (p: AddedPayment[]) => save([...p, ...items.filter((o) => !p.some((x) => x.utr === o.utr))]),
    remove: (utr: string) => save(items.filter((x) => x.utr !== utr)),
  }
}

export const isUtr = (s: string) => /^\d{12}$/.test(s.trim())

/** Read a small CSV (utr, amount, date, customer; header names are matched loosely). Returns the usable rows and how many were skipped. */
export function parseBankCsv(text: string): { rows: AddedPayment[]; skipped: number } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) return { rows: [], skipped: 0 }
  const head = lines[0].split(',').map((h) => h.trim().toLowerCase())
  const at = (names: string[]) => head.findIndex((h) => names.some((n) => h.includes(n)))
  const iU = at(['utr', 'ref', 'txn']), iA = at(['amount', 'amt']), iD = at(['date', 'time']), iC = at(['customer', 'payer', 'name'])
  const rows: AddedPayment[] = []
  let skipped = 0
  for (const l of lines.slice(1)) {
    const c = l.split(',').map((x) => x.trim())
    const utr = (c[iU] ?? '').replace(/\D/g, '')
    const amount = Number((c[iA] ?? '').replace(/[₹,\s]/g, ''))
    const d = new Date(c[iD] ?? '')
    if (isUtr(utr) && amount > 0 && !Number.isNaN(d.getTime())) rows.push({ utr, amount, date: d.toISOString().slice(0, 10), customer: c[iC] ?? '' })
    else skipped++
  }
  return { rows, skipped }
}
