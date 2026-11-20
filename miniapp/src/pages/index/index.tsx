import { useState } from 'react'
import { Button, ScrollView, Text, View } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import type { components } from '../../api/schema'
import CityChip from '../../components/CityChip'
import CityPicker from '../../components/CityPicker'
import HeroFrame from '../../components/HeroFrame'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import PrivacyPopup from '../../components/PrivacyPopup'
import PrivateDomainCard from '../../components/PrivateDomainCard'
import SearchBox from '../../components/SearchBox'
import ShootGuide from '../../components/ShootGuide'
import SpecGroups from '../../components/SpecGroups'
import SpecPicker from '../../components/SpecPicker'
import SpecTile from '../../components/SpecTile'
import useCity from '../../hooks/useCity'
import useCommonSpecs from '../../hooks/useCommonSpecs'
import useShootFlow from '../../hooks/useShootFlow'
import { handleError } from '../../utils/errors'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type SpecOut = components['schemas']['SpecOut']

const REASONS = [
  ['修得自然', '美颜可调，五官不变形，按官方尺寸和底色制作。'],
  ['没有广告', '从拍到保存，全程没有广告。'],
  ['全国可办回执', '各省常见证件的官方回执可以在线办理。'],
  ['云端保管', '换手机也能下载，还能换尺寸。']
]

export default function Index() {
  const { city, setCity, regionCode } = useCity()
  const { specs, loading, load } = useCommonSpecs(regionCode)
  const receipts = useCommonSpecs(regionCode, { category: 'receipt', limit: 6 })
  const [picking, setPicking] = useState(false)
  const [cityAction, setCityAction] = useState<'change' | { keyword?: string } | null>(null)
  const shoot = useShootFlow()

  async function refresh(): Promise<void> {
    const results = await Promise.allSettled([
      load(),
      receipts.load()
    ])
    const failure = results.find((result) => result.status === 'rejected')
    if (failure?.status === 'rejected') await handleError(failure.reason)
  }

  usePullDownRefresh(() => {
    void refresh().finally(() => Taro.stopPullDownRefresh())
  })

  function pickSpec(spec: SpecOut): void {
    if (!city) {
      openPicker()
      return
    }
    setPicking(false)
    void shoot.open(spec.code)
  }

  function openPicker(): void {
    if (shoot.busy) return
    setPicking(true)
    if (city && specs.length === 0) void load().catch(handleError)
  }

  function openCatalog(keyword?: string): void {
    if (city) void navigate(PAGES.specs, { keyword })
    else setCityAction({ keyword })
  }

  return (
    <PageContainer>
      <View className='home-city'>
        <CityChip city={city} onClick={() => setCityAction('change')} />
      </View>
      <View className='home-hero'>
        <Text className='home-hero__title'>在家拍证件照</Text>
        <Text className='home-hero__intro'>手机拍一张，自动换底色、裁尺寸，修得自然。</Text>
        <HeroFrame />
        <Button className='btn-native' onClick={openPicker} disabled={shoot.busy}>开始拍</Button>
        <Text className='hint home-hero__note'>先免费看成品，满意再保存</Text>
      </View>

      <SearchBox
        placeholder='搜身份证、社保卡、教师资格证…'
        onSearch={openCatalog}
      />

      <View className='home-section'>
        <View className='section-title'>
          <Text>常用规格</Text>
          <Text className='home-link' onClick={() => openCatalog()}>全部</Text>
        </View>
        {loading && specs.length === 0 ? <Loading /> : null}
        <View className='spec-tiles'>
          {specs.map((spec) => (
            <SpecTile
              key={spec.code}
              spec={spec}
              onClick={() => pickSpec(spec)}
            />
          ))}
        </View>
      </View>

      <View className='home-section'>
        <View className='section-title'>
          <Text>办证要回执？</Text>
        </View>
        <Text className='home-receipt-copy'>身份证、社保卡、驾驶证等官方回执，拍好照片后在线提交，不用跑腿。</Text>
        <SpecGroups city={city} specs={receipts.specs.filter((spec) => spec.supports_receipt)}>
          {(items) => (
            <ScrollView scrollX className='home-scroll' enhanced showScrollbar={false}>
              <View className='home-scroll__row'>
                {items.map((spec) => (
                  <Text key={spec.code} className='home-receipt' onClick={() => {
                    if (city) void navigate(PAGES.specDetail, { code: spec.code })
                    else openPicker()
                  }}>
                    {spec.name}
                  </Text>
                ))}
              </View>
            </ScrollView>
          )}
        </SpecGroups>
      </View>

      <View className='home-section'>
        <View className='section-title'><Text>为什么在这里拍</Text></View>
        {REASONS.map(([label, description]) => (
          <View className='home-reason' key={label}>
            <Text className='home-reason__label'>{label}</Text>
            <Text className='home-reason__description'>{description}</Text>
          </View>
        ))}
      </View>
      <PrivateDomainCard />
      <SpecPicker
        open={picking}
        specs={specs}
        loading={loading}
        onPick={pickSpec}
        onClose={() => setPicking(false)}
      />
      <CityPicker
        open={cityAction !== null}
        city={city}
        onClose={() => setCityAction(null)}
        onPick={(nextCity) => {
          setCity(nextCity)
          setCityAction(null)
          if (cityAction && cityAction !== 'change') void navigate(PAGES.specs, { keyword: cityAction.keyword })
        }}
      />
      <ShootGuide spec={shoot.spec} onChoose={shoot.choose} onClose={shoot.close} />
      <PrivacyPopup page={PAGES.index} />
    </PageContainer>
  )
}
