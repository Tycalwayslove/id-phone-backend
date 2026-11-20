import { useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useReachBottom, usePullDownRefresh, useRouter } from '@tarojs/taro'
import { listSpecs } from '../../api/specs'
import type { SpecCategory } from '../../api/specs'
import CityChip from '../../components/CityChip'
import CityPicker from '../../components/CityPicker'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import SearchBox from '../../components/SearchBox'
import SpecCard from '../../components/SpecCard'
import useCity from '../../hooks/useCity'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError, handleError } from '../../utils/errors'
import { PAGES, SPEC_PICKED_EVENT, navigate, safeDecode, toInt } from '../../utils/nav'
import './index.scss'

interface Tab {
  label: string
  value: SpecCategory | undefined
}

const TABS: Tab[] = [
  { label: '全部', value: undefined },
  { label: '回执', value: 'receipt' },
  { label: '常用', value: 'normal' },
  { label: '考试', value: 'exam' }
]

function parseCategory(v: string | undefined): SpecCategory | undefined {
  return v === 'receipt' || v === 'normal' || v === 'exam' ? v : undefined
}

/**
 * 规格列表。路由参数：
 * keyword 初始关键字；category 初始分类；
 * select=1 时通过页面通信通道将规格返回给制作页；
 * photo_id 有值表示“给这张照片换规格”，选中后直接回制作页。
 */
export default function Specs() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const selecting = params.select === '1'
  const { city, setCity, regionCode } = useCity()
  const [pickingCity, setPickingCity] = useState(!city)
  const [category, setCategory] = useState<SpecCategory | undefined>(parseCategory(params.category))
  const [keyword, setKeyword] = useState(params.keyword ? safeDecode(params.keyword) : '')

  const pick = (code: string) => {
    if (!city) {
      setPickingCity(true)
      return
    }
    if (selecting) {
      const channel = Taro.getCurrentInstance().page?.getOpenerEventChannel?.()
      if (!channel?.emit) {
        void Taro.showToast({ title: '请返回制作页重新选择证件类型', icon: 'none' })
        return
      }
      channel.emit(SPEC_PICKED_EVENT, code)
      void Taro.navigateBack().catch(handleError)
    } else if (photoId) void navigate(PAGES.editor, { photo_id: photoId, spec_code: code })
    else void navigate(PAGES.specDetail, { code })
  }

  return (
    <PageContainer>
      <View className='specs-city'>
        <CityChip city={city} onClick={() => setPickingCity(true)} />
      </View>
      <SearchBox value={keyword} onSearch={setKeyword} />
      <View className='specs-tabs'>
        {TABS.map((t) => (
          <Text
            key={t.label}
            className={`specs-tabs__item${t.value === category ? ' specs-tabs__item--active' : ''}`}
            onClick={() => setCategory(t.value)}
          >
            {t.label}
          </Text>
        ))}
      </View>
      {photoId ? <View className='hint specs-tip'>请选择要换成的规格</View> : null}
      <SpecResults key={regionCode} category={category} keyword={keyword} regionCode={regionCode} onPick={pick} />
      <CityPicker
        open={pickingCity}
        city={city}
        onClose={() => setPickingCity(false)}
        onPick={(nextCity) => {
          setCity(nextCity)
          setPickingCity(false)
        }}
      />
    </PageContainer>
  )
}

interface SpecResultsProps {
  category?: SpecCategory
  keyword: string
  regionCode: string
  onPick: (code: string) => void
}

function SpecResults({ category, keyword, regionCode, onPick }: SpecResultsProps) {
  const { items, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listSpecs({ category, keyword: keyword || undefined, cursor, region_code: regionCode }),
    [category, keyword]
  )

  usePullDownRefresh(() => {
    void reload().finally(() => Taro.stopPullDownRefresh())
  })
  useReachBottom(() => {
    void loadMore()
  })

  return (
    <>
      <View className='list-gap'>
        {items.map((s) => (
          <SpecCard key={s.code} spec={s} onClick={() => onPick(s.code)} />
        ))}
      </View>

      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? (
        <EmptyState emoji='🔍' title='没有找到相关规格' desc='换个关键字、分类或城市试试' />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </>
  )
}
