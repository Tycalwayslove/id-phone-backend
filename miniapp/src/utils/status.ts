/** 各业务状态的中文与颜色（key 与接口枚举一致） */
import type { components } from '../api/schema'

export type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'default'
export interface StatusMeta {
  text: string
  tone: Tone
}

type S = components['schemas']

export const APPLICATION_STATUS: Record<S['ApplicationOut']['status'], StatusMeta> = {
  pending: { text: '待提交', tone: 'default' },
  processing: { text: '办理中', tone: 'primary' },
  rejected: { text: '已驳回', tone: 'danger' },
  completed: { text: '已完成', tone: 'success' },
  failed: { text: '办理失败', tone: 'danger' },
  cancelled: { text: '已取消', tone: 'default' }
}

export const ATTEMPT_STATUS: Record<S['AttemptOut']['status'], StatusMeta> = {
  created: { text: '已创建', tone: 'default' },
  submitted: { text: '已提交，等待结果', tone: 'primary' },
  unknown: { text: '提交结果确认中', tone: 'warning' },
  processing: { text: '办理中', tone: 'primary' },
  completed: { text: '办理成功', tone: 'success' },
  rejected: { text: '被驳回', tone: 'danger' },
  failed: { text: '办理失败', tone: 'danger' },
  abandoned: { text: '已放弃', tone: 'default' }
}

export const ORDER_STATUS: Record<S['OrderOut']['status'], StatusMeta> = {
  pending: { text: '待支付', tone: 'warning' },
  paid: { text: '已支付', tone: 'success' },
  closed: { text: '已关闭', tone: 'default' },
  part_refunded: { text: '部分退款', tone: 'warning' },
  refunded: { text: '已退款', tone: 'default' }
}

export function orderStatus(order: Pick<S['OrderOut'], 'status' | 'refund_pending'>): StatusMeta {
  return order.refund_pending ? { text: '退款中', tone: 'warning' } : ORDER_STATUS[order.status]
}

export const ORDER_ITEM_TYPE_TEXT: Record<S['OrderItemOut']['item_type'], string> = {
  plan: '套餐',
  addon: '加购项',
  renew: '续费'
}

export const PHOTO_SOURCE_TEXT: Record<S['PhotoOut']['source'], string> = {
  camera: '拍照',
  upload: '相册'
}

export const SPEC_CATEGORY_TEXT: Record<S['SpecOut']['category'], string> = {
  receipt: '回执',
  normal: '常用',
  exam: '考试'
}

/** 是否开启 fake 支付 / 模拟结果（仅开发） */
export const FAKE_PAY_ENABLED: boolean = process.env.TARO_APP_FAKE_PAY === '1'
