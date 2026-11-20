import type { ReactNode } from 'react'
import { Text, View } from '@tarojs/components'
import { Popup } from '@nutui/nutui-react-taro'
import './index.scss'

interface Props {
  open: boolean
  title: string
  titleAction?: ReactNode
  dismissible?: boolean
  onClose: () => void
  children: ReactNode
}

export default function BottomSheet({ open, title, titleAction, dismissible = true, onClose, children }: Props) {
  return (
    <Popup
      className='bottom-sheet-popup'
      position='bottom'
      visible={open}
      closeable={dismissible}
      closeOnOverlayClick={dismissible}
      onClose={() => {
        // NutUI 也会在 visible 变为 false 时调用 onClose。
        if (open) onClose()
      }}
      zIndex={80}
    >
      <View className='bottom-sheet'>
        <View className='bottom-sheet__header'>
          <Text className='bottom-sheet__title'>{title}</Text>
          {titleAction}
        </View>
        {children}
      </View>
    </Popup>
  )
}
