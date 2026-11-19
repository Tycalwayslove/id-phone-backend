import type { components } from './schema'
import { request } from './client'

type EntitlementOut = components['schemas']['EntitlementOut']

/** active 有效（默认）/ expired 已到期或撤销 / all 全部 */
export type EntitlementStatus = 'active' | 'expired' | 'all'

export function listEntitlements(status: EntitlementStatus = 'active'): Promise<EntitlementOut[]> {
  return request<EntitlementOut[]>({ path: '/entitlements', query: { status } })
}

export function getEntitlement(id: number): Promise<EntitlementOut> {
  return request<EntitlementOut>({ path: `/entitlements/${id}` })
}
