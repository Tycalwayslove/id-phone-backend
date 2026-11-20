import { Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import PriceText from '../PriceText'
import './index.scss'

type PlanOut = components['schemas']['PlanOut']
type Benefits = components['schemas']['PlanBenefitsOut']

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

function displayPoints(display: PlanOut['display']): string[] {
  const p = display['points']
  return Array.isArray(p) ? p.filter((x): x is string => typeof x === 'string') : []
}

/** 没有运营文案时，根据权益生成兜底卖点 */
function benefitPoints(b: Benefits): string[] {
  const list: string[] = []
  if (b.storage_days) list.push(`云端保管 ${b.storage_days} 天`)
  if (b.receipt_quota) list.push(`含 ${b.receipt_quota} 次回执`)
  if (b.resubmit_limit) list.push(`驳回可免费重提 ${b.resubmit_limit} 次`)
  if (b.spec_change === 1) list.push('期内无限换规格')
  if (b.one_person === 1) list.push('一卡一人')
  if (b.attach_to_parent === 1) list.push('加办回执，到期时间与主权益一致')
  return list
}

/** 套餐卡片：名称、价格、卖点、角标 */
export default function PlanCard({ plan, selected = false, renewal = false, onClick }: Props) {
  const badge = renewal ? '' : displayBadge(plan.display)
  const configured = displayPoints(plan.display)
  const points = renewal
    ? [`延长保管期 ${plan.benefits.storage_days} 天`]
    : configured.length ? configured : benefitPoints(plan.benefits)
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
