import { useRef, useState } from 'react'
import { View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { listEntitlements } from '../../api/entitlements'
import EntitlementCard from '../../components/EntitlementCard'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { handleError } from '../../utils/errors'

type EntitlementOut = components['schemas']['EntitlementOut']

export default function Entitlements() {
  const [list, setList] = useState<EntitlementOut[] | null>(null)
  const requestId = useRef(0)

  async function load(): Promise<void> {
    const id = ++requestId.current
    try {
      const entitlements = await listEntitlements('all')
      if (id === requestId.current) setList(entitlements)
    } catch (e) {
      if (id !== requestId.current) return
      setList((prev) => prev ?? [])
      await handleError(e)
    }
  }

  useDidShow(() => {
    void load()
  })
  usePullDownRefresh(() => {
    void load().finally(() => Taro.stopPullDownRefresh())
  })

  if (list === null) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      {list.length === 0 ? <EmptyState emoji='🎫' title='还没有权益' desc='购买套餐后会显示在这里' /> : null}
      <View className='list-gap'>
        {list.map((e) => (
          <EntitlementCard key={e.id} entitlement={e} showDetails />
        ))}
      </View>
    </PageContainer>
  )
}
