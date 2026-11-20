import type { ReactNode } from 'react'
import { Text, View } from '@tarojs/components'
import { Popup } from '@nutui/nutui-react-taro'
import './index.scss'

interface Props {
  open: boolean
  title: string
  dismissible?: boolean
  onClose: () => void
  children: ReactNode
}

export default function BottomSheet({ open, title, dismissible = true, onClose, children }: Props) {
  return (
    <Popup
      className='bottom-sheet-popup'
      position='bottom'
      visible={open}
      closeable={dismissible}
      closeOnOverlayClick={dismissible}
      onClose={onClose}
      zIndex={80}
    >
      <View className='bottom-sheet'>
        <Text className='bottom-sheet__title'>{title}</Text>
        {children}
      </View>
    </Popup>
  )
}
