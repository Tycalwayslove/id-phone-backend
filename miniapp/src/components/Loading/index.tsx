import { Text, View } from '@tarojs/components'
import './index.scss'

interface Props {
  text?: string
}

/** 加载中提示 */
export default function Loading({ text = '加载中…' }: Props) {
  return (
    <View className='loading'>
      <View className='loading__dot' />
      <Text className='loading__text'>{text}</Text>
    </View>
  )
}
