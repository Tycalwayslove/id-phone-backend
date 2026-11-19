import { Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { formatMm } from '../../utils/format'
import { SPEC_CATEGORY_TEXT } from '../../utils/status'
import './index.scss'

type SpecOut = components['schemas']['SpecOut']

interface Props {
  spec: SpecOut
  onClick?: () => void
}

/** 规格卡片：名称、像素/毫米尺寸、分类 */
export default function SpecCard({ spec, onClick }: Props) {
  const mm = formatMm(spec.width_mm, spec.height_mm)
  return (
    <View className='spec-card' onClick={onClick}>
      <View className='spec-card__main'>
        <Text className='spec-card__name'>{spec.name}</Text>
        <Text className='spec-card__size'>
          {spec.width_px}×{spec.height_px}px{mm ? ` · ${mm}` : ''}
        </Text>
      </View>
      <Text className={`spec-card__tag spec-card__tag--${spec.category}`}>{SPEC_CATEGORY_TEXT[spec.category]}</Text>
    </View>
  )
}
