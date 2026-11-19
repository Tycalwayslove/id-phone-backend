import type { components } from './schema'
import { request } from './client'

type TemplateOut = components['schemas']['TemplateOut']
type SubscriptionQuota = components['schemas']['SubscriptionQuota']

export function listTemplates(): Promise<TemplateOut[]> {
  return request<TemplateOut[]>({ path: '/notify/templates' })
}

/** 上报用户在订阅弹窗里点了“允许”的模板 ID */
export function reportSubscriptions(accepted: string[]): Promise<SubscriptionQuota> {
  const body: components['schemas']['SubscriptionReport'] = { accepted }
  return request<SubscriptionQuota>({ method: 'POST', path: '/notify/subscriptions', body })
}
