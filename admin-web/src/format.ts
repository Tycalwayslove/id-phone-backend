import type { Schema } from './api/client'

export const userStatus = { active: '正常', disabled: '已停用', cancelled: '已注销' } satisfies Record<Schema['AdminUserOut']['status'], string>
export const orderStatus = { pending: '待支付', paid: '已支付', closed: '已关闭', part_refunded: '部分退款', refunded: '已全额退款' } satisfies Record<Schema['AdminOrderOut']['status'], string>
export const receiptStatus = { pending: '未提交', processing: '办理中', rejected: '已驳回', completed: '已出回执', failed: '办理失败', cancelled: '已取消' } satisfies Record<Schema['AdminApplicationOut']['status'], string>
export const attemptStatus = { created: '已创建未发出', submitted: '已提交等待结果', unknown: '等待系统核对', processing: '服务商办理中', completed: '已出回执', rejected: '已驳回', failed: '提交失败', abandoned: '已放弃' } satisfies Record<Schema['AdminAttemptOut']['status'], string>
export const paymentStatus = { pending: '待支付', success: '支付成功', failed: '支付失败', closed: '已关闭' } satisfies Record<Schema['AdminPaymentOut']['status'], string>
export const refundStatus = { pending: '退款处理中', success: '退款成功', failed: '退款失败' } satisfies Record<Schema['AdminRefundOut']['status'], string>
export const planStatus = { draft: '草稿', on_sale: '在售', off_sale: '已下架' } satisfies Record<Schema['AdminPlanOut']['status'], string>
export const specStatus = { active: '上架', inactive: '下架' } satisfies Record<Schema['AdminSpecOut']['status'], string>
export const providerStatus = { enabled: '启用', disabled: '停用', circuit_open: '已熔断' } satisfies Record<Schema['AdminProviderOut']['status'], string>
export const specCategory = { receipt: '回执类', normal: '普通证件照', exam: '考试报名照' } satisfies Record<Schema['AdminSpecOut']['category'], string>
export const orderItem = { plan: '套餐', addon: '加购项', renew: '续费' } satisfies Record<Schema['OrderItemOut']['item_type'], string>
export const adminRole = { owner: '所有者', operator: '运营', finance: '财务' } satisfies Record<Schema['AdminMeOut']['role'], string>
export const adminAccountStatus = { active: '正常', disabled: '已停用' } satisfies Record<Schema['AdminAccountOut']['status'], string>
type NotifyTask = Schema['AdminNotifyTaskOut']
export const notifyStatus = { pending: '待发送', sent: '已发送', failed: '发送失败', skipped: '已跳过', cancelled: '已取消' } satisfies Record<NotifyTask['status'], string>
export const notifyEvent = { receipt_rejected: '回执驳回', receipt_completed: '回执办理完成', entitlement_expiring: '权益即将到期', receipt_expiring: '回执即将到期' } satisfies Record<NotifyTask['event'], string>
export const notifyChannel = { mini_subscribe: '小程序订阅消息', mp_template: '公众号模板消息', wecom: '企业微信', sms: '短信', voice: '语音', manual_call: '人工电话' } satisfies Record<NotifyTask['channel'], string>
export const identitySources: Record<string, string> = { wx_mini: '微信小程序', wx_mp: '微信公众号', alipay_mini: '支付宝小程序', douyin_mini: '抖音小程序', h5: '网页' }
export const paymentChannels: Record<string, string> = { wxpay: '微信支付', alipay: '支付宝', douyin_pay: '抖音支付' }

export const benefitTypes = {
  storage_days: { label: '保管天数', description: '照片可保管的天数' },
  photo_scope: { label: '照片范围', description: '1 表示单张照片，0 表示全部照片' },
  receipt_quota: { label: '回执次数', description: '可办理回执的次数' },
  resubmit_limit: { label: '免费重提次数', description: '驳回后可免费重新提交的次数' },
  spec_change: { label: '更换规格', description: '1 表示可更换规格' },
  one_person: { label: '一卡一人', description: '1 表示套餐仅限一人使用' },
  attach_to_parent: { label: '跟随主权益', description: '1 表示随主权益生效的加购项' },
}
export type BenefitType = keyof typeof benefitTypes

export const auditActions: Record<string, string> = {
  'auth.login': '登录',
  'auth.logout': '退出登录',
  'refund.create': '发起退款',
  'application.cancel': '取消回执',
  'application.manual_review': '标记回执已核对',
  'plan.create': '新建套餐',
  'plan.update': '修改套餐',
  'spec.create': '新建规格',
  'spec.update': '修改规格',
  'provider.update': '修改服务商状态',
  'provider.sync_specs': '同步服务商规格',
}
export const auditTargets: Record<string, string> = {
  order: '订单', plan: '套餐', spec: '规格', provider: '服务商', receipt_application: '回执申请', admin_session: '后台会话',
}

export function labelFor(labels: Record<string, string>, value: string) {
  return Object.hasOwn(labels, value) ? labels[value] : value
}

export function enumOptions<T extends string>(labels: Record<T, string>) {
  return (Object.keys(labels) as T[]).map((value) => ({ value, label: labels[value] }))
}

const dateTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export function dateText(value?: string | null) {
  return value ? dateTime.format(new Date(value)) : '—'
}

export function money(fen?: number | null) {
  return fen == null ? '—' : `¥${(fen / 100).toFixed(2)}`
}

export function yuanToFen(yuan: string) {
  if (!/^\d+(\.\d{1,2})?$/.test(yuan)) return null
  const [units, decimals = ''] = yuan.split('.')
  const fen = Number(units) * 100 + Number(decimals.padEnd(2, '0'))
  return Number.isSafeInteger(fen) ? fen : null
}
