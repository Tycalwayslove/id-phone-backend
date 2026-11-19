import type { components } from './schema'
import { request } from './client'

type SpecPage = components['schemas']['SpecPage']
type SpecDetail = components['schemas']['SpecDetail']

export type SpecCategory = components['schemas']['SpecOut']['category']

export interface ListSpecsParams {
  category?: SpecCategory
  keyword?: string
  cursor?: string | null
  limit?: number
}

export function listSpecs(params: ListSpecsParams = {}): Promise<SpecPage> {
  return request<SpecPage>({
    path: '/specs',
    query: {
      category: params.category,
      keyword: params.keyword,
      cursor: params.cursor,
      limit: params.limit
    },
    auth: false
  })
}

export function getSpec(code: string): Promise<SpecDetail> {
  return request<SpecDetail>({ path: `/specs/${encodeURIComponent(code)}`, auth: false })
}
