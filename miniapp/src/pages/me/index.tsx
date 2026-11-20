import { useState } from 'react'
import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { resolveUrl } from '../../api/client'
import { cancelAccount } from '../../api/me'
import PageContainer from '../../components/PageContainer'
import PrivacyPopup from '../../components/PrivacyPopup'
import PrivateDomainCard from '../../components/PrivateDomainCard'
import { useUserStore } from '../../stores/user'
import { handleError } from '../../utils/errors'
import { PAGES, navigate } from '../../utils/nav'
import { LEGAL_PAGES } from '../legal/routes'
import ReminderSettings from './ReminderSettings'
import './index.scss'

interface MenuItem {
  label: string
  path: string
}

const MENUS: MenuItem[] = [
  { label: '我的订单', path: PAGES.orders },
  { label: '我的权益', path: PAGES.entitlements },
  { label: '我的回执', path: PAGES.receipts },
  { label: '用户协议', path: LEGAL_PAGES.agreement },
  { label: '隐私政策', path: LEGAL_PAGES.privacy }
]

export default function Me() {
  const user = useUserStore((s) => s.user)
  const [binding, setBinding] = useState(false)

  // 每次显示：没登录就静默登录；已登录刷新资料
  useDidShow(() => {
    useUserStore
      .getState()
      .ensureLogin()
      .catch((e: unknown) => handleError(e))
  })

  async function bindPhone(code: string | undefined): Promise<void> {
    if (!code) {
      // 用户拒绝授权
      return
    }
    if (binding) return
    setBinding(true)
    try {
      await useUserStore.getState().bindPhone(code)
      await Taro.showToast({ title: '绑定成功', icon: 'success' })
    } catch (err) {
      await handleError(err)
    } finally {
      setBinding(false)
    }
  }

  async function onCancelAccount(): Promise<void> {
    const r = await Taro.showModal({
      title: '注销账号',
      content: '注销后将立即删除你的全部照片，且无法恢复。确定要注销吗？',
      confirmText: '确认注销',
      confirmColor: '#FF3141'
    })
    if (!r.confirm) return
    try {
      await cancelAccount()
      useUserStore.getState().clearLocal()
      await Taro.showToast({ title: '账号已注销', icon: 'success' })
      await Taro.reLaunch({ url: PAGES.index })
    } catch (e) {
      await handleError(e)
    }
  }

  function about(): void {
    void Taro.showModal({
      title: '关于智拍证件照',
      content: '无广告 · 官方回执 · 云端保管\n版本 0.1.0',
      showCancel: false
    })
  }

  return (
    <PageContainer>
      <View className='card me-profile'>
        {user?.avatar_url ? (
          <Image className='me-profile__avatar' src={resolveUrl(user.avatar_url)} mode='aspectFill' />
        ) : (
          <View className='me-profile__avatar me-profile__avatar--empty'>👤</View>
        )}
        <View className='me-profile__info'>
          <Text className='me-profile__name'>{user?.nickname || '微信用户'}</Text>
          {user?.phone_masked ? (
            <Text className='hint'>手机号 {user.phone_masked}</Text>
          ) : (
            <Button className='me-profile__bind' openType='getPhoneNumber' onGetPhoneNumber={(e) => void bindPhone((e.detail as { code?: string }).code)}>
              绑定手机号
            </Button>
          )}
        </View>
      </View>

      <View className='me-menu'>
        {MENUS.map((m) => (
          <View key={m.path} className='cell' onClick={() => navigate(m.path)}>
            <Text>{m.label}</Text>
            <Text className='cell__arrow'>&gt;</Text>
          </View>
        ))}
        <ReminderSettings />
        <Button className='cell cell-btn' openType='contact'>
          <Text>联系客服</Text>
          <Text className='cell__arrow'>&gt;</Text>
        </Button>
        <View className='cell' onClick={about}>
          <Text>关于</Text>
          <Text className='cell__arrow'>&gt;</Text>
        </View>
      </View>

      <PrivateDomainCard />
      <View className='me-cancel' onClick={onCancelAccount}>
        注销账号
      </View>
      <PrivacyPopup page={PAGES.me} />
    </PageContainer>
  )
}
