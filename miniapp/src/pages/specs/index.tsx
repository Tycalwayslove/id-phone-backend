import { useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useReachBottom, usePullDownRefresh, useRouter } from '@tarojs/taro'
import { listSpecs } from '../../api/specs'
import type { SpecCategory } from '../../api/specs'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import SearchBox from '../../components/SearchBox'
import SpecCard from '../../components/SpecCard'
import { usePagedList } from '../../hooks/usePagedList'
import { describeError } from '../../utils/errors'
import { PAGES, navigate, safeDecode, toInt } from '../../utils/nav'
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
 * photo_id 有值表示“给这张照片换规格”，选中后直接回制作页。
 */
export default function Specs() {
  const { params } = useRouter()
  const photoId = toInt(params.photo_id)
  const [category, setCategory] = useState<SpecCategory | undefined>(parseCategory(params.category))
  const [keyword, setKeyword] = useState(params.keyword ? safeDecode(params.keyword) : '')

  const { items, loading, loaded, hasMore, error, reload, loadMore } = usePagedList(
    (cursor) => listSpecs({ category, keyword: keyword || undefined, cursor }),
    [category, keyword]
  )

  usePullDownRefresh(() => {
    void reload().finally(() => Taro.stopPullDownRefresh())
  })
  useReachBottom(() => {
    void loadMore()
  })

  const pick = (code: string) => {
    if (photoId) return navigate(PAGES.editor, { photo_id: photoId, spec_code: code })
    return navigate(PAGES.specDetail, { code })
  }

  return (
    <PageContainer>
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

      <View className='list-gap'>
        {items.map((s) => (
          <SpecCard key={s.code} spec={s} onClick={() => pick(s.code)} />
        ))}
      </View>

      {loading ? <Loading /> : null}
      {loaded && !loading && items.length === 0 ? (
        <EmptyState emoji='🔍' title='没有找到相关规格' desc='换个关键字或分类试试' />
      ) : null}
      {error ? <View className='list-footer'>{describeError(error).message}，下拉重试</View> : null}
      {loaded && !hasMore && items.length > 0 ? <View className='list-footer'>没有更多了</View> : null}
    </PageContainer>
  )
}
