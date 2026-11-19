import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import { listReceipts } from '../../api/receipts'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import StatusTag from '../../components/StatusTag'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError } from '../../utils/errors'
import { formatDateTime } from '../../utils/format'
import { PAGES, navigate, switchTab } from '../../utils/nav'
import './index.scss'

export default function Receipts() {
  const { items, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listReceipts(cursor),
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
        {items.map((a) => (
          <View key={a.app_no} className='card receipt-item' onClick={() => navigate(PAGES.receiptDetail, { app_no: a.app_no })}>
            <View className='receipt-item__head'>
              <Text className='receipt-item__name'>{a.spec_name}</Text>
              <StatusTag kind='application' status={a.status} />
            </View>
            <Text className='hint'>申请时间 {formatDateTime(a.created_at)}</Text>
            {a.status === 'rejected' && a.reject_reason ? (
              <Text className='receipt-item__reason'>驳回原因：{a.reject_reason}</Text>
            ) : null}
          </View>
        ))}
      </View>
      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? (
        <EmptyState
          emoji='📄'
          title='还没有回执'
          desc='选择支持回执的规格即可办理'
          actionText='去办理'
          onAction={() => switchTab(PAGES.index)}
        />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </PageContainer>
  )
}
