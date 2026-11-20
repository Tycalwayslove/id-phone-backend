import { useEffect, useSyncExternalStore } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useUnload } from '@tarojs/taro'
import { LEGAL_PAGES } from '../../pages/legal/routes'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type PrivacyListener = Parameters<typeof Taro.onNeedPrivacyAuthorization>[0]
type Resolve = Parameters<PrivacyListener>[0]
type PrivacyPage = typeof PAGES.index | typeof PAGES.me | typeof LEGAL_PAGES.privacy

declare const wx: { onNeedPrivacyAuthorization?: (listener: PrivacyListener) => void }

const AGREE_BUTTON_ID = 'privacy-popup-agree'
const listeners = new Set<() => void>()
let pending: { page: PrivacyPage; resolvers: Resolve[]; returnToCaller: boolean } | null = null
let listening = false

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getPage(): PrivacyPage | null {
  return pending?.page ?? null
}

function setPending(value: typeof pending): void {
  pending = value
  listeners.forEach((listener) => listener())
}

async function answer(agreed: boolean, goBack = true): Promise<void> {
  if (!pending) return
  const { resolvers, returnToCaller } = pending
  setPending(null)
  if (returnToCaller && goBack) {
    // 先返回发起操作的页面，再恢复被微信挂起的接口调用。
    await Taro.navigateBack().catch(() => undefined)
  }
  for (const resolve of resolvers) {
    if (agreed) resolve({ event: 'agree', buttonId: AGREE_BUTTON_ID })
    else resolve({ event: 'disagree' })
  }
  if (!agreed) {
    void Taro.showModal({
      title: '相关功能暂不可用',
      content: '你可以继续浏览。拍照、选图等涉及个人信息的功能需同意隐私保护指引后才能使用。',
      showCancel: false
    })
  }
}

function listenForPrivacyAuthorization(): void {
  if (listening || typeof wx === 'undefined' || typeof wx.onNeedPrivacyAuthorization !== 'function') return
  wx.onNeedPrivacyAuthorization((resolve) => {
    if (pending) {
      pending.resolvers.push(resolve)
      return
    }

    const pages = Taro.getCurrentPages()
    const current = `/${pages[pages.length - 1]?.route ?? ''}`
    if (current === PAGES.index || current === PAGES.me || current === LEGAL_PAGES.privacy) {
      setPending({ page: current, resolvers: [resolve], returnToCaller: false })
      return
    }

    // 规格详情等已有页面可通过隐私政策页完成授权，无需离开当前流程。
    setPending({ page: LEGAL_PAGES.privacy, resolvers: [resolve], returnToCaller: true })
    void navigate(LEGAL_PAGES.privacy).catch(() => answer(false, false))
  })
  listening = true
}

function openPrivacyGuide(): void {
  Taro.openPrivacyContract({
    fail: () => {
      void Taro.showToast({ title: '暂时无法打开隐私保护指引', icon: 'none' })
    },
  })
}

export default function PrivacyPopup({ page }: { page: PrivacyPage }) {
  const pendingPage = useSyncExternalStore(subscribe, getPage, getPage)
  useEffect(listenForPrivacyAuthorization, [])
  useUnload(() => {
    if (getPage() === page) void answer(false, false)
  })

  if (pendingPage !== page) return null
  const onPolicyPage = page === LEGAL_PAGES.privacy

  const panel = (
    <View className='privacy-popup__panel'>
      <Text className='privacy-popup__title'>小程序隐私保护指引</Text>
      <Text className='privacy-popup__summary'>
        本小程序在你制作证件照、办理回执或绑定手机号时，按所选服务使用你的照片和必要资料。请阅读微信隐私保护指引后选择是否同意。
      </Text>
      <Text className='privacy-popup__link' onClick={openPrivacyGuide}>查看微信隐私保护指引</Text>
      {!onPolicyPage ? (
        <Text className='privacy-popup__link' onClick={() => {
          void navigate(LEGAL_PAGES.privacy).catch(() => {
            void Taro.showToast({ title: '暂时无法打开隐私政策', icon: 'none' })
          })
        }}>
          查看隐私政策
        </Text>
      ) : null}
      <View className='privacy-popup__actions'>
        <Button className='btn-native btn-native--plain' onClick={() => void answer(false)}>拒绝</Button>
        <Button
          className='btn-native'
          id={AGREE_BUTTON_ID}
          openType='agreePrivacyAuthorization'
          onAgreePrivacyAuthorization={() => void answer(true)}
        >
          同意
        </Button>
      </View>
    </View>
  )

  return onPolicyPage ? panel : (
    <View className='privacy-popup' catchMove>
      {panel}
    </View>
  )
}
