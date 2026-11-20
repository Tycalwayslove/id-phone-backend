import { Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { listPhotos } from '../../api/photos'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError } from '../../utils/errors'
import { formatDate } from '../../utils/format'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type PhotoOut = components['schemas']['PhotoOut']

/** 保管状态文案与颜色 */
function accessLabel(p: PhotoOut): { text: string; ok: boolean } {
  if (p.access.active && p.access.access_until) return { text: `保管至 ${formatDate(p.access.access_until)}`, ok: true }
  if (p.access.access_until) return { text: '已过期', ok: false }
  return { text: '未购买', ok: false }
}

export default function Photos() {
  const { items, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listPhotos(cursor),
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
      <View className='photo-grid'>
        {items.map((p) => {
          const label = accessLabel(p)
          return (
            <View key={p.id} className='photo-grid__cell' onClick={() => navigate(PAGES.photoDetail, { id: p.id })}>
              {p.original_url ? (
                <Image className='photo-grid__img' src={resolveUrl(p.original_url)} mode='aspectFill' lazyLoad />
              ) : (
                <View className='photo-grid__placeholder hint'>暂无法预览</View>
              )}
              <Text className={`photo-grid__tag${label.ok ? ' photo-grid__tag--ok' : ''}`}>{label.text}</Text>
            </View>
          )
        })}
      </View>
      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? (
        <EmptyState
          emoji='📷'
          title='还没有证件照'
          desc='选一个规格，拍一张试试'
          actionText='去制作'
          onAction={() => navigate(PAGES.specs)}
        />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </PageContainer>
  )
}
