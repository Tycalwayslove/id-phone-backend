import { useEffect, useState } from 'react'
import { Button, Checkbox, CheckboxGroup, Label, Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { bgColorName } from '../../utils/format'
import type { PhotoSource } from '../../utils/pickPhoto'
import BottomSheet from '../BottomSheet'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']

interface Props {
  open: boolean
  spec?: SpecDetail
  onClose: () => void
  onChoose: (source: PhotoSource, skip: boolean) => void
}

export default function ShootGuide({ open, spec, onClose, onChoose }: Props) {
  const [skip, setSkip] = useState(false)
  useEffect(() => {
    if (!open) setSkip(false)
  }, [open])

  const color = bgColorName(spec?.bg_colors[0] ?? '')
  const backdrop = color === '其他' ? '规格要求的底色' : `${color}色`

  return (
    <BottomSheet open={open} title='拍之前看一眼' onClose={onClose}>
      <View className='shoot-guide__steps'>
        <Text>1. 正对镜头，露出眉毛和耳朵，表情自然</Text>
        <Text>2. 光线均匀，脸上没有明显阴影</Text>
        <Text>3. {spec ? `不用找白墙，背景会自动换成${backdrop}` : '不用找白墙，背景之后可以随便换'}</Text>
      </View>
      <View className='shoot-guide__actions'>
        <Button className='btn-native' onClick={() => onChoose('camera', skip)}>拍照</Button>
        <Button className='btn-native btn-native--plain' onClick={() => onChoose('upload', skip)}>从相册选</Button>
      </View>
      <CheckboxGroup onChange={(e) => setSkip(e.detail.value.includes('skip'))}>
        <Label className='shoot-guide__skip'>
          <Checkbox value='skip' checked={skip} />
          <Text>下次不再提示</Text>
        </Label>
      </CheckboxGroup>
    </BottomSheet>
  )
}
