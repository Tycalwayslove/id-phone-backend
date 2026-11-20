import type { components, operations } from './schema'
import { request } from './client'

type SpecPage = components['schemas']['SpecPage']
type SpecDetail = components['schemas']['SpecDetail']

export type SpecCategory = components['schemas']['SpecOut']['category']

type ListSpecsParams = NonNullable<operations['specs_list']['parameters']['query']>

export function listSpecs(params: ListSpecsParams = {}): Promise<SpecPage> {
  return request<SpecPage>({
    path: '/specs',
    query: {
      category: params.category,
      keyword: params.keyword,
      region_code: params.region_code === '' ? 'national' : params.region_code,
      cursor: params.cursor,
      limit: params.limit
    },
    auth: false
  })
}

export function listSpecRegions(): Promise<components['schemas']['SpecRegionProvince'][]> {
  return request({ path: '/spec-regions', auth: false })
}

export function getSpec(code: string): Promise<SpecDetail> {
  return request<SpecDetail>({ path: `/specs/${encodeURIComponent(code)}`, auth: false })
}
