import type { components } from '../api/schema'

type PlanOut = components['schemas']['PlanOut']

export function unlockablePlans(plans: readonly PlanOut[]): PlanOut[] {
  return plans.filter(({ price_fen, benefits }) => (
    price_fen > 0 && benefits.attach_to_parent === 0 && benefits.storage_days > 0
  ))
}

export function pickRecommendedPlan(plans: readonly PlanOut[], supportsReceipt: boolean): PlanOut | undefined {
  let lowest: PlanOut | undefined
  let preferred: PlanOut | undefined
  for (const plan of plans) {
    if (!lowest || plan.price_fen < lowest.price_fen) lowest = plan
    if ((plan.benefits.receipt_quota > 0) === supportsReceipt &&
        (!preferred || plan.price_fen < preferred.price_fen)) {
      preferred = plan
    }
  }
  return preferred ?? lowest
}

export function describeBenefits(plan: PlanOut): string[] {
  const { storage_days, spec_change, photo_scope, attach_to_parent, receipt_quota, resubmit_limit } = plan.benefits
  const points: string[] = []
  if (storage_days > 0) {
    const duration = storage_days % 365 === 0 ? `${storage_days / 365} 年` : `${storage_days} 天`
    points.push(`云端保管 ${duration}，换手机也能下载`)
  }
  if (spec_change === 1) points.push('同一张照片免费换其他尺寸')
  if (photo_scope === 0 && attach_to_parent === 0) points.push('期内不限照片张数')
  if (receipt_quota > 0) {
    const resubmits = resubmit_limit > 0 ? `，被驳回免费重提 ${resubmit_limit} 次` : ''
    points.push(`含 ${receipt_quota} 次官方回执${resubmits}`)
  }
  return points
}
