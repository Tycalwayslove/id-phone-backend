import { useEffect, useMemo, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { ApiError } from '../../api/client'
import { getEntitlement } from '../../api/entitlements'
import { createOrder, devSimulatePaid, getOrder } from '../../api/orders'
import { listPlans } from '../../api/plans'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PlanCard from '../../components/PlanCard'
import { handleError, isUserCancel } from '../../utils/errors'
import { createKeyKeeper } from '../../utils/idempotency'
import { PAGES, goBack, redirect, toInt } from '../../utils/nav'
import { FAKE_PAY_ENABLED } from '../../utils/status'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']
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

/** 套餐页。支持购买、加购和指定权益续费。 */
export default function Plans() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const parentId = toInt(params.parent_entitlement_id)
  const renewId = toInt(params.renew_entitlement_id)
  const renewing = renewId !== undefined

  const [plans, setPlans] = useState<PlanOut[] | null>(null)
  const [selected, setSelected] = useState('')
  const [paying, setPaying] = useState(false)
  const [pendingOrderNo, setPendingOrderNo] = useState('')
  const keeper = useRef(createKeyKeeper())
  const payingRef = useRef(false)

  useEffect(() => {
    let active = true
    if (renewId !== undefined) void Taro.setNavigationBarTitle({ title: '选择续费套餐' })
    Promise.all([listPlans(), renewId === undefined ? null : getEntitlement(renewId)])
      .then(([list, entitlement]) => {
        if (!active) return
        if (entitlement) {
          const visible = entitlement.can_renew
            ? list.filter((plan) => (
              plan.price_fen > 0 &&
              plan.benefits.attach_to_parent === 0 &&
              plan.benefits.storage_days > 0 &&
              plan.benefits.photo_scope === (entitlement.photo_id === null ? 0 : 1)
            ))
            : []
          setPlans(visible)
          setSelected(visible[0]?.code ?? '')
          return
        }
        const visible = list.filter((p) => p.benefits.attach_to_parent !== 1 || parentId !== undefined)
        setPlans(visible)
        const first = visible.find((p) => (parentId !== undefined ? p.benefits.attach_to_parent === 1 : true))
        setSelected((first ?? visible[0])?.code ?? '')
      })
      .catch((e: unknown) => {
        if (!active) return
        setPlans([])
        return handleError(e)
      })
    return () => {
      active = false
    }
  }, [parentId, renewId])

  const current = useMemo(() => plans?.find((p) => p.code === selected), [plans, selected])

  async function buy(): Promise<void> {
    if (!current || payingRef.current) return
    const needPhoto = !renewing && current.benefits.photo_scope === 1
    const isAddon = !renewing && current.benefits.attach_to_parent === 1
    if (needPhoto && photoId === undefined) {
      await Taro.showToast({ title: '该套餐需要先选择照片，请从照片页进入购买', icon: 'none' })
      return
    }
    if (isAddon && parentId === undefined) {
      await Taro.showToast({ title: '请从“我的权益”进入加办', icon: 'none' })
      return
    }
    payingRef.current = true
    setPaying(true)
    let orderNo = pendingOrderNo
    try {
      if (!orderNo) {
        const body: OrderCreateIn = renewId !== undefined
          ? { plan_code: current.code, renew_entitlement_id: renewId }
          : {
            plan_code: current.code,
            photo_id: needPhoto ? photoId : undefined,
            parent_entitlement_id: isAddon ? parentId : undefined
          }
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
        setPendingOrderNo(orderNo)
      }
      const confirmed = await waitForPayment(orderNo)
      if (!confirmed) {
        await Taro.showToast({ title: '支付结果确认中，请稍后在“我的订单”查看', icon: 'none', duration: 2500 })
        return
      }
      keeper.current.release()
      setPendingOrderNo('')
      if (confirmed.refund_pending || confirmed.status === 'refunded' || confirmed.status === 'part_refunded') {
        await redirect(PAGES.orderDetail, { order_no: orderNo })
        return
      }
      if (confirmed.status === 'closed') {
        await Taro.showToast({ title: '订单已关闭，请重新下单', icon: 'none' })
        return
      }
      await Taro.showToast({ title: renewing ? '续费成功' : '购买成功', icon: 'success' })
      await sleep(800)
      await goBack()
    } catch (e) {
      if (isUserCancel(e)) {
        // 用户取消支付：订单保留，再次点击沿用同一个幂等键
        await Taro.showToast({ title: '已取消支付', icon: 'none' })
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

  if (plans === null) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }
  if (plans.length === 0) {
    return (
      <PageContainer>
        <EmptyState emoji='🧾' title={renewing ? '暂无适用的续费套餐' : '暂无可购买的套餐'} />
      </PageContainer>
    )
  }

  return (
    <PageContainer withBottomBar>
      {!renewing && parentId !== undefined ? (
        <View className='hint plans-tip'>为已有权益加办回执，到期时间与主权益一致</View>
      ) : null}
      <View className='list-gap'>
        {plans.map((p) => (
          <PlanCard
            key={p.code}
            plan={p}
            selected={p.code === selected}
            renewal={renewing}
            onClick={() => {
              if (!payingRef.current && !pendingOrderNo) setSelected(p.code)
            }}
          />
        ))}
      </View>
      <Text className='hint plans-note'>
        {renewing ? '续费只延长原权益的保管期，从原到期时间与支付时间中较晚的时间起算。' : '支付成功后权益立即生效。'}
      </Text>
      <View className='bottom-bar'>
        <Button block type='primary' loading={paying} disabled={!current} onClick={buy}>
          {pendingOrderNo ? '确认支付结果' : renewing ? '立即续费' : '立即购买'}
        </Button>
      </View>
    </PageContainer>
  )
}
