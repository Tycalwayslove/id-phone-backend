import { useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import useCity from '../../hooks/useCity'
import { PAGES, navigate } from '../../utils/nav'
import BottomSheet from '../BottomSheet'
import CityChip from '../CityChip'
import CityPicker from '../CityPicker'
import Loading from '../Loading'
import SpecGroups from '../SpecGroups'
import SpecTile from '../SpecTile'

type SpecOut = components['schemas']['SpecOut']

interface Props {
  open: boolean
  specs: SpecOut[]
  loading: boolean
  onClose: () => void
  onPick: (spec: SpecOut) => void
}

export default function SpecPicker({ open, specs, loading, onClose, onPick }: Props) {
  const { city, setCity } = useCity()
  const [changingCity, setChangingCity] = useState(false)
  const needsCity = city === null || changingCity

  return (
    <>
      <BottomSheet
        open={open && !needsCity}
        title='拍哪种证件照？'
        titleAction={<CityChip city={city} onClick={() => setChangingCity(true)} />}
        onClose={onClose}
      >
        <View className='list-gap'>
          {loading && specs.length === 0 ? <Loading /> : null}
          <SpecGroups city={city} specs={specs}>
            {(items) => (
              <View className='spec-tiles'>
                {items.map((spec) => <SpecTile key={spec.code} spec={spec} onClick={() => onPick(spec)} />)}
              </View>
            )}
          </SpecGroups>
          {!loading && specs.length === 0 ? <Text className='hint'>可以搜索更多规格，或换个城市试试</Text> : null}
          <Button className='btn-native btn-native--plain' onClick={() => {
            onClose()
            void navigate(PAGES.specs)
          }}>
            搜索更多规格
          </Button>
        </View>
      </BottomSheet>
      <CityPicker
        open={open && needsCity}
        city={city}
        onClose={() => {
          setChangingCity(false)
          if (!city) onClose()
        }}
        onPick={(nextCity) => {
          setCity(nextCity)
          setChangingCity(false)
        }}
      />
    </>
  )
}
