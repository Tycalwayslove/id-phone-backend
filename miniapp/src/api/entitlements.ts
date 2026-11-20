import type { components } from './schema'
import { request } from './client'

type EntitlementOut = components['schemas']['EntitlementOut']
type EntitlementPage = components['schemas']['EntitlementPage']

/** active 有效（默认）/ expired 已到期或撤销 / all 全部 */
export type EntitlementStatus = 'active' | 'expired' | 'all'

/** 游标分页：第一页 cursor 不传，之后传上一页的 next_cursor */
export function listEntitlements(
  status: EntitlementStatus = 'active',
  cursor?: string | null,
  limit?: number
): Promise<EntitlementPage> {
  return request<EntitlementPage>({ path: '/entitlements', query: { status, cursor, limit } })
}

export function getEntitlement(id: number): Promise<EntitlementOut> {
  return request<EntitlementOut>({ path: `/entitlements/${id}` })
}
