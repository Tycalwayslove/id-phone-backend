import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import { cancelOrder, listOrders } from '../../api/orders'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PriceText from '../../components/PriceText'
import StatusTag from '../../components/StatusTag'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError, handleError } from '../../utils/errors'
import { formatDateTime } from '../../utils/format'
import { PAGES, navigate } from '../../utils/nav'
import { ORDER_ITEM_TYPE_TEXT } from '../../utils/status'
import './index.scss'

export default function Orders() {
  const { items, setItems, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listOrders(cursor),
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

  async function cancel(orderNo: string): Promise<void> {
    const r = await Taro.showModal({ title: '取消订单', content: '确定取消这个订单吗？' })
    if (!r.confirm) return
    try {
      const updated = await cancelOrder(orderNo)
      setItems((prev) => prev.map((o) => (o.order_no === orderNo ? updated : o)))
      await Taro.showToast({ title: '订单已取消', icon: 'success' })
    } catch (e) {
      await handleError(e)
    }
  }

  return (
    <PageContainer>
      <View className='list-gap'>
        {items.map((o) => (
          <View key={o.order_no} className='card order-item'>
            <View className='order-item__head'>
              <Text className='hint'>{o.order_no}</Text>
              <StatusTag kind='order' order={o} />
            </View>
            {o.items.map((it, i) => (
              <View key={`${o.order_no}-${i}`} className='order-item__row'>
                <Text>{it.plan_name ?? ORDER_ITEM_TYPE_TEXT[it.item_type]}</Text>
                <PriceText fen={it.amount_fen} size='small' />
              </View>
            ))}
            <View className='order-item__foot'>
              <Text className='hint'>{formatDateTime(o.created_at)}</Text>
              <View className='order-item__total'>
                <Text className='hint'>应付 </Text>
                <PriceText fen={o.total_fen} />
              </View>
            </View>
            <View className='order-item__actions'>
              <Text
                className='order-item__btn'
                onClick={() => navigate(PAGES.orderDetail, { order_no: o.order_no })}
              >
                查看详情
              </Text>
              {o.status === 'pending' ? (
                <Text className='order-item__btn' onClick={() => cancel(o.order_no)}>
                  取消订单
                </Text>
              ) : null}
            </View>
          </View>
        ))}
      </View>
      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? <EmptyState emoji='🧾' title='还没有订单' /> : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </PageContainer>
  )
}
