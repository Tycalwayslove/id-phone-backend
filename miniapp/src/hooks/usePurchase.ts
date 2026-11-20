import { useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { ApiError } from '../api/client'
import { createOrder, devSimulatePaid, getOrder } from '../api/orders'
import type { components } from '../api/schema'
import { handleError, isUserCancel } from '../utils/errors'
import { createKeyKeeper } from '../utils/idempotency'
import { PAGES, redirect } from '../utils/nav'
import { FAKE_PAY_ENABLED } from '../utils/status'

type OrderOut = components['schemas']['OrderOut']
type OrderCreateIn = components['schemas']['OrderCreateIn']
type PayParams = components['schemas']['OrderCreatedOut']['pay_params']
type SignType = 'MD5' | 'HMAC-SHA256' | 'RSA'

function str(v: unknown): string {
  return typeof v === 'string' ? v : typeof v === 'number' ? String(v) : ''
}

/** 把后端 pay_params 收窄成 requestPayment 的入参，缺字段时返回 null */
function toPayArgs(p: PayParams): Taro.requestPayment.Option | null {
  const timeStamp = str(p['timeStamp'])
  const nonceStr = str(p['nonceStr'])
  const pkg = str(p['package'])
  const paySign = str(p['paySign'])
  const rawSign = str(p['signType'])
  if (!timeStamp || !nonceStr || !pkg || !paySign) return null
  const signType: SignType = rawSign === 'MD5' || rawSign === 'HMAC-SHA256' ? rawSign : 'RSA'
  return { timeStamp, nonceStr, package: pkg, signType, paySign }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/** 轮询订单直到支付结果确认：最多 10 次，间隔 1 秒 */
async function waitForPayment(orderNo: string): Promise<OrderOut | null> {
  for (let i = 0; i < 10; i++) {
    const order = await getOrder(orderNo)
    if (order.refund_pending || order.status !== 'pending') return order
    if (i < 9) await sleep(1000)
  }
  return null
}

interface Options {
  onPaid: () => Promise<void>
  notifyCancellation?: boolean
}

/** 两个付费入口共享订单幂等键、微信支付和支付结果确认。 */
export default function usePurchase({ onPaid, notifyCancellation = false }: Options) {
  const [paying, setPaying] = useState(false)
  const [hasPendingOrder, setHasPendingOrder] = useState(false)
  const keeper = useRef(createKeyKeeper())
  const pendingOrder = useRef('')
  const payingRef = useRef(false)

  async function purchase(body: OrderCreateIn): Promise<void> {
    if (payingRef.current) return
    payingRef.current = true
    setPaying(true)
    let orderNo = pendingOrder.current
    try {
      if (!orderNo) {
        const order = await createOrder(body, keeper.current.get(JSON.stringify(body)))
        if (order.pay_params['mode'] === 'fake') {
          if (!FAKE_PAY_ENABLED) {
            await Taro.showToast({ title: '支付未配置', icon: 'none' })
            return
          }
          await devSimulatePaid(order.order_no)
        } else {
          const args = toPayArgs(order.pay_params)
          if (!args) {
            await Taro.showToast({ title: '支付参数异常，请稍后再试', icon: 'none' })
            return
          }
          await Taro.requestPayment(args)
        }
        orderNo = order.order_no
        pendingOrder.current = orderNo
        setHasPendingOrder(true)
      }
      const confirmed = await waitForPayment(orderNo)
      if (!confirmed) {
        await Taro.showToast({ title: '支付结果确认中，请稍后在“我的订单”查看', icon: 'none', duration: 2500 })
        return
      }
      keeper.current.release()
      pendingOrder.current = ''
      setHasPendingOrder(false)
      if (confirmed.refund_pending || confirmed.status === 'refunded' || confirmed.status === 'part_refunded') {
        await redirect(PAGES.orderDetail, { order_no: orderNo })
        return
      }
      if (confirmed.status === 'closed') {
        await Taro.showToast({ title: '订单已关闭，请重新下单', icon: 'none' })
        return
      }
      await onPaid()
    } catch (e) {
      if (isUserCancel(e)) {
        // 用户取消支付：订单保留，再次点击沿用同一个幂等键
        if (notifyCancellation) await Taro.showToast({ title: '已取消支付', icon: 'none' })
      } else {
        // 明确的业务错误换新键；网络/服务端错误保留原键以便安全重试
        if (!orderNo && e instanceof ApiError && e.status >= 400 && e.status < 500 && e.code !== 'IDEMPOTENCY_CONFLICT') {
          keeper.current.release()
        }
        await handleError(e)
      }
    } finally {
      payingRef.current = false
      setPaying(false)
    }
  }

  return { paying, hasPendingOrder, purchase }
}
