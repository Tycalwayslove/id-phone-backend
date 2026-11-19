import type { components } from './schema'
import { request } from './client'

type PlanOut = components['schemas']['PlanOut']

export function listPlans(): Promise<PlanOut[]> {
  return request<PlanOut[]>({ path: '/plans', auth: false })
}
