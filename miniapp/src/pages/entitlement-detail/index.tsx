import { useRef, useState } from 'react'
import { View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useRouter } from '@tarojs/taro'
import { getEntitlement } from '../../api/entitlements'
import EntitlementCard from '../../components/EntitlementCard'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { describeError } from '../../utils/errors'
import { toInt } from '../../utils/nav'

export default function EntitlementDetail() {
  const { params } = useRouter()
  const id = toInt(params.id)
  const [entitlement, setEntitlement] = useState<Awaited<ReturnType<typeof getEntitlement>> | null>(null)
  const [error, setError] = useState('')
  const requestId = useRef(0)

  async function load(): Promise<void> {
    if (id === undefined) return
    const request = ++requestId.current
    try {
      const current = await getEntitlement(id)
      if (request !== requestId.current) return
      setEntitlement(current)
      setError('')
    } catch (e) {
      if (request === requestId.current) setError(describeError(e).message)
    }
  }

  useDidShow(() => {
    void load()
  })
  usePullDownRefresh(() => {
    void load().finally(() => Taro.stopPullDownRefresh())
  })

  return (
    <PageContainer>
      {id === undefined ? <View className='list-footer'>缺少权益编号</View> : null}
      {entitlement ? <EntitlementCard entitlement={entitlement} /> : null}
      {error ? <View className='list-footer'>{error}，下拉重试</View> : null}
      {id !== undefined && !entitlement && !error ? <Loading /> : null}
    </PageContainer>
  )
}
