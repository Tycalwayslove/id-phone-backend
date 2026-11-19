import { Text, View } from '@tarojs/components'
import './index.scss'

interface Props {
  emoji?: string
  title: string
  desc?: string
  actionText?: string
  onAction?: () => void
}

/** 空状态：emoji 占位 + 标题 + 可选按钮 */
export default function EmptyState({ emoji = '📭', title, desc, actionText, onAction }: Props) {
  return (
    <View className='empty-state'>
      <Text className='empty-state__emoji'>{emoji}</Text>
      <Text className='empty-state__title'>{title}</Text>
      {desc ? <Text className='empty-state__desc'>{desc}</Text> : null}
      {actionText && onAction ? (
        <View className='empty-state__action' onClick={onAction}>
          {actionText}
        </View>
      ) : null}
    </View>
  )
}
