import { Button, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { PAGES, navigate } from '../../utils/nav'
import BottomSheet from '../BottomSheet'
import Loading from '../Loading'
import SpecTile from '../SpecTile'

type SpecOut = components['schemas']['SpecOut']
type SpecDetail = components['schemas']['SpecDetail']

interface Props {
  open: boolean
  specs: SpecOut[]
  details: ReadonlyMap<string, SpecDetail>
  loading: boolean
  onClose: () => void
  onPick: (spec: SpecOut) => void
}

export default function SpecPicker({ open, specs, details, loading, onClose, onPick }: Props) {
  return (
    <BottomSheet open={open} title='拍哪种证件照？' onClose={onClose}>
      <View className='list-gap'>
        {loading && specs.length === 0 ? <Loading /> : null}
        {specs.length > 0 ? (
          <View className='spec-tiles'>
            {specs.map((spec) => (
              <SpecTile
                key={spec.code}
                spec={spec}
                supportsReceipt={details.get(spec.code)?.supports_receipt}
                onClick={() => onPick(spec)}
              />
            ))}
          </View>
        ) : null}
        <Button className='btn-native btn-native--plain' onClick={() => {
          onClose()
          void navigate(PAGES.specs)
        }}>
          搜索更多规格
        </Button>
      </View>
    </BottomSheet>
  )
}
