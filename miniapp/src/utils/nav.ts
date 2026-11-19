import Taro from '@tarojs/taro'

/** 页面路径集中定义，页面里不要手写路径字符串 */
export const PAGES = {
  index: '/pages/index/index',
  specs: '/pages/specs/index',
  specDetail: '/pages/spec-detail/index',
  editor: '/pages/editor/index',
  plans: '/pages/plans/index',
  receiptApply: '/pages/receipt-apply/index',
  receipts: '/pages/receipts/index',
  receiptDetail: '/pages/receipt-detail/index',
  photos: '/pages/photos/index',
  photoDetail: '/pages/photo-detail/index',
  me: '/pages/me/index',
  orders: '/pages/orders/index',
  entitlements: '/pages/entitlements/index'
} as const

type QueryValue = string | number | null | undefined

export function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  if (!query) return path
  const parts: string[] = []
  Object.keys(query).forEach((k) => {
    const v = query[k]
    if (v === undefined || v === null || v === '') return
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  })
  return parts.length ? `${path}?${parts.join('&')}` : path
}

export function navigate(path: string, query?: Record<string, QueryValue>): Promise<unknown> {
  return Taro.navigateTo({ url: buildUrl(path, query) })
}

export function redirect(path: string, query?: Record<string, QueryValue>): Promise<unknown> {
  return Taro.redirectTo({ url: buildUrl(path, query) })
}

export function switchTab(path: string): Promise<unknown> {
  return Taro.switchTab({ url: path })
}

/** 返回上一页；没有上一页时回首页 */
export function goBack(): Promise<unknown> {
  if (Taro.getCurrentPages().length > 1) return Taro.navigateBack()
  return Taro.switchTab({ url: PAGES.index })
}

/** 路由参数转整数，非法返回 undefined */
export function toInt(v: string | undefined): number | undefined {
  if (!v) return undefined
  const n = Number(v)
  return Number.isInteger(n) ? n : undefined
}

/** 路由参数可能已被框架解码，二次解码失败时原样返回 */
export function safeDecode(v: string): string {
  try {
    return decodeURIComponent(v)
  } catch {
    return v
  }
}
