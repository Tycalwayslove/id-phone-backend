import { useRef, useState } from 'react'
import type { components } from '../api/schema'
import { getSpec, listSpecs } from '../api/specs'

type SpecOut = components['schemas']['SpecOut']
type SpecDetail = components['schemas']['SpecDetail']

export default function useCommonSpecs() {
  const [specs, setSpecs] = useState<SpecOut[]>([])
  const [details, setDetails] = useState<ReadonlyMap<string, SpecDetail>>(() => new Map())
  const [loading, setLoading] = useState(false)
  const request = useRef<Promise<void> | null>(null)

  function load(): Promise<void> {
    if (request.current) return request.current
    setLoading(true)
    request.current = listSpecs({ limit: 8 })
      .then(async ({ items }) => {
        setSpecs(items)
        setDetails(new Map())
        // 列表按运营排序，实际回执能力和默认底色由详情接口提供。
        await Promise.allSettled(items.map(async ({ code }) => {
          const detail = await getSpec(code)
          setDetails((current) => new Map(current).set(code, detail))
        }))
      })
      .finally(() => {
        request.current = null
        setLoading(false)
      })
    return request.current
  }

  return { specs, details, loading, load }
}
