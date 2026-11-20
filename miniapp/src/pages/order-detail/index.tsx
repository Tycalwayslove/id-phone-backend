import { useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useRouter } from '@tarojs/taro'
import { getOrder } from '../../api/orders'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PriceText from '../../components/PriceText'
import StatusTag from '../../components/StatusTag'
import { describeError } from '../../utils/errors'
import { formatDateTime } from '../../utils/format'
import { ORDER_ITEM_TYPE_TEXT } from '../../utils/status'
import '../orders/index.scss'

export default function OrderDetail() {
  const { params } = useRouter()
  const orderNo = params.order_no
  const [order, setOrder] = useState<Awaited<ReturnType<typeof getOrder>> | null>(null)
  const [error, setError] = useState('')

  async function load(): Promise<void> {
    if (!orderNo) return
    try {
      setOrder(await getOrder(orderNo))
      setError('')
    } catch (e) {
      setError(describeError(e).message)
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
      {order ? (
        <View className='card order-item'>
          <View className='order-item__head'>
            <Text className='hint'>{order.order_no}</Text>
            <StatusTag kind='order' order={order} />
          </View>
          {order.items.map((item, i) => (
            <View key={i} className='order-item__row'>
              <View>
                <Text>{item.plan_name ?? ORDER_ITEM_TYPE_TEXT[item.item_type]}</Text>
                {item.plan_name ? <Text className='hint'> · {ORDER_ITEM_TYPE_TEXT[item.item_type]}</Text> : null}
              </View>
              <PriceText fen={item.amount_fen} size='small' />
            </View>
          ))}
          <View className='order-item__foot'>
            <Text className='hint'>下单时间</Text>
            <Text>{formatDateTime(order.created_at)}</Text>
          </View>
          {order.paid_at ? (
            <View className='order-item__row'>
              <Text className='hint'>支付时间</Text>
              <Text>{formatDateTime(order.paid_at)}</Text>
            </View>
          ) : null}
          <View className='order-item__row'>
            <Text className='hint'>应付金额</Text>
            <PriceText fen={order.total_fen} />
          </View>
          <View className='order-item__row'>
            <Text className='hint'>已付金额</Text>
            <PriceText fen={order.paid_fen} />
          </View>
          {order.refunded_fen > 0 ? (
            <View className='order-item__row'>
              <Text className='hint'>已退金额</Text>
              <PriceText fen={order.refunded_fen} />
            </View>
          ) : null}
        </View>
      ) : null}
      {!orderNo ? <View className='list-footer'>缺少订单号</View> : null}
      {error ? <View className='list-footer'>{error}，下拉重试</View> : null}
      {orderNo && !order && !error ? <Loading /> : null}
    </PageContainer>
  )
}
