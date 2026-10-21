// Client for /api/merchant/*: read-only analytics over the sample business (or, later, an uploaded dataset).
import { useEffect, useState, useSyncExternalStore } from 'react'

// How many requests are in flight right now: drives the thin loading bar across the top of the page.
let inflight = 0
const listeners = new Set<() => void>()
const bump = (d: number) => {
  inflight = Math.max(0, inflight + d)
  listeners.forEach((l) => l())
}
export const useBusy = () => useSyncExternalStore((cb) => (listeners.add(cb), () => listeners.delete(cb)), () => inflight > 0)

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

export interface Kpi {
  key: string
  label: string
  unit: 'money' | 'count' | 'bps'
  value: number | null // money in paise, bps = hundredths of a percent
  previous: number | null
  change_pct: number | null
  tone: string
  definition: string
  sub: string | null
}
export interface Overview {
  period: string
  from: string
  to: string
  data_end: string
  kpis: Kpi[]
  status_breakdown: { status: string; count: number; amount_paise: number }[]
  top_outlets: { outlet: string; confirmed_paise: number; payments: number; attempts: number; discrepancies: number }[]
  outlet_count: number
  unusual_days: { date: string; value_paise: number; typical_paise: number; direction: string; metric: string }[]
}
export interface SeriesPoint {
  date: string
  recorded_sales: number
  confirmed: number
  refunds: number
  attempts: number
  failed: number
  discrepancies: number
  alerts: number
}
export interface ActionItem {
  id: string
  kind: string
  classification: 'rule_based_discrepancy' | 'ml_risk_alert' | 'unusual_activity' | 'observation'
  title: string
  severity: 'high' | 'medium' | 'low'
  ts: string
  summary: string
  amount_at_stake_paise: number
  next_step: string
  priority: number
}
export interface BizMeta {
  id: string
  label: string
  source: 'sample' | 'upload'
  notes: string[]
  warnings: string[]
  data_start: string
  data_end: string
  counts: { transactions: number; orders: number; refunds: number; settlement_days: number; outlets: number; duplicate_rows: number }
  capabilities: { orders: boolean; settlements: boolean; risk_model: boolean; unusual_activity: boolean }
  discrepancy_counts: { total: number; by_type: Record<string, { count: number; title: string; default_severity: string }>; by_severity: Record<string, number> }
  retention: string
  outlets: string[]
}
export interface Reconciliation {
  total: number
  summary: Record<string, { count: number; title: string; amount_at_stake_paise: number }>
  matching: { orders_checked: number; payments_checked: number; refunds_checked: number; settlement_days_checked: number }
}

export const biz = {
  meta: (ds = 'sample') => get<BizMeta>(ds === 'sample' ? `/merchant/datasets/sample` : `/merchant/${ds}/meta`),
  overview: (ds: string, period: string) => get<Overview>(`/merchant/${ds}/overview?period=${period}`),
  series: (ds: string, granularity: string, days?: number) => get<{ points: SeriesPoint[] }>(`/merchant/${ds}/series?granularity=${granularity}${days ? `&days=${days}` : ''}`),
  actions: (ds: string, limit = 6) => get<{ total: number; items: ActionItem[] }>(`/merchant/${ds}/actions?limit=${limit}`),
  reconciliation: (ds: string) => get<Reconciliation>(`/merchant/${ds}/reconciliation?page_size=1`),
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      msg = (await res.json()).detail ?? msg
    } catch {
      /* not JSON */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

/** Tiny data hook: re-fetches when `key` changes; keeps the previous data on screen while loading. */
export function useBiz<T>(load: () => Promise<T>, key: string): { data: T | null; error: string | null; loading: boolean } {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true })
  useEffect(() => {
    let live = true
    let open = true
    const done = () => {
      if (open) bump(-1)
      open = false
    }
    bump(1)
    setState((s) => ({ ...s, loading: true, error: null }))
    load()
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((e: Error) => live && setState((s) => ({ ...s, error: e.message, loading: false })))
      .finally(done)
    return () => {
      live = false
      done()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

/** Whole rupees with Indian digit grouping, from paise. */
export const rupees0 = (paise: number) => '₹' + Math.round(paise / 100).toLocaleString('en-IN')
/** Compact: ₹12.4 L, ₹1.2 Cr (lakh / crore) for axes and tight spaces. */
export function rupeesCompact(paise: number): string {
  const r = paise / 100
  if (r >= 1e7) return `₹${(r / 1e7).toFixed(1)} Cr`
  if (r >= 1e5) return `₹${(r / 1e5).toFixed(1)} L`
  if (r >= 1e3) return `₹${(r / 1e3).toFixed(1)}k`
  return `₹${Math.round(r)}`
}
export const pct = (bps: number) => `${(bps / 100).toFixed(1)}%`
