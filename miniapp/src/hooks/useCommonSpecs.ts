import { useCallback, useEffect, useRef, useState } from 'react'
import type { components } from '../api/schema'
import { listSpecs, type SpecCategory } from '../api/specs'
import { handleError } from '../utils/errors'

type SpecOut = components['schemas']['SpecOut']

interface Options {
  category?: SpecCategory
  limit?: number
  enabled?: boolean
}

export default function useCommonSpecs(regionCode: string, { category, limit = 8, enabled = true }: Options = {}) {
  const [result, setResult] = useState<{ regionCode: string; specs: SpecOut[] }>()
  const [loading, setLoading] = useState(false)
  const request = useRef<{ regionCode: string; promise: Promise<void> } | null>(null)

  const load = useCallback(() => {
    if (request.current?.regionCode === regionCode) return request.current.promise
    setLoading(true)

    const promise = listSpecs({ category, limit, region_code: regionCode }).then(({ items }) => {
      if (request.current?.promise === promise) setResult({ regionCode, specs: items })
    }).catch((error: unknown) => {
      if (request.current?.promise === promise) throw error
    }).finally(() => {
      if (request.current?.promise === promise) {
        request.current = null
        setLoading(false)
      }
    })
    request.current = { regionCode, promise }
    return promise
  }, [category, limit, regionCode])

  useEffect(() => {
    if (!enabled) return
    void load().catch(handleError)
    return () => { request.current = null }
  }, [enabled, load])

  return { specs: result?.regionCode === regionCode ? result.specs : [], loading, load }
}
