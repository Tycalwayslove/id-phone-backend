import { useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { listPhotos } from '../../api/photos'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PhotoFrame from '../../components/PhotoFrame'
import SpecPicker from '../../components/SpecPicker'
import useCity from '../../hooks/useCity'
import useCommonSpecs from '../../hooks/useCommonSpecs'
import { usePagedList } from '../../hooks/usePagedList'
import useShootFlow from '../../hooks/useShootFlow'
import { describeError } from '../../utils/errors'
import { formatDate } from '../../utils/format'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type PhotoOut = components['schemas']['PhotoOut']

/** 保管状态文案与颜色 */
function accessLabel(p: PhotoOut): { text: string; ok: boolean } {
  const until = formatDate(p.access.access_until)
  if (p.access.active) return { text: until ? `保管至 ${until}` : '已保管', ok: true }
  if (p.access.access_until || p.status === 'expired') return { text: '已过期，续费后可下载', ok: false }
  return { text: '预览，未保存', ok: false }
}

export default function Photos() {
  const [picking, setPicking] = useState(false)
  const { city, regionCode } = useCity()
  const common = useCommonSpecs(regionCode, { enabled: picking && city !== null })
  const shoot = useShootFlow()
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
              <PhotoFrame className='photo-grid__frame'>
                {p.original_url ? (
                  <Image className='photo-grid__img' src={resolveUrl(p.original_url)} mode='aspectFill' lazyLoad />
                ) : (
                  <View className='photo-grid__placeholder hint'>暂无法预览</View>
                )}
              </PhotoFrame>
              <Text className={`photo-grid__tag${label.ok ? ' photo-grid__tag--ok' : ''}`}>{label.text}</Text>
            </View>
          )
        })}
      </View>
      {loading ? <Loading /> : null}
      {loaded && !loading && !error && items.length === 0 ? (
        <EmptyState
          emoji='📷'
          title='拍好的照片会存在这里'
          actionText='去拍一张'
          onAction={() => {
            if (shoot.busy) return
            setPicking(true)
          }}
        />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
      <SpecPicker
        open={picking}
        specs={common.specs}
        loading={common.loading}
        onClose={() => setPicking(false)}
        onPick={(spec) => {
          setPicking(false)
          void shoot.open(spec.code)
        }}
      />
    </PageContainer>
  )
}
