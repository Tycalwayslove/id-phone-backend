import { client, result, type Schema } from './client'
import type { operations } from './schema'

// 用户查询走 POST /admin/users/search：手机号放请求体，不进 URL 和访问日志
export type UserFilters = Omit<Schema['AdminUserSearchIn'], 'cursor' | 'limit'>
export type OrderFilters = NonNullable<operations['admin_orders_list']['parameters']['query']>
export type ReceiptFilters = NonNullable<operations['admin_applications_list']['parameters']['query']>
export type AuditFilters = NonNullable<operations['admin_audit_logs']['parameters']['query']>

export const adminApi = {
  login: async (body: Schema['AdminLoginIn']) =>
    result(await client.POST('/api/v1/admin/auth/login', { body })),
  logout: async () =>
    result(await client.POST('/api/v1/admin/auth/logout')),
  me: async (signal?: AbortSignal) =>
    result(await client.GET('/api/v1/admin/me', { signal })),

  users: async (filters: UserFilters & { cursor: string | null }, signal: AbortSignal) =>
    result(await client.POST('/api/v1/admin/users/search', { body: { limit: 20, ...filters }, signal })),
  user: async (user_id: number, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/users/{user_id}', { params: { path: { user_id } }, signal })),
  orders: async (query: OrderFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/orders', { params: { query }, signal })),
  order: async (order_no: string, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/orders/{order_no}', { params: { path: { order_no } }, signal })),
  refund: async (order_no: string, body: Schema['AdminRefundIn']) =>
    result(await client.POST('/api/v1/admin/orders/{order_no}/refunds', { params: { path: { order_no } }, body })),

  receipts: async (query: ReceiptFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/receipt-applications', { params: { query }, signal })),
  receipt: async (app_no: string, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/receipt-applications/{app_no}', { params: { path: { app_no } }, signal })),
  cancelReceipt: async (app_no: string) =>
    result(await client.POST('/api/v1/admin/receipt-applications/{app_no}/cancel', { params: { path: { app_no } } })),

  plans: async (signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/plans', { signal })),
  createPlan: async (body: Schema['AdminPlanCreateIn']) =>
    result(await client.POST('/api/v1/admin/plans', { body })),
  updatePlan: async (code: string, body: Schema['AdminPlanUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/plans/{code}', { params: { path: { code } }, body })),

  specs: async (query: { cursor: string | null }, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/specs', { params: { query }, signal })),
  createSpec: async (body: Schema['AdminSpecCreateIn']) =>
    result(await client.POST('/api/v1/admin/specs', { body })),
  updateSpec: async (code: string, body: Schema['AdminSpecUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/specs/{code}', { params: { path: { code } }, body })),

  providers: async (signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/providers', { signal })),
  updateProvider: async (code: string, body: Schema['AdminProviderUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/providers/{code}', { params: { path: { code } }, body })),

  auditLogs: async (query: AuditFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/audit-logs', { params: { query }, signal })),
}
