import { useEffect, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import { listPlans } from '../../api/plans'
import type { components } from '../../api/schema'
import usePurchase from '../../hooks/usePurchase'
import { LEGAL_PAGES } from '../../pages/legal/routes'
import { describeError, handleError } from '../../utils/errors'
import { fenToYuan } from '../../utils/format'
import { navigate } from '../../utils/nav'
import { describeBenefits, pickRecommendedPlan, unlockablePlans } from '../../utils/plans'
import BottomSheet from '../BottomSheet'
import Loading from '../Loading'
import PriceText from '../PriceText'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']

interface Props {
  open: boolean
  photoId: number
  supportsReceipt: boolean
  onClose: () => void
  onPaid: () => Promise<void>
}

export default function UnlockSheet({ open, photoId, supportsReceipt, onClose, onPaid }: Props) {
  const [plans, setPlans] = useState<PlanOut[] | null>(null)
  const [selectedCode, setSelectedCode] = useState('')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const { paying, hasPendingOrder, purchase } = usePurchase({ onPaid })

  useEffect(() => {
    if (!open || plans !== null) return
    let current = true
    setError('')
    listPlans()
      .then((items) => {
        if (current) setPlans(unlockablePlans(items))
      })
      .catch((e: unknown) => {
        if (current) setError(describeError(e).message)
      })
    return () => {
      current = false
    }
  }, [open, plans, retry])

  const recommended = pickRecommendedPlan(plans ?? [], supportsReceipt)
  const selected = plans?.find((plan) => plan.code === selectedCode) ?? recommended
  const benefits = selected ? describeBenefits(selected) : []

  return (
    <BottomSheet open={open} title='保存这张照片' onClose={onClose} dismissible={!paying}>
      <View className='unlock-sheet__benefits'>
        <Text>✓ 高清无水印，可直接用于报名和办证</Text>
        {benefits.map((benefit) => <Text key={benefit}>✓ {benefit}</Text>)}
      </View>
      {error ? (
        <View className='list-gap'>
          <Text className='hint'>{error}</Text>
          <Button className='btn-native btn-native--plain' onClick={() => setRetry((n) => n + 1)}>重新加载</Button>
        </View>
      ) : null}
      {!error && plans === null ? <Loading /> : null}
      {plans?.length === 0 ? <Text className='hint'>暂时无法购买保管服务，请稍后再试。</Text> : null}
      {selected ? (
        <>
          <View className='unlock-sheet__options'>
            {plans?.map((plan) => {
              const checked = plan.code === selected.code
              return (
                <Button
                  key={plan.code}
                  className={`unlock-sheet__option${checked ? ' unlock-sheet__option--selected' : ''}`}
                  ariaLabel={`${plan.name}，${fenToYuan(plan.price_fen)}元${checked ? '，已选中' : ''}`}
                  disabled={paying || hasPendingOrder}
                  onClick={() => setSelectedCode(plan.code)}
                >
                  <View className='unlock-sheet__radio' ariaHidden />
                  <View className='unlock-sheet__option-label'>
                    <Text>{plan.name}</Text>
                    {plan.code === recommended?.code ? <Text className='unlock-sheet__recommended'>推荐</Text> : null}
                  </View>
                  <PriceText fen={plan.price_fen} size='large' />
                </Button>
              )
            })}
          </View>
          <Button
            className='btn-native'
            disabled={paying}
            loading={paying}
            onClick={() => void purchase({
              plan_code: selected.code,
              photo_id: selected.benefits.photo_scope === 1 ? photoId : undefined
            })}
          >
            {hasPendingOrder ? '确认支付结果' : `支付 ¥${fenToYuan(selected.price_fen)}`}
          </Button>
          <View className='hint unlock-sheet__agreement'>
            <Text>支付即同意</Text>
            <Text className='unlock-sheet__link' onClick={() => {
              if (!paying) void navigate(LEGAL_PAGES.agreement).catch(handleError)
            }}>《用户协议》</Text>
          </View>
        </>
      ) : null}
    </BottomSheet>
  )
}
