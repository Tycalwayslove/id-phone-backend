import type { components } from './schema'
import { request } from './client'

type MeOut = components['schemas']['MeOut']
type OkResponse = components['schemas']['OkResponse']

export function getMe(): Promise<MeOut> {
  return request<MeOut>({ path: '/me' })
}

export function updateMe(body: components['schemas']['UpdateMeRequest']): Promise<MeOut> {
  return request<MeOut>({ method: 'PATCH', path: '/me', body })
}

/** 绑定手机号；code 来自 getPhoneNumber 按钮 */
export function bindPhone(code: string): Promise<MeOut> {
  const body: components['schemas']['BindPhoneRequest'] = { code }
  return request<MeOut>({ method: 'POST', path: '/me/phone', body })
}

/** 注销账号，会立即删除全部照片 */
export function cancelAccount(): Promise<OkResponse> {
  const body: components['schemas']['CancelAccountRequest'] = { confirm: true }
  return request<OkResponse>({ method: 'POST', path: '/me/cancel', body })
}
