import { useCallback, useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'
import { Button } from '@nutui/nutui-react-taro'
import type { components } from '../../api/schema'
import { resolveUrl } from '../../api/client'
import { deletePhoto, getPhoto } from '../../api/photos'
import EmptyState from '../../components/EmptyState'
import Loading from '../../components/Loading'
import PageContainer from '../../components/PageContainer'
import { handleError } from '../../utils/errors'
import { formatDate } from '../../utils/format'
import { PAGES, goBack, navigate, toInt } from '../../utils/nav'
import { saveRenderToAlbum } from '../../utils/saveImage'
import './index.scss'

type PhotoDetail = components['schemas']['PhotoDetail']

/** 照片详情页。路由参数：id */
export default function PhotoDetailPage() {
  const { params } = useRouter()
  const photoId = toInt(params.id)
  const [photo, setPhoto] = useState<PhotoDetail | null>(null)

  const load = useCallback(async () => {
    if (photoId === undefined) return
    try {
      setPhoto(await getPhoto(photoId))
    } catch (e) {
      await handleError(e)
    }
  }, [photoId])

  useDidShow(() => {
    void load()
  })

  async function download(renderId: number): Promise<void> {
    if (photoId === undefined) return
    try {
      await saveRenderToAlbum(photoId, renderId)
    } catch (e) {
      await handleError(e, { photoId })
    }
  }

  async function remove(): Promise<void> {
    if (photoId === undefined) return
    const r = await Taro.showModal({
      title: '删除照片',
      content: '删除后无法恢复，已生成的导出图也会一并删除。确定删除吗？',
      confirmText: '删除',
      confirmColor: '#FF3141'
    })
    if (!r.confirm) return
    try {
      await deletePhoto(photoId)
      await Taro.showToast({ title: '已删除', icon: 'success' })
      await goBack()
    } catch (e) {
      await handleError(e, { photoId })
    }
  }

  if (photoId === undefined) {
    return (
      <PageContainer>
        <View className='list-footer'>缺少参数</View>
      </PageContainer>
    )
  }
  if (!photo) {
    return (
      <PageContainer>
        <Loading />
      </PageContainer>
    )
  }

  const { access } = photo
  const expired = photo.status === 'expired' || (!access.active && !!access.access_until)

  return (
    <PageContainer withBottomBar>
      <View className='card pd-head'>
        <Image className='pd-head__img' src={resolveUrl(photo.original_url)} mode='aspectFill' />
        <View className='pd-head__info'>
          <Text className='pd-head__status'>
            {access.active ? `保管至 ${formatDate(access.access_until)}` : expired ? '保管期已过' : '未购买'}
          </Text>
          <Text className='hint'>{photo.source === 'camera' ? '拍照' : '相册'} · {formatDate(photo.created_at)}</Text>
          {expired ? (
            <Text className='pd-head__renew' onClick={() => navigate(PAGES.plans, { photo_id: photo.id })}>
              续费 &gt;
            </Text>
          ) : null}
        </View>
      </View>

      <View className='section-title'>
        <Text>导出图</Text>
      </View>
      {photo.renders.length === 0 ? (
        <EmptyState emoji='🖼️' title='还没有导出图' desc='点下方“换规格”开始制作' />
      ) : (
        <View className='list-gap'>
          {photo.renders.map((r) => (
            <View key={r.id} className='card pd-render'>
              <Image
                className='pd-render__img'
                src={resolveUrl(r.preview_url)}
                mode='aspectFit'
                onClick={() => Taro.previewImage({ urls: [resolveUrl(r.preview_url)] })}
              />
              <View className='pd-render__info'>
                <Text className='pd-render__name'>{r.spec_name}</Text>
                <Text className='hint'>
                  {r.width_px}×{r.height_px}px · {Math.max(1, Math.round(r.size_bytes / 1024))}KB
                </Text>
                <View className='pd-render__bg'>
                  <View className='pd-render__dot' style={{ background: r.bg_color }} />
                  <Text className='hint'>{r.watermarked ? '带水印预览' : '无水印'}</Text>
                </View>
                <View className='pd-render__btns'>
                  <Text
                    className='pd-render__btn'
                    onClick={() => navigate(PAGES.editor, { photo_id: photo.id, spec_code: r.spec_code })}
                  >
                    再编辑
                  </Text>
                  {!r.watermarked && access.active ? (
                    <Text className='pd-render__btn pd-render__btn--primary' onClick={() => download(r.id)}>
                      下载
                    </Text>
                  ) : null}
                </View>
              </View>
            </View>
          ))}
        </View>
      )}

      <View className='bottom-bar'>
        <Button block type='default' onClick={remove}>
          删除
        </Button>
        {expired ? (
          <Button block type='primary' onClick={() => navigate(PAGES.plans, { photo_id: photo.id })}>
            续费
          </Button>
        ) : null}
        <Button block type={expired ? 'default' : 'primary'} onClick={() => navigate(PAGES.specs, { photo_id: photo.id })}>
          换规格
        </Button>
      </View>
    </PageContainer>
  )
}
