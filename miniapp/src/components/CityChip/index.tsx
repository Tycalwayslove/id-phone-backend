import { Button, Text } from '@tarojs/components'
import type { City } from '../../hooks/useCity'
import './index.scss'

interface Props {
  city: City | null
  onClick: () => void
}

export default function CityChip({ city, onClick }: Props) {
  return (
    <Button className='city-chip' onClick={onClick}>
      <Text>{city?.name ?? '选择城市'}</Text>
      <Text className='city-chip__arrow' />
    </Button>
  )
}
