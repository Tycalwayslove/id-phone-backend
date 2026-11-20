import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { readPublicEnv } from './publicEnv'
import './index.scss'

const wecomUrl = readPublicEnv(() => process.env.TARO_APP_WECOM_URL)
const wecomQrUrl = readPublicEnv(() => process.env.TARO_APP_WECOM_QR_URL)
const wecomText = readPublicEnv(() => process.env.TARO_APP_WECOM_TEXT)
const mpName = readPublicEnv(() => process.env.TARO_APP_MP_NAME)
const mpText = readPublicEnv(() => process.env.TARO_APP_MP_TEXT)

async function copy(data: string): Promise<void> {
  try {
    await Taro.setClipboardData({ data })
  } catch {
    void Taro.showToast({ title: '复制失败，请重试', icon: 'none' })
  }
}

async function showWecomQr(): Promise<void> {
  try {
    await Taro.previewImage({ urls: [wecomQrUrl] })
  } catch {
    void Taro.showToast({ title: '二维码加载失败，请重试', icon: 'none' })
  }
}

export default function PrivateDomainCard() {
  if (!wecomUrl && !wecomQrUrl && !mpName) return null

  return (
    <View className='card private-domain'>
      {wecomUrl || wecomQrUrl ? (
        <View className='private-domain__channel'>
          <Text className='private-domain__title'>添加企业微信</Text>
          <Text className='private-domain__copy'>
            {wecomText || '添加企业微信好友，咨询证件照和回执办理。'}
          </Text>
          <Text className='hint'>
            {wecomQrUrl ? '查看二维码后，长按识别并添加。' : '复制添加链接，在浏览器打开。'}
          </Text>
          <View className='private-domain__actions'>
            {wecomQrUrl ? (
              <Button className='private-domain__button' onClick={() => void showWecomQr()}>
                查看二维码
              </Button>
            ) : null}
            {wecomUrl ? (
              <Button className='private-domain__button' onClick={() => void copy(wecomUrl)}>
                复制添加链接
              </Button>
            ) : null}
          </View>
        </View>
      ) : null}
      {mpName ? (
        <View className='private-domain__channel'>
          <Text className='private-domain__title'>关注公众号</Text>
          <Text className='private-domain__copy'>{mpText || '关注公众号，查看服务动态。'}</Text>
          <Text className='hint'>在微信搜索「{mpName}」并关注。</Text>
          <View className='private-domain__actions'>
            <Button className='private-domain__button' onClick={() => void copy(mpName)}>
              复制公众号名称
            </Button>
          </View>
        </View>
      ) : null}
    </View>
  )
}
