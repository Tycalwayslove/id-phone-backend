import { useEffect, useMemo, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { ApiError } from '../../api/client'
import { createOrder, devSimulatePaid, getOrder } from '../../api/orders'
import { listPlans } from '../../api/plans'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PlanCard from '../../components/PlanCard'
import { handleError, isUserCancel } from '../../utils/errors'
import { createKeyKeeper } from '../../utils/idempotency'
import { goBack, toInt } from '../../utils/nav'
import { FAKE_PAY_ENABLED } from '../../utils/status'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']
type OrderOut = components['schemas']['OrderOut']
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

/** 轮询订单直到已支付：最多 10 次，间隔 1 秒 */
async function waitPaid(orderNo: string): Promise<boolean> {
  for (let i = 0; i < 10; i++) {
    const o: OrderOut = await getOrder(orderNo)
    if (o.status === 'paid') return true
    await sleep(1000)
  }
  return false
}

/** 套餐页。路由参数：photo_id（单张照片套餐需要）、parent_entitlement_id（加购项需要） */
export default function Plans() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const parentId = toInt(params.parent_entitlement_id)

  const [plans, setPlans] = useState<PlanOut[] | null>(null)
  const [selected, setSelected] = useState('')
  const [paying, setPaying] = useState(false)
  const keeper = useRef(createKeyKeeper())

  useEffect(() => {
    listPlans()
      .then((list) => {
        // 加购项只在带主权益参数时显示
        const visible = list.filter((p) => p.benefits.attach_to_parent !== 1 || parentId !== undefined)
        setPlans(visible)
        const first = visible.find((p) => (parentId !== undefined ? p.benefits.attach_to_parent === 1 : true))
        setSelected((first ?? visible[0])?.code ?? '')
      })
      .catch((e: unknown) => {
        setPlans([])
        return handleError(e)
      })
  }, [parentId])

  const current = useMemo(() => plans?.find((p) => p.code === selected), [plans, selected])

  async function buy(): Promise<void> {
    if (!current || paying) return
    const needPhoto = current.benefits.photo_scope === 1
    const isAddon = current.benefits.attach_to_parent === 1
    if (needPhoto && photoId === undefined) {
      await Taro.showToast({ title: '该套餐需要先选择照片，请从照片页进入购买', icon: 'none' })
      return
    }
    if (isAddon && parentId === undefined) {
      await Taro.showToast({ title: '请从“我的权益”进入加办', icon: 'none' })
      return
    }
    const photo = needPhoto ? photoId : undefined
    const parent = isAddon ? parentId : undefined
    // 同一笔购买重复点击用同一个幂等键，选项变化换新键
    const key = keeper.current.get(`${current.code}|${photo ?? ''}|${parent ?? ''}`)

    setPaying(true)
    try {
      const order = await createOrder(
        { plan_code: current.code, photo_id: photo, parent_entitlement_id: parent },
        key
      )
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
      const paid = await waitPaid(order.order_no)
      keeper.current.release()
      if (!paid) {
        await Taro.showToast({ title: '支付结果确认中，请稍后在“我的订单”查看', icon: 'none', duration: 2500 })
        return
      }
      await Taro.showToast({ title: '购买成功', icon: 'success' })
      await sleep(800)
      await goBack()
    } catch (e) {
      if (isUserCancel(e)) {
        // 用户取消支付：订单保留，再次点击沿用同一个幂等键
        await Taro.showToast({ title: '已取消支付', icon: 'none' })
      } else {
        // 明确的业务错误换新键；网络/服务端错误保留原键以便安全重试
        if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.code !== 'IDEMPOTENCY_CONFLICT') {
          keeper.current.release()
        }
        await handleError(e)
      }
    } finally {
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
        <EmptyState emoji='🧾' title='暂无可购买的套餐' />
      </PageContainer>
    )
  }

  return (
    <PageContainer withBottomBar>
      {parentId !== undefined ? <View className='hint plans-tip'>为已有权益加办回执，到期时间与主权益一致</View> : null}
      <View className='list-gap'>
        {plans.map((p) => (
          <PlanCard key={p.code} plan={p} selected={p.code === selected} onClick={() => setSelected(p.code)} />
        ))}
      </View>
      <Text className='hint plans-note'>支付成功后权益立即生效。</Text>
      <View className='bottom-bar'>
        <Button block type='primary' loading={paying} disabled={!current} onClick={buy}>
          立即购买
        </Button>
      </View>
    </PageContainer>
  )
}
