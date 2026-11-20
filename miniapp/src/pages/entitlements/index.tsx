import { View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import { listEntitlements } from '../../api/entitlements'
import EntitlementCard from '../../components/EntitlementCard'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError } from '../../utils/errors'

export default function Entitlements() {
  const { items, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listEntitlements('all', cursor),
    [],
    { auto: false }
  )

  useDidShow(() => {
    void reload()
  })
  usePullDownRefresh(() => {
    void reload().finally(() => Taro.stopPullDownRefresh())
  })
  useReachBottom(() => {
    void loadMore()
  })

  return (
    <PageContainer>
      <View className='list-gap'>
        {items.map((e) => (
          <EntitlementCard key={e.id} entitlement={e} showDetails />
        ))}
      </View>
      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? (
        <EmptyState emoji='🎫' title='还没有权益' desc='购买套餐后会显示在这里' />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </PageContainer>
  )
}
