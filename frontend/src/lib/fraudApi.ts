// /api/fraud: score one payment with every model, and the stored evaluation of those models.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

export interface Payment {
  amount: number
  hour: number
  product: string
  network: string
  instrument: string
  email_domain: string | null
  device_type: string
  os: string
  browser: string
  distance_km: number | null
  account_age_days: number | null
  customer_prior_payments: number
  customer_usual_amount: number | null
  hours_since_last_payment: number | null
  payments_last_hour: number
  payments_last_24h: number
  new_device: boolean
  devices_seen: number
  accounts_on_device_7d: number
  prior_fraud: number
  threshold_preset: Preset
}
export type Preset = 'fewer_false_alarms' | 'balanced' | 'catch_more'

export interface Reason {
  feature: string
  effect: number
  text: string
}
export interface ScoreOut {
  probability: number
  percent: number
  band: 'low' | 'medium' | 'high'
  flagged: boolean
  headline: string
  advice: string
  typical_rate_percent: number
  times_more_than_typical: number | null
  reasons_up: Reason[]
  reasons_down: Reason[]
  warning_signs: string[]
  models: Record<string, { probability: number; flagged: boolean }>
  best_model: string
  gauge: { low_to_medium: number; medium_to_high: number }
  model_version: string
  trained_on: string
}

export interface AtThreshold {
  threshold: number
  tp: number
  fp: number
  fn: number
  tn: number
  precision: number
  recall: number
  f1: number
  accuracy: number
  fpr: number
  flags_per_1000: number
  false_alarms_per_1000: number
  fraud_value_caught?: number
  fraud_value_missed?: number
  cost?: number
}
export type Curve = [number, number][]
export interface ModelResult {
  name: string
  kind: string
  val: { roc_auc: number; pr_auc: number; brier: number }
  test: { roc_auc: number; pr_auc: number; brier: number }
  test_brier_calibrated?: number
  threshold: number
  at_threshold: AtThreshold
  ci95: Record<'roc_auc' | 'pr_auc' | 'precision' | 'recall' | 'f1', [number, number]>
  curves: { roc: Curve; pr: Curve }
  train_seconds?: number
  ms_per_1000_predictions?: number
}
export interface Zone {
  payments: number
  share: number
  fraud: number
  fraud_rate: number
  share_of_all_fraud: number
  fraud_value: number
}
export interface Triage {
  target: number
  block_threshold: number
  check_threshold: number
  block: Zone
  check: Zone
  approve: Zone
  block_precision: number
  block_recall: number
  flag_recall: number
  approve_clean_rate: number
  test_payments: number
}
export interface Fold {
  period: number
  n: number
  fraud: number
  roc_auc: number
  pr_auc: number
  base_rate: number
}
export interface Experiment {
  tag: string
  rows: number
  n_features: number
  base_rate: number
  train_rows: number
  train_rows_before_sampling: number
  val_rows: number
  test_rows: number
  test_fraud: number
  base_rate_test: number
  models: Record<string, ModelResult>
  walk_forward: Record<string, { folds: Fold[]; pr_auc_mean: number; pr_auc_std: number; roc_auc_mean: number; roc_auc_std: number }>
  best: string
  presets: Record<Preset, AtThreshold>
  triage?: Triage
  calibration: { before: { predicted: number; actual: number; n: number }[]; after: { predicted: number; actual: number; n: number }[] }
  sweep: { threshold: number; precision: number; recall: number; f1: number; flags_per_1000: number; false_alarms_per_1000: number; cost: number }[]
  importance?: { feature: string; label: string; mean_abs_shap: number }[]
  learning_curve?: { fraction: number; train_rows: number; pr_auc: number; roc_auc: number }[]
  examples?: { kind: string; transaction_id: number; actual_fraud: number; pattern?: string; inputs: Partial<Payment> }[]
  synthetic?: boolean
  registry?: { version: string; trained_at: string; git_commit: string; dataset: string; train_window: string; calibration_window: string; test_window: string; train_rows: number; best_name: string }
}
export interface Insights {
  rows: number
  fraud: number
  base_rate: number
  days: number
  fraud_amount_median: number
  genuine_amount_median: number
  by_product: { group: string; n: number; fraud_rate: number }[]
  by_device: { group: string; n: number; fraud_rate: number }[]
  by_email: { group: string; n: number; fraud_rate: number }[]
  by_os: { group: string; n: number; fraud_rate: number }[]
  amount: { band: string; share_fraud: number; share_genuine: number; fraud_rate: number }[]
  hours: { hour: number; fraud_rate: number; n: number }[]
  weekly: { week: number; fraud_rate: number; n: number }[]
  flags: { flag: string; label: string; n: number; fraud_rate: number; lift: number }[]
  rule_score: { warning_signs: number; n: number; fraud_rate: number }[]
}
export interface FraudPattern {
  pattern: string
  name: string
  rows: number
  share: number
  median_amount: number
  new_device: number
  burst: number
  night: number
  far: number
  new_account: number
  shared_device: number
  anon_email: number
  prior_fraud: number
  test_rows: number
  caught: number | null
}
export interface Eda {
  rows: number
  fraud: number
  genuine: number
  columns: number
  missing: { column: string; missing: number }[]
  hist: { feature: string; label: string; missing_fraud: number; missing_genuine: number; bins: { bin: string; fraud: number; genuine: number }[] }[]
  corr: { features: string[]; matrix: number[][] }
  fraud_corr: { feature: string; r: number }[]
  patterns: FraudPattern[]
}
export interface RealCheck {
  rows: number
  test_rows: number
  base_rate_test: number
  best: string
  triage?: Triage
  models: Record<string, { name: string; test: { roc_auc: number; pr_auc: number }; at_threshold: { precision: number; recall: number; f1: number } }>
}
export interface Overview {
  generated: string
  review_cost: number
  synthetic?: boolean
  ieee: Experiment
  ieee_research?: Experiment
  ulb?: Experiment
  insights: Insights
  eda?: Eda
  real_check?: RealCheck | null
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const b = await r.json().catch(() => null)
    throw new Error((b && (b.detail?.[0]?.msg ?? b.detail)) || `Request failed (${r.status})`)
  }
  return r.json() as Promise<T>
}

export const fraudApi = {
  overview: () => fetch(`${BASE}/fraud/overview`).then((r) => j<Overview>(r)),
  score: (p: Payment) => fetch(`${BASE}/fraud/score`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) }).then((r) => j<ScoreOut>(r)),
}

export const DEFAULT_PAYMENT: Payment = {
  amount: 120, hour: 14, product: 'W', network: 'visa', instrument: 'debit', email_domain: 'gmail.com', device_type: 'mobile', os: 'Android', browser: 'Chrome',
  distance_km: null, account_age_days: null, customer_prior_payments: 5, customer_usual_amount: 100, hours_since_last_payment: 48, payments_last_hour: 0,
  payments_last_24h: 0, new_device: false, devices_seen: 1, accounts_on_device_7d: 0, prior_fraud: 0, threshold_preset: 'balanced',
}

// The training data (IEEE-CIS) is in US dollars. The screen shows rupees at one fixed rate;
// the form converts rupees back to dollars only when calling the model.
export const INR_PER_USD = 88
/** Full rupee amount with Indian digit grouping, from a dollar value: 1234 -> "₹1,08,592". */
export const inr = (usd: number) => `₹${Math.round(usd * INR_PER_USD).toLocaleString('en-IN')}`
/** Short rupee amount for chart axes and labels, from a dollar value: crore (Cr), lakh (L) or thousand (k). */
export function inrShort(usd: number): string {
  const r = usd * INR_PER_USD
  const a = Math.abs(r)
  const fmt = (v: number) => (v >= 10 ? Math.round(v).toString() : v.toFixed(1).replace(/\.0$/, ''))
  return a >= 1e7 ? `₹${fmt(r / 1e7)} Cr` : a >= 1e5 ? `₹${fmt(r / 1e5)} L` : a >= 1e3 ? `₹${fmt(r / 1e3)}k` : `₹${Math.round(r)}`
}
/** Re-label a dollar amount band such as "25-50", "<25" or "1k+" in rupees. */
export const bandInr = (band: string) => band.replace(/(\d+(?:\.\d+)?)(k?)/g, (_, n: string, k: string) => inrShort(Number(n) * (k ? 1000 : 1)).replace('₹', '')).replace(/^/, '₹').replace('₹<', '<₹')
