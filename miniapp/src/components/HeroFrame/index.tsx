import { View } from '@tarojs/components'
import PhotoFrame from '../PhotoFrame'
import './index.scss'

export default function HeroFrame() {
  return (
    <PhotoFrame className='hero-frame' ariaHidden>
      <View className='hero-frame__backdrop hero-frame__backdrop--blue' />
      <View className='hero-frame__backdrop hero-frame__backdrop--red' />
      <View className='hero-frame__head' />
      <View className='hero-frame__shoulders' />
    </PhotoFrame>
  )
}
