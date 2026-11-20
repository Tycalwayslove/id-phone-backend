import { client, result, type Schema } from './client'
import type { operations } from './schema'

// 用户查询走 POST /admin/users/search：手机号放请求体，不进 URL 和访问日志
export type UserFilters = Omit<Schema['AdminUserSearchIn'], 'cursor' | 'limit'>
export type OrderFilters = NonNullable<operations['admin_orders_list']['parameters']['query']>
export type ReceiptFilters = NonNullable<operations['admin_applications_list']['parameters']['query']>
export type AuditFilters = NonNullable<operations['admin_audit_logs']['parameters']['query']>
export type NotifyFilters = NonNullable<operations['admin_notify_tasks_list']['parameters']['query']>
export type SpecFilters = NonNullable<operations['admin_specs_list']['parameters']['query']>
export type ProviderSpecFilters = NonNullable<operations['admin_provider_specs_list']['parameters']['query']>
export type RouteRuleFilters = NonNullable<operations['admin_route_rules_list']['parameters']['query']>

export const adminApi = {
  login: async (body: Schema['AdminLoginIn']) =>
    result(await client.POST('/api/v1/admin/auth/login', { body })),
  logout: async () =>
    result(await client.POST('/api/v1/admin/auth/logout')),
  me: async (signal?: AbortSignal) =>
    result(await client.GET('/api/v1/admin/me', { signal })),

  statsOverview: async (signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/stats/overview', { signal })),
  notifyTasks: async (query: NotifyFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/notify-tasks', { params: { query }, signal })),

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
  resolveReceiptReview: async (app_no: string, body: Schema['AdminManualReviewIn']) =>
    result(await client.POST('/api/v1/admin/receipt-applications/{app_no}/manual-review', { params: { path: { app_no } }, body })),

  plans: async (signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/plans', { signal })),
  createPlan: async (body: Schema['AdminPlanCreateIn']) =>
    result(await client.POST('/api/v1/admin/plans', { body })),
  updatePlan: async (code: string, body: Schema['AdminPlanUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/plans/{code}', { params: { path: { code } }, body })),

  specs: async (query: SpecFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/specs', { params: { query }, signal })),
  specRegion: async (region_code: string, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/spec-regions/{region_code}', { params: { path: { region_code } }, signal })),
  createSpec: async (body: Schema['AdminSpecCreateIn']) =>
    result(await client.POST('/api/v1/admin/specs', { body })),
  updateSpec: async (code: string, body: Schema['AdminSpecUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/specs/{code}', { params: { path: { code } }, body })),

  providers: async (signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/providers', { signal })),
  updateProvider: async (code: string, body: Schema['AdminProviderUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/providers/{code}', { params: { path: { code } }, body })),
  syncProviderSpecs: async (code: string, auto_publish: boolean) =>
    result(await client.POST('/api/v1/admin/providers/{code}/sync-specs', { params: { path: { code }, query: { auto_publish } } })),
  providerSpecs: async (query: ProviderSpecFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/provider-specs', { params: { query }, signal })),
  routeRules: async (query: RouteRuleFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/route-rules', { params: { query }, signal })),
  createProviderSpec: async (body: Schema['AdminProviderSpecCreateIn']) =>
    result(await client.POST('/api/v1/admin/provider-specs', { body })),
  updateProviderSpec: async (entry_id: number, body: Schema['AdminProviderSpecUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/provider-specs/{entry_id}', { params: { path: { entry_id } }, body })),
  deleteProviderSpec: async (entry_id: number) =>
    result(await client.DELETE('/api/v1/admin/provider-specs/{entry_id}', { params: { path: { entry_id } } })),
  createRouteRule: async (body: Schema['AdminRouteRuleCreateIn']) =>
    result(await client.POST('/api/v1/admin/route-rules', { body })),
  updateRouteRule: async (rule_id: number, body: Schema['AdminRouteRuleUpdateIn']) =>
    result(await client.PATCH('/api/v1/admin/route-rules/{rule_id}', { params: { path: { rule_id } }, body })),
  deleteRouteRule: async (rule_id: number) =>
    result(await client.DELETE('/api/v1/admin/route-rules/{rule_id}', { params: { path: { rule_id } } })),

  adminAccounts: async (query: { cursor: string | null }, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/admin-users', { params: { query }, signal })),
  createAdminAccount: async (body: Schema['AdminAccountCreateIn']) =>
    result(await client.POST('/api/v1/admin/admin-users', { body })),
  disableAdminAccount: async (admin_id: number) =>
    result(await client.POST('/api/v1/admin/admin-users/{admin_id}/disable', { params: { path: { admin_id } } })),
  updateAdminRole: async (admin_id: number, body: Schema['AdminAccountRoleIn']) =>
    result(await client.PATCH('/api/v1/admin/admin-users/{admin_id}/role', { params: { path: { admin_id } }, body })),
  resetAdminPassword: async (admin_id: number) =>
    result(await client.POST('/api/v1/admin/admin-users/{admin_id}/reset-password', { params: { path: { admin_id } } })),

  auditLogs: async (query: AuditFilters, signal: AbortSignal) =>
    result(await client.GET('/api/v1/admin/audit-logs', { params: { query }, signal })),
}
