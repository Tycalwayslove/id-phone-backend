import { useRef, useState } from 'react'
import { Button, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { reportSubscriptions } from '../../api/notify'
import { readPublicEnv } from '../../components/PrivateDomainCard/publicEnv'
import { handleError } from '../../utils/errors'

const templates = [...new Set([
  readPublicEnv(() => process.env.TARO_APP_TPL_RECEIPT_COMPLETED),
  readPublicEnv(() => process.env.TARO_APP_TPL_RECEIPT_REJECTED),
  readPublicEnv(() => process.env.TARO_APP_TPL_ENTITLEMENT_EXPIRING)
].filter(Boolean))]

export default function ReminderSettings() {
  const submitting = useRef(false)
  const [busy, setBusy] = useState(false)

  if (templates.length === 0 || Taro.getEnv() !== Taro.ENV_TYPE.WEAPP) return null

  async function subscribe(): Promise<void> {
    if (submitting.current) return
    submitting.current = true
    setBusy(true)
    try {
      // 微信要求在点击事件中直接调用，中间不能等待网络请求。
      const result = await Taro.requestSubscribeMessage({ tmplIds: templates, entityIds: [] })
      const statuses = result as unknown as Record<string, unknown>
      const accepted = templates.filter((id) => statuses[id] === 'accept')
      if (accepted.length === 0) {
        await Taro.showToast({ title: '未允许消息提醒', icon: 'none' })
        return
      }

      const { quota } = await reportSubscriptions(accepted)
      const recorded = accepted.filter((id) => (quota[id] ?? 0) > 0).length
      if (recorded === templates.length) {
        await Taro.showToast({ title: '已记录消息提醒授权', icon: 'success' })
      } else {
        const title = recorded > 0 ? `已记录 ${recorded} 项提醒授权` : '服务暂未登记这些提醒模板'
        await Taro.showToast({ title, icon: 'none' })
      }
    } catch (error) {
      await handleError(error)
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <Button className='cell me-reminders' disabled={busy} onClick={() => void subscribe()}>
      <Text>消息提醒设置</Text>
      <Text className='cell__arrow'>&gt;</Text>
    </Button>
  )
}
