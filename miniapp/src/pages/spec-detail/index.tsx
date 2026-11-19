import { useEffect, useState } from 'react'
import { Text, View } from '@tarojs/components'
import { useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { getSpec } from '../../api/specs'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { handleError } from '../../utils/errors'
import { formatMm, formatSizeRange } from '../../utils/format'
import { PAGES, navigate } from '../../utils/nav'
import { pickAndCreatePhoto } from '../../utils/pickPhoto'
import type { PhotoSource } from '../../utils/pickPhoto'
import './index.scss'

type SpecDetail = components['schemas']['SpecDetail']

export default function SpecDetailPage() {
  const { params } = useRouter()
  const code = params.code ?? ''
  const [spec, setSpec] = useState<SpecDetail | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!code) return
    getSpec(code)
      .then(setSpec)
      .catch((e: unknown) => handleError(e))
  }, [code])

  async function choose(source: PhotoSource): Promise<void> {
    if (busy || !spec) return
    setBusy(true)
    try {
      const photo = await pickAndCreatePhoto(source)
      if (photo) await navigate(PAGES.editor, { photo_id: photo.id, spec_code: spec.code })
    } catch (e) {
      await handleError(e)
    } finally {
      setBusy(false)
    }
  }

  if (!spec) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }

  const mm = formatMm(spec.width_mm, spec.height_mm)
  const sizeRange = formatSizeRange(spec.file_size_min_kb, spec.file_size_max_kb)

  return (
    <PageContainer withBottomBar>
      <View className='card'>
        <Text className='spec-detail__name'>{spec.name}</Text>
        <View className='spec-detail__row'>
          <Text className='spec-detail__label'>像素尺寸</Text>
          <Text>
            {spec.width_px}×{spec.height_px}px
          </Text>
        </View>
        <View className='spec-detail__row'>
          <Text className='spec-detail__label'>物理尺寸</Text>
          <Text>{mm || '官方未规定'}</Text>
        </View>
        <View className='spec-detail__row'>
          <Text className='spec-detail__label'>分辨率</Text>
          <Text>{spec.dpi} dpi</Text>
        </View>
        {sizeRange ? (
          <View className='spec-detail__row'>
            <Text className='spec-detail__label'>文件大小</Text>
            <Text>{sizeRange}</Text>
          </View>
        ) : null}
        <View className='spec-detail__row'>
          <Text className='spec-detail__label'>可选底色</Text>
          <View className='spec-detail__colors'>
            {spec.bg_colors.map((c) => (
              <View key={c} className='spec-detail__color' style={{ background: c }} />
            ))}
          </View>
        </View>
        <View className='spec-detail__row'>
          <Text className='spec-detail__label'>官方回执</Text>
          <Text className={spec.supports_receipt ? 'spec-detail__yes' : ''}>
            {spec.supports_receipt ? '支持办理' : '暂不支持'}
          </Text>
        </View>
      </View>

      <View className='card'>
        <Text className='spec-detail__notice-title'>办理须知</Text>
        <View className='spec-detail__notice'>
          <Text>1. 请使用正面免冠、光线均匀、背景简洁的照片，五官清晰无遮挡。</Text>
          <Text>2. 不要使用过度美颜或滤镜，部分官方规格不允许修图。</Text>
          {spec.supports_receipt ? (
            <>
              <Text>3. 办理回执需填写本人真实姓名和身份证号，信息仅用于办理，平台加密保存。</Text>
              {spec.official_valid_days ? (
                <Text>4. 官方回执有效期约 {spec.official_valid_days} 天，过期需重新办理。</Text>
              ) : null}
            </>
          ) : null}
        </View>
      </View>

      <View className='bottom-bar'>
        <Button block type='default' disabled={busy} onClick={() => choose('camera')}>
          拍照
        </Button>
        <Button block type='primary' disabled={busy} onClick={() => choose('upload')}>
          从相册选
        </Button>
      </View>
    </PageContainer>
  )
}
