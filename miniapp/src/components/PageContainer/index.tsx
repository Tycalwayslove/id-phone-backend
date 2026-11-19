import type { ReactNode } from 'react'
import { View } from '@tarojs/components'
import './index.scss'

interface Props {
  children: ReactNode
  /** 页面底部有固定操作栏时为 true，预留空间避免遮挡内容 */
  withBottomBar?: boolean
}

/** 页面外壳：统一背景、内边距、底部安全区 */
export default function PageContainer({ children, withBottomBar = false }: Props) {
  return <View className={`page-container${withBottomBar ? ' with-bottom-bar' : ''}`}>{children}</View>
}
