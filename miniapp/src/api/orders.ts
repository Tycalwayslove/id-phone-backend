import type { components } from './schema'
import { request } from './client'

type OrderCreatedOut = components['schemas']['OrderCreatedOut']
type OrderOut = components['schemas']['OrderOut']
type OrderPage = components['schemas']['OrderPage']

/** 下单；idempotencyKey 由调用方生成，重复点击用同一个 */
export function createOrder(
  body: components['schemas']['OrderCreateIn'],
  idempotencyKey: string
): Promise<OrderCreatedOut> {
  return request<OrderCreatedOut>({ method: 'POST', path: '/orders', body, idempotencyKey })
}

export function listOrders(cursor?: string | null, limit?: number): Promise<OrderPage> {
  return request<OrderPage>({ path: '/orders', query: { cursor, limit } })
}

export function getOrder(orderNo: string): Promise<OrderOut> {
  return request<OrderOut>({ path: `/orders/${encodeURIComponent(orderNo)}` })
}

export function cancelOrder(orderNo: string): Promise<OrderOut> {
  return request<OrderOut>({ method: 'POST', path: `/orders/${encodeURIComponent(orderNo)}/cancel` })
}

/** 仅联调：模拟支付成功（后端非 fake 模式不可用） */
export function devSimulatePaid(orderNo: string): Promise<OrderOut> {
  return request<OrderOut>({
    method: 'POST',
    path: `/dev/orders/${encodeURIComponent(orderNo)}/simulate-paid`
  })
}
