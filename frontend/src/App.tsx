import { useEffect, useState, type ComponentType } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Gauge, BellRing, BookOpenCheck, CircleHelp, Database, Ellipsis, GitCompareArrows, LayoutDashboard, ListChecks, MessageSquareWarning, ReceiptText, ScanLine, X } from 'lucide-react'
import { useBusy } from './lib/biz'
import CheckPage from './pages/CheckPage'
import LedgerPage from './pages/LedgerPage'
import MessagesPage from './pages/MessagesPage'
import AboutPage from './pages/AboutPage'
import DashboardPage from './pages/DashboardPage'
import FraudPage from './pages/FraudPage'
import PaymentsPage from './pages/PaymentsPage'
import MissingMoneyPage from './pages/MissingMoneyPage'
import RiskPage from './pages/RiskPage'
import ActionsPage from './pages/ActionsPage'
import DataPage from './pages/DataPage'
import { LogoMark } from './components/Illustration'
import { useBizCtx } from './lib/bizctx'

type Icon = ComponentType<{ size?: number; className?: string }>
interface Item {
  to: string
  icon: Icon
  label: string
  end?: boolean
  soon?: boolean
}

/** Where the numbers come from. Tapping it opens My data. */
function DataChip() {
  const { meta } = useBizCtx()
  if (!meta) return <span className="skeleton h-7 w-24" />
  const n = meta.counts.transactions.toLocaleString('en-IN')
  const label = `${meta.source === 'sample' ? 'Sample data' : 'Your data'} · ${n} payments`
  return (
    <Link to="/data" className="chip !py-1.5" aria-label={label}>
      <span className="dot" />
      <span className="hidden min-[420px]:inline">{label}</span>
      <span className="min-[420px]:hidden">{meta.source === 'sample' ? 'Sample' : 'Yours'} · {n}</span>
    </Link>
  )
}

function Brand({ onDark = false }: { onDark?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight whitespace-nowrap">
      <LogoMark size={34} onDark={onDark} />
      <span className="text-[1.02rem] hidden min-[400px]:inline">UPI Safety Check</span>
    </Link>
  )
}

function SideLink({ i }: { i: Item }) {
  if (i.soon)
    return (
      <span aria-disabled="true" className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-muted/60 cursor-not-allowed">
        <i.icon size={18} /> {i.label}
        <span className="ml-auto chip !text-[0.62rem] !py-0.5 !px-1.5 ">next</span>
      </span>
    )
  return (
    <NavLink to={i.to} end={i.end} className={({ isActive }) => `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${isActive ? 'bg-brand-soft text-brand' : 'text-ink/80 hover:bg-black/5'}`}>
      <i.icon size={18} /> {i.label}
    </NavLink>
  )
}

export default function App() {
  return <Shell />
}

function Shell() {
  const busy = useBusy()
  const { name, meta: bmeta } = useBizCtx()

  const [more, setMore] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => setMore(false), [pathname])

  const main: Item[] = [
    { to: '/', icon: Gauge, label: 'Fraud check', end: true },
    { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/check', icon: ScanLine, label: 'Check a payment' },
    { to: '/ledger', icon: BookOpenCheck, label: 'Bank record' },
  ]
  const business: Item[] = [
    { to: '/transactions', icon: ReceiptText, label: 'Payments' },
    { to: '/reconciliation', icon: GitCompareArrows, label: 'Missing money' },
    { to: '/risk', icon: BellRing, label: 'Risk alerts' },
    { to: '/actions', icon: ListChecks, label: 'Action center' },
    { to: '/data', icon: Database, label: 'My data' },
  ]
  const help: Item[] = [
    { to: '/messages', icon: MessageSquareWarning, label: 'Scam messages' },
    { to: '/about', icon: CircleHelp, label: 'How it works' },
  ]
  // Phone bar: five slots, the Fraud check button in the middle, everything else under "More".
  const mobile: Item[] = [main[1], business[0], main[0], business[2]]
  const inMore = [main[2], main[3], business[1], business[3], business[4], ...help]
  const tab = ({ isActive }: { isActive: boolean }) => `flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium min-h-14 ${isActive ? 'text-brand' : 'text-muted'}`
  const section = 'px-3 mt-5 mb-1.5 text-xs font-medium text-muted'

  return (
    <div className="min-h-dvh">
      {busy && <div className="toploader" role="progressbar" aria-label="Loading" />}
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 btn btn-primary">
        {'Skip to content'}
      </a>

      {/* desktop: full-height sidebar */}
      <aside className="side hidden lg:flex fixed inset-y-0 left-0 w-60 flex-col px-3 py-4 z-30">
        <div className="px-2 pb-3"><Brand /></div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto">
          <p className={section + ' !mt-2'}>{'Counter'}</p>
          <div className="space-y-0.5">{main.map((i) => <SideLink key={i.to} i={i} />)}</div>
          <p className={section}>{'Business analysis'}</p>
          <div className="space-y-0.5">{business.map((i) => <SideLink key={i.to} i={i} />)}</div>
          <p className={section}>{'Help'}</p>
          <div className="space-y-0.5">{help.map((i) => <SideLink key={i.to} i={i} />)}</div>
        </nav>
        <div className="mt-3 rounded-xl border border-line bg-surface p-3">
          <Link to="/data" className="flex items-center gap-3 lift" title="Change business name or upload your data">
            <span className="grid place-items-center size-9 rounded-full bg-brand text-on-brand font-semibold">{name.slice(0, 1).toUpperCase()}</span>
            <div className="min-w-0">
              <div className="text-sm font-semibold leading-tight truncate">{name}</div>
              <div className="text-xs text-muted truncate">{bmeta?.source === 'upload' ? 'Your uploaded data' : 'Sample data'}</div>
            </div>
          </Link>
        </div>
      </aside>

      <div className="lg:pl-60 flex flex-col min-h-dvh">
        <header className="sticky top-0 z-20 navbar border-b border-line">
          <div className="flex items-center justify-between gap-3 px-4 sm:px-6 lg:px-8 h-14">
            <div className="lg:hidden"><Brand /></div>
            <div className="hidden lg:block text-sm text-muted">{name}</div>
            <div className="flex items-center gap-2">
              <DataChip />
            </div>
          </div>
        </header>

        <main id="main" className="flex-1 w-full max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 py-6 pb-32 lg:pb-10">
          <Routes>
            <Route path="/" element={<FraudPage />} />
            <Route path="/fraud" element={<Navigate to="/" replace />} />
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/check" element={<CheckPage />} />
            <Route path="/ledger" element={<LedgerPage />} />
            <Route path="/transactions" element={<PaymentsPage />} />
            <Route path="/reconciliation" element={<MissingMoneyPage />} />
            <Route path="/risk" element={<RiskPage />} />
            <Route path="/why" element={<Navigate to="/risk" replace />} />
            <Route path="/actions" element={<ActionsPage />} />
            <Route path="/models" element={<Navigate to="/messages" replace />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/safety" element={<Navigate to="/" replace />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="/message" element={<Navigate to="/messages" replace />} />
            <Route path="/number" element={<Navigate to="/" replace />} />
            <Route path="/handle" element={<Navigate to="/" replace />} />
            <Route path="/report" element={<Navigate to="/" replace />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/business" element={<Navigate to="/" replace />} />
            <Route path="/verify" element={<Navigate to="/check" replace />} />
            <Route path="/statement" element={<Navigate to="/ledger" replace />} />
            <Route path="*" element={<DashboardPage />} />
          </Routes>
        </main>
      </div>

      {more && (
        <div className="lg:hidden fixed inset-0 z-40" role="dialog" aria-label="More pages">
          <button className="absolute inset-0 bg-black/30" aria-label="Close" onClick={() => setMore(false)} />
          <div className="absolute inset-x-0 bottom-0 rounded-t-2xl bg-surface p-3 pb-24 shadow-xl">
            <div className="flex items-center justify-between px-2 pb-2"><span className="font-semibold">More</span>
              <button className="grid size-9 place-items-center rounded-full hover:bg-black/5" aria-label="Close" onClick={() => setMore(false)}><X size={18} /></button>
            </div>
            <div className="grid grid-cols-2 gap-1">{inMore.map((i) => <SideLink key={i.to} i={i} />)}</div>
          </div>
        </div>
      )}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-50 navbar border-t border-line pb-[env(safe-area-inset-bottom)]" aria-label="Main">
        <ul className="grid grid-cols-5 items-end">
          {mobile.map((n, i) => (
            <li key={n.to} className="flex justify-center">
              {i === 2 ? (
                <NavLink to={n.to} end className="flex flex-col items-center gap-1 text-[11px] font-medium text-brand pb-1.5" aria-label={n.label}>
                  <span className="fab"><n.icon size={26} /></span>
                  Fraud check
                </NavLink>
              ) : (
                <NavLink to={n.to} end={n.end} className={tab}>
                  <n.icon size={21} />
                  <span className="truncate max-w-full px-1">{n.label}</span>
                </NavLink>
              )}
            </li>
          ))}
          <li className="flex justify-center">
            <button className={tab({ isActive: more })} onClick={() => setMore((m) => !m)} aria-expanded={more}>
              <Ellipsis size={21} /><span>More</span>
            </button>
          </li>
        </ul>
      </nav>
    </div>
  )
}
