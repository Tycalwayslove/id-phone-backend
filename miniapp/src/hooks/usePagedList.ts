import { useCallback, useEffect, useRef, useState } from 'react'

interface Page<T> {
  items: T[]
  next_cursor?: string | null
}

interface Options {
  /** 是否在 deps 变化时自动加载第一页，默认 true；用 useDidShow 手动刷新的页面传 false */
  auto?: boolean
}

/** 游标分页列表：reload 重新加载第一页，loadMore 加载下一页 */
export function usePagedList<T>(
  fetchPage: (cursor: string | null) => Promise<Page<T>>,
  deps: ReadonlyArray<unknown>,
  options: Options = {}
) {
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage
  const [items, setItems] = useState<T[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const cursorRef = useRef<string | null>(null)
  const busyRef = useRef(false)
  const seqRef = useRef(0)

  const reload = useCallback(async () => {
    const seq = ++seqRef.current
    busyRef.current = true
    setLoading(true)
    setError(null)
    try {
      const page = await fetchRef.current(null)
      if (seq !== seqRef.current) return
      setItems(page.items)
      cursorRef.current = page.next_cursor ?? null
      setHasMore(page.next_cursor != null)
      setLoaded(true)
    } catch (e) {
      if (seq === seqRef.current) setError(e)
    } finally {
      if (seq === seqRef.current) {
        busyRef.current = false
        setLoading(false)
      }
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (busyRef.current || !cursorRef.current) return
    const seq = seqRef.current
    busyRef.current = true
    setLoading(true)
    try {
      const page = await fetchRef.current(cursorRef.current)
      if (seq !== seqRef.current) return
      setItems((prev) => prev.concat(page.items))
      cursorRef.current = page.next_cursor ?? null
      setHasMore(page.next_cursor != null)
    } catch (e) {
      if (seq === seqRef.current) setError(e)
    } finally {
      if (seq === seqRef.current) {
        busyRef.current = false
        setLoading(false)
      }
    }
  }, [])

  const auto = options.auto !== false
  useEffect(() => {
    if (auto) void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, reload, ...deps])

  return { items, setItems, loading, loaded, hasMore, error, reload, loadMore }
}
