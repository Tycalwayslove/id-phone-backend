import { Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { describeBenefits } from '../../utils/plans'
import PriceText from '../PriceText'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']

interface Props {
  plan: PlanOut
  selected?: boolean
  renewal?: boolean
  onClick?: () => void
}

/** 从运营配置的 display 里取字符串（类型未知，逐个收窄） */
function displayBadge(display: PlanOut['display']): string {
  const b = display['badge']
  return typeof b === 'string' ? b : ''
}

/** 套餐卡片：名称、价格、卖点、角标 */
export default function PlanCard({ plan, selected = false, renewal = false, onClick }: Props) {
  const badge = renewal ? '' : displayBadge(plan.display)
  const points = renewal
    ? [`延长保管期 ${plan.benefits.storage_days} 天`]
    : describeBenefits(plan)
  if (!renewal && plan.benefits.one_person === 1) points.push('一卡一人')
  if (!renewal && plan.benefits.attach_to_parent === 1) points.push('加办回执，到期时间与主权益一致')
  return (
    <View className={`plan-card${selected ? ' plan-card--selected' : ''}`} onClick={onClick}>
      {badge ? <Text className='plan-card__badge'>{badge}</Text> : null}
      <View className='plan-card__head'>
        <Text className='plan-card__name'>{plan.name}</Text>
        <PriceText fen={plan.price_fen} size='large' />
      </View>
      <View className='plan-card__points'>
        {points.map((p) => (
          <Text key={p} className='plan-card__point'>
            ✓ {p}
          </Text>
        ))}
      </View>
    </View>
  )
}
