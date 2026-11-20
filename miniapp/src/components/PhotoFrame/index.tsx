import type { ComponentProps } from 'react'
import { View } from '@tarojs/components'

export default function PhotoFrame({ className, children, ...props }: ComponentProps<typeof View>) {
  return (
    <View className={className ? `photo-frame ${className}` : 'photo-frame'} {...props}>
      {children}
      <View className='photo-frame__corner photo-frame__corner--top-right' />
      <View className='photo-frame__corner photo-frame__corner--bottom-left' />
    </View>
  )
}
