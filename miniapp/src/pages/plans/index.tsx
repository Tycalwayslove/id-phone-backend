import { useEffect, useMemo, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { getEntitlement } from '../../api/entitlements'
import { listPlans } from '../../api/plans'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PlanCard from '../../components/PlanCard'
import usePurchase from '../../hooks/usePurchase'
import { handleError } from '../../utils/errors'
import { goBack, toInt } from '../../utils/nav'
import { unlockablePlans } from '../../utils/plans'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']

/** 套餐页。支持购买、加购和指定权益续费。 */
export default function Plans() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const parentId = toInt(params.parent_entitlement_id)
  const renewId = toInt(params.renew_entitlement_id)
  const renewing = renewId !== undefined

  const [plans, setPlans] = useState<PlanOut[] | null>(null)
  const [selected, setSelected] = useState('')
  const { paying, hasPendingOrder, purchase } = usePurchase({
    notifyCancellation: true,
    onPaid: async () => {
      await Taro.showToast({ title: renewing ? '续费成功' : '购买成功', icon: 'success' })
      await new Promise<void>((resolve) => setTimeout(resolve, 800))
      await goBack()
    }
  })

  useEffect(() => {
    let active = true
    if (renewId !== undefined) void Taro.setNavigationBarTitle({ title: '选择续费套餐' })
    Promise.all([listPlans(), renewId === undefined ? null : getEntitlement(renewId)])
      .then(([list, entitlement]) => {
        if (!active) return
        if (entitlement) {
          const visible = entitlement.can_renew
            ? unlockablePlans(list).filter((plan) => (
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
    if (!current || paying) return
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
    await purchase(renewId !== undefined
      ? { plan_code: current.code, renew_entitlement_id: renewId }
      : {
        plan_code: current.code,
        photo_id: needPhoto ? photoId : undefined,
        parent_entitlement_id: isAddon ? parentId : undefined
      })
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
              if (!paying && !hasPendingOrder) setSelected(p.code)
            }}
          />
        ))}
      </View>
      <Text className='hint plans-note'>
        {renewing ? '续费只延长原权益的保管期，从原到期时间与支付时间中较晚的时间起算。' : '支付成功后权益立即生效。'}
      </Text>
      <View className='bottom-bar'>
        <Button block type='primary' loading={paying} disabled={!current} onClick={buy}>
          {hasPendingOrder ? '确认支付结果' : renewing ? '立即续费' : '立即购买'}
        </Button>
      </View>
    </PageContainer>
  )
}
