import { Button, Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { formatMm } from '../../utils/format'
import './index.scss'

type SpecOut = components['schemas']['SpecOut']

interface Props {
  spec: SpecOut
  onClick: () => void
}

export default function SpecTile({ spec, onClick }: Props) {
  const size = formatMm(spec.width_mm, spec.height_mm)
  return (
    <Button className='spec-tile' onClick={onClick}>
      <Text className='spec-tile__name'>{spec.name}</Text>
      <View className='spec-tile__meta'>
        {size ? <Text>{size}</Text> : null}
        {spec.supports_receipt ? <Text className='spec-tile__receipt'>可办回执</Text> : null}
      </View>
    </Button>
  )
}
