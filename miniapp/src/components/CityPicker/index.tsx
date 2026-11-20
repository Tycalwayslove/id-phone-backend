import { useEffect, useState } from 'react'
import { Button, ScrollView, Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { listSpecRegions } from '../../api/specs'
import type { City } from '../../hooks/useCity'
import BottomSheet from '../BottomSheet'
import Loading from '../Loading'
import './index.scss'

type Province = components['schemas']['SpecRegionProvince']
type Region = Pick<Province, 'region_code' | 'region_name'>

interface Props {
  open: boolean
  city: City | null
  onClose: () => void
  onPick: (city: City) => void
}

export default function CityPicker({ open, city, onClose, onPick }: Props) {
  const [provinces, setProvinces] = useState<Province[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!open || provinces !== null) return
    let active = true
    setFailed(false)
    void listSpecRegions().then((regions) => {
      if (active) setProvinces(regions)
    }).catch(() => {
      if (active) setFailed(true)
    })
    return () => { active = false }
  }, [open, provinces, attempt])

  function option(region: Region, count: number) {
    const { region_code: code, region_name: name } = region
    const selected = city?.code === code
    return (
      <Button
        key={code}
        className={`city-picker__option${selected ? ' city-picker__option--selected' : ''}`}
        onClick={() => onPick({ code, name })}
      >
        <Text>{name}</Text>
        <Text className='hint'>{count} 个规格</Text>
      </Button>
    )
  }

  return (
    <BottomSheet open={open} title='你在哪里办证？' onClose={onClose}>
      <View className='list-gap'>
        <Text className='hint'>不同城市能办的回执不一样</Text>
        {failed ? (
          <Button className='btn-native btn-native--plain' onClick={() => setAttempt(attempt + 1)}>
            城市列表加载失败，点此重试
          </Button>
        ) : null}
        {provinces === null && !failed ? <Loading /> : null}
        {provinces?.length === 0 ? <Text className='hint'>暂无地区专属规格，可以继续查看全国通用规格</Text> : null}
        {provinces?.length ? (
          <ScrollView scrollY className='city-picker__list'>
            {provinces.map((province) => (
              <View key={province.region_code} className='city-picker__province'>
                {province.cities.length ? (
                  <>
                    <Text className='city-picker__heading'>{province.region_name}</Text>
                    {province.cities.map((region) => option(region, region.spec_count + province.province_spec_count))}
                  </>
                ) : option(province, province.spec_count)}
              </View>
            ))}
          </ScrollView>
        ) : null}
        <Button className='btn-native btn-native--plain' onClick={() => onPick({ code: '', name: '全国' })}>
          我的城市不在这里
        </Button>
      </View>
    </BottomSheet>
  )
}
