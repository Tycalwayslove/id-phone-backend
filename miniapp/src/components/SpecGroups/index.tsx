import type { ReactNode } from 'react'
import { Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import type { City } from '../../hooks/useCity'
import './index.scss'

type SpecOut = components['schemas']['SpecOut']

interface Props {
  city: City | null
  specs: SpecOut[]
  children: (specs: SpecOut[]) => ReactNode
}

export default function SpecGroups({ city, specs, children }: Props) {
  const groups = [
    { title: `${city?.name ?? ''}可办`, items: city?.code ? specs.filter((spec) => spec.region_code) : [] },
    { title: '全国通用', items: specs.filter((spec) => !spec.region_code) },
  ].filter(({ items }) => items.length > 0)

  if (!groups.length) return null
  return (
    <View className='list-gap'>
      {groups.map(({ title, items }) => (
        <View key={title}>
          <Text className='spec-group__title'>{title}</Text>
          {children(items)}
        </View>
      ))}
    </View>
  )
}
