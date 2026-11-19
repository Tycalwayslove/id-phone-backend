import type { components } from './schema'
import { request } from './client'

type ApplicationOut = components['schemas']['ApplicationOut']
type ApplicationPage = components['schemas']['ApplicationPage']

export function createReceipt(
  body: components['schemas']['ReceiptCreate'],
  idempotencyKey: string
): Promise<ApplicationOut> {
  return request<ApplicationOut>({
    method: 'POST',
    path: '/receipt-applications',
    body,
    idempotencyKey
  })
}

export function listReceipts(cursor?: string | null, limit?: number): Promise<ApplicationPage> {
  return request<ApplicationPage>({ path: '/receipt-applications', query: { cursor, limit } })
}

export function getReceipt(appNo: string): Promise<ApplicationOut> {
  return request<ApplicationOut>({ path: `/receipt-applications/${encodeURIComponent(appNo)}` })
}

/** 被驳回后重新提交；不传 photo_id 沿用原照片 */
export function resubmitReceipt(
  appNo: string,
  body: components['schemas']['ResubmitRequest'],
  idempotencyKey: string
): Promise<ApplicationOut> {
  return request<ApplicationOut>({
    method: 'POST',
    path: `/receipt-applications/${encodeURIComponent(appNo)}/resubmit`,
    body,
    idempotencyKey
  })
}

export function cancelReceipt(appNo: string): Promise<ApplicationOut> {
  return request<ApplicationOut>({
    method: 'POST',
    path: `/receipt-applications/${encodeURIComponent(appNo)}/cancel`
  })
}

/** 仅联调：模拟服务商出结果 */
export function devSimulateReceipt(
  appNo: string,
  body: components['schemas']['SimulateRequest']
): Promise<ApplicationOut> {
  return request<ApplicationOut>({
    method: 'POST',
    path: `/dev/receipt-applications/${encodeURIComponent(appNo)}/simulate`,
    body
  })
}
