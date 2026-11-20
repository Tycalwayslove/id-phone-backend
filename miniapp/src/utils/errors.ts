/** 错误码 → 提示文案与处理方式 */
import Taro from '@tarojs/taro'
import { ApiError } from '../api/client'
import { PAGES, navigate, switchTab } from './nav'

type ErrorAction = 'none' | 'renew' | 'buy' | 'buy_addon' | 'contact' | 'retry' | 'retake'

export interface ErrorInfo {
  message: string
  action: ErrorAction
  /** 弹窗里的动作按钮文案 */
  actionText?: string
}

/** 出错时的上下文，用于动作跳转带参数 */
export interface ErrorContext {
  photoId?: number
  parentEntitlementId?: number
  onRetake?: () => Promise<unknown>
}

const TABLE: Record<string, ErrorInfo> = {
  PHOTO_ACCESS_EXPIRED: { message: '照片保管期已过，续费后可继续下载和换规格', action: 'renew', actionText: '去续费' },
  ENTITLEMENT_EXPIRED: { message: '权益已过期，续费后可继续使用', action: 'renew', actionText: '去续费' },
  SPEC_CHANGE_NOT_ALLOWED: { message: '当前套餐不支持更换规格，可购买支持换规格的套餐', action: 'buy', actionText: '查看套餐' },
  QUOTA_EXHAUSTED: { message: '回执次数已用完，可以购买加办回执', action: 'buy_addon', actionText: '购买加办' },
  RESUBMIT_LIMIT_REACHED: { message: '重新提交次数已用完，请联系客服处理', action: 'contact', actionText: '联系客服' },
  PHONE_ALREADY_BOUND: { message: '这个手机号已绑定其他账号，请联系客服', action: 'contact', actionText: '联系客服' },
  ONE_PERSON_MISMATCH: { message: '该权益仅限本人使用，请使用办理人本人的证件信息', action: 'none' },
  RECEIPT_NOT_SUPPORTED: { message: '这个规格暂不支持办理回执', action: 'none' },
  PROVIDER_UNAVAILABLE: { message: '回执通道暂时不可用，请稍后再试', action: 'retry' },
  APPLICATION_NOT_RESUBMITTABLE: { message: '当前状态不能重新提交', action: 'none' },
  PLAN_NOT_AVAILABLE: { message: '这个套餐暂不可购买', action: 'none' },
  ORDER_NOT_PAYABLE: { message: '订单当前不能支付，请重新下单', action: 'none' },
  ORDER_NOT_CANCELLABLE: { message: '订单当前不能取消', action: 'none' },
  PHOTO_NOT_READY: { message: '照片检测中，请稍后再试', action: 'retry' },
  PHOTO_REJECTED: { message: '照片未通过内容检测，请更换照片', action: 'retake', actionText: '重新拍摄' },
  UPLOAD_INVALID: { message: '照片需为 JPEG 或 PNG，不超过 10MB，且宽高不小于 300 像素', action: 'none' },
  UPLOAD_NOT_FOUND: { message: '上传的文件已过期，请重新选择照片', action: 'none' },
  PHOTO_NOT_FOUND: { message: '照片不存在或已删除', action: 'none' },
  SPEC_NOT_FOUND: { message: '规格不存在', action: 'none' },
  APPLICATION_NOT_FOUND: { message: '回执申请不存在', action: 'none' },
  ORDER_NOT_FOUND: { message: '订单不存在', action: 'none' },
  IDEMPOTENCY_CONFLICT: { message: '请求正在处理，请稍候，不要重复点击', action: 'none' },
  RATE_LIMITED: { message: '操作太频繁，请稍后再试', action: 'retry' },
  ACCOUNT_DISABLED: { message: '账号已被停用，请联系客服', action: 'contact', actionText: '联系客服' },
  WECHAT_LOGIN_FAILED: { message: '微信登录失败，请重试', action: 'retry' },
  AUTH_REQUIRED: { message: '请先登录', action: 'retry' },
  AUTH_INVALID: { message: '登录已失效，请重试', action: 'retry' },
  DB_UNAVAILABLE: { message: '服务暂时不可用，请稍后再试', action: 'retry' },
  INTERNAL_ERROR: { message: '服务开小差了，请稍后再试', action: 'retry' },
  NETWORK_ERROR: { message: '网络不太好，请检查网络后重试', action: 'retry' }
}

/** 把任意异常转成可展示的信息；未知错误码用服务端返回的 message */
export function describeError(err: unknown): ErrorInfo {
  if (err instanceof ApiError) {
    const hit = TABLE[err.code]
    if (hit) return hit
    return { message: err.message || '操作失败，请稍后再试', action: 'none' }
  }
  return { message: '操作失败，请稍后再试', action: 'none' }
}

/** 提示错误；需要用户操作时通过弹窗引导 */
export async function handleError(err: unknown, ctx: ErrorContext = {}): Promise<void> {
  const info = describeError(err)
  if (info.action === 'none' || info.action === 'retry' || !info.actionText) {
    await Taro.showToast({ title: info.message, icon: 'none', duration: 2500 })
    return
  }
  const res = await Taro.showModal({
    title: '提示',
    content: info.message,
    confirmText: info.actionText,
    cancelText: '知道了'
  })
  if (!res.confirm) return
  if (info.action === 'renew') {
    await navigate(PAGES.entitlements)
  } else if (info.action === 'buy') {
    await navigate(PAGES.plans, { photo_id: ctx.photoId })
  } else if (info.action === 'buy_addon') {
    await navigate(PAGES.plans, {
      photo_id: ctx.photoId,
      parent_entitlement_id: ctx.parentEntitlementId
    })
  } else if (info.action === 'contact') {
    // 客服按钮（openType=contact）在“我的”页
    await switchTab(PAGES.me)
  } else if (info.action === 'retake') {
    if (!ctx.onRetake) {
      await navigate(PAGES.specs)
      return
    }
    try {
      await ctx.onRetake()
    } catch (e) {
      await Taro.showToast({ title: describeError(e).message, icon: 'none', duration: 2500 })
    }
  }
}

/** 是否用户主动取消（选图、支付、授权弹窗点取消） */
export function isUserCancel(err: unknown): boolean {
  const msg = typeof err === 'object' && err !== null ? (err as { errMsg?: unknown }).errMsg : undefined
  return typeof msg === 'string' && msg.indexOf('cancel') > -1
}
