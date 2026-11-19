import { useEffect, useState } from 'react'
import { ScrollView, Text, View } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import type { components } from '../../api/schema'
import { listPlans } from '../../api/plans'
import { listSpecs } from '../../api/specs'
import PageContainer from '../../components/PageContainer'
import PlanCard from '../../components/PlanCard'
import SearchBox from '../../components/SearchBox'
import SpecCard from '../../components/SpecCard'
import { describeError } from '../../utils/errors'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type SpecOut = components['schemas']['SpecOut']
type PlanOut = components['schemas']['PlanOut']

export default function Index() {
  const [hot, setHot] = useState<SpecOut[]>([])
  const [receipts, setReceipts] = useState<SpecOut[]>([])
  const [plans, setPlans] = useState<PlanOut[]>([])

  async function load(): Promise<void> {
    const [a, b, c] = await Promise.allSettled([
      listSpecs({ limit: 6 }),
      listSpecs({ category: 'receipt', limit: 6 }),
      listPlans()
    ])
    if (a.status === 'fulfilled') setHot(a.value.items)
    if (b.status === 'fulfilled') setReceipts(b.value.items)
    if (c.status === 'fulfilled') setPlans(c.value.filter((p) => p.benefits.attach_to_parent !== 1))
    const failed = [a, b, c].find((r) => r.status === 'rejected')
    if (failed && failed.status === 'rejected') {
      await Taro.showToast({ title: describeError(failed.reason).message, icon: 'none' })
    }
  }

  useEffect(() => {
    void load()
  }, [])

  usePullDownRefresh(() => {
    void load().finally(() => Taro.stopPullDownRefresh())
  })

  const openSpec = (code: string) => navigate(PAGES.specDetail, { code })

  return (
    <PageContainer>
      <View className='home-hero'>
        <Text className='home-hero__name'>智拍证件照</Text>
        <Text className='home-hero__slogan'>无广告 · 官方回执 · 云端保管</Text>
        <View className='home-hero__search'>
          <SearchBox onSearch={(keyword) => navigate(PAGES.specs, { keyword })} />
        </View>
      </View>

      <View className='section-title'>
        <Text>热门规格</Text>
        <Text className='section-more' onClick={() => navigate(PAGES.specs)}>
          全部 &gt;
        </Text>
      </View>
      <View className='list-gap'>
        {hot.map((s) => (
          <SpecCard key={s.code} spec={s} onClick={() => openSpec(s.code)} />
        ))}
      </View>

      {receipts.length > 0 ? (
        <>
          <View className='section-title home-section'>
            <Text>办理回执</Text>
            <Text className='section-more' onClick={() => navigate(PAGES.specs, { category: 'receipt' })}>
              更多 &gt;
            </Text>
          </View>
          <ScrollView scrollX className='home-scroll' enhanced showScrollbar={false}>
            <View className='home-scroll__row'>
              {receipts.map((s) => (
                <View key={s.code} className='home-receipt' onClick={() => openSpec(s.code)}>
                  <Text className='home-receipt__name'>{s.name}</Text>
                  <Text className='home-receipt__sub'>官方回执</Text>
                </View>
              ))}
            </View>
          </ScrollView>
        </>
      ) : null}

      {plans.length > 0 ? (
        <>
          <View className='section-title home-section'>
            <Text>套餐亮点</Text>
            <Text className='section-more' onClick={() => navigate(PAGES.plans)}>
              查看全部 &gt;
            </Text>
          </View>
          <View className='list-gap'>
            {plans.slice(0, 3).map((p) => (
              <PlanCard key={p.code} plan={p} onClick={() => navigate(PAGES.plans)} />
            ))}
          </View>
        </>
      ) : null}
    </PageContainer>
  )
}
