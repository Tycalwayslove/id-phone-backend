import { useRef, useState } from 'react'
import { Button, Checkbox, CheckboxGroup, Label, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { SKIP_GUIDE_KEY } from '../../hooks/useShootFlow'
import { handleError } from '../../utils/errors'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

const EXAMPLES = [
  { kind: 'correct', label: '正确' },
  { kind: 'profile', label: '侧脸' },
  { kind: 'small', label: '头太小' },
  { kind: 'backlit', label: '背光' }
]
const TIPS = [
  '手机举到眼睛高度，离远一点，把肩膀也拍进来',
  '正对镜头，露出眉毛和耳朵，表情自然',
  '面朝光线，脸上不要有明显阴影',
  '不用找白墙，穿深色上衣会更好看'
]
const QUESTIONS = [
  ['能戴眼镜吗？', '建议摘掉眼镜，避免反光。部分证件不允许戴眼镜。'],
  ['头发怎么处理？', '把头发拨开，露出眉毛和耳朵。'],
  ['可以化妆吗？', '淡妆可以。']
]

export default function ShootGuidePage() {
  const { params } = useRouter()
  const [skip, setSkip] = useState(() => Taro.getStorageSync(SKIP_GUIDE_KEY) === true)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)

  async function openCamera(album = false): Promise<void> {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    try {
      await navigate(PAGES.camera, { spec_code: params.spec_code, album: album ? 1 : undefined })
    } catch (e) {
      await handleError(e)
    } finally {
      locked.current = false
      setBusy(false)
    }
  }

  return (
    <View className='shoot-guide-page'>
      <Text className='shoot-guide-page__title'>这样拍，一次过</Text>
      <View className='shoot-guide-page__examples'>
        {EXAMPLES.map(({ kind, label }) => (
          <View className={`shoot-example shoot-example--${kind}`} key={kind}>
            <View className='shoot-example__portrait' ariaHidden>
              <View className='shoot-example__shoulders' />
              <View className='shoot-example__head' />
            </View>
            <Text className='shoot-example__label'>{label}</Text>
          </View>
        ))}
      </View>

      <View className='shoot-guide-page__tips'>
        {TIPS.map((tip, index) => (
          <View className='shoot-guide-page__tip' key={tip}>
            <Text className='shoot-guide-page__number'>{index + 1}.</Text>
            <Text>{tip}</Text>
          </View>
        ))}
      </View>

      <View className='shoot-guide-faq'>
        <Button
          className='cell-btn shoot-guide-faq__toggle'
          ariaLabel={expanded ? '收起常见问题' : '展开常见问题'}
          onClick={() => setExpanded(!expanded)}
        >
          <Text>常见问题</Text>
          <View className={`shoot-guide-faq__arrow${expanded ? ' shoot-guide-faq__arrow--open' : ''}`} ariaHidden />
        </Button>
        {expanded ? QUESTIONS.map(([question, answer]) => (
          <View className='shoot-guide-faq__item' key={question}>
            <Text className='shoot-guide-faq__question'>{question}</Text>
            <Text className='shoot-guide-faq__answer'>{answer}</Text>
          </View>
        )) : null}
      </View>

      <View className='bottom-bar shoot-guide-page__bottom'>
        <View className='shoot-guide-page__actions'>
          <Button className='btn-native' disabled={busy} onClick={() => void openCamera()}>开始拍照</Button>
          <Button className='btn-native btn-native--plain' disabled={busy} onClick={() => void openCamera(true)}>
            从相册选
          </Button>
        </View>
        <CheckboxGroup onChange={(e) => {
          const nextSkip = e.detail.value.includes('skip')
          Taro.setStorageSync(SKIP_GUIDE_KEY, nextSkip)
          setSkip(nextSkip)
        }}>
          <Label className='shoot-guide-page__skip'>
            <Checkbox value='skip' checked={skip} color='#2f6cc8' />
            <Text>下次不再提示</Text>
          </Label>
        </CheckboxGroup>
      </View>
    </View>
  )
}
