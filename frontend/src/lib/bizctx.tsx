// Which dataset the Business pages show, what the business is called. All kept in this browser.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { biz, type BizMeta } from './biz'

interface Ctx {
  ds: string
  meta: BizMeta | null
  name: string
  setName: (n: string) => void
  useDataset: (m: BizMeta) => void
  useSample: () => void
}
const C = createContext<Ctx>({ ds: 'sample', meta: null, name: 'Demo Mart', setName: () => undefined, useDataset: () => undefined, useSample: () => undefined })

const read = (k: string): string | null => {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}
const write = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v)
  } catch {
    /* storage can be blocked */
  }
}
const defaultName = (ds: string) => (ds === 'sample' ? 'Demo Mart' : 'My business')

export function BizProvider({ children }: { children: ReactNode }) {
  const [ds, setDs] = useState<string>(() => read('biz-ds') ?? 'sample')
  const [meta, setMeta] = useState<BizMeta | null>(null)
  const [name, setNameState] = useState<string>(() => read(`biz-name-v2:${read('biz-ds') ?? 'sample'}`) ?? defaultName(read('biz-ds') ?? 'sample'))

  // Uploaded data lives in server memory and expires, so fall back to the sample if it is gone.
  useEffect(() => {
    let live = true
    biz
      .meta(ds)
      .then((m) => live && setMeta(m))
      .catch(() => {
        if (!live) return
        write('biz-ds', 'sample')
        setDs('sample')
        setNameState(read('biz-name-v2:sample') ?? defaultName('sample'))
      })
    return () => {
      live = false
    }
  }, [ds])

  const setName = useCallback(
    (n: string) => {
      const v = n.trim().slice(0, 40) || defaultName(ds)
      setNameState(v)
      write(`biz-name-v2:${ds}`, v)
    },
    [ds],
  )
  const useDataset = useCallback((m: BizMeta) => {
    write('biz-ds', m.id)
    setMeta(m)
    setDs(m.id)
    setNameState(read(`biz-name-v2:${m.id}`) ?? defaultName(m.id))
  }, [])
  const useSample = useCallback(() => {
    write('biz-ds', 'sample')
    setDs('sample')
    setNameState(read('biz-name-v2:sample') ?? defaultName('sample'))
  }, [])
  const value = useMemo(() => ({ ds, meta, name, setName, useDataset, useSample }), [ds, meta, name, setName, useDataset, useSample])
  return <C.Provider value={value}>{children}</C.Provider>
}
export const useBizCtx = () => useContext(C)
