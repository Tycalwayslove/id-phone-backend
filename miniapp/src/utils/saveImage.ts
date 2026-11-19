/** 下载无水印图并保存到相册（含相册权限被拒的处理） */
import Taro from '@tarojs/taro'
import { resolveUrl } from '../api/client'
import { getRenderDownload } from '../api/photos'

function isAuthDenied(e: unknown): boolean {
  const msg = typeof e === 'object' && e !== null ? (e as { errMsg?: unknown }).errMsg : undefined
  return typeof msg === 'string' && /auth deny|authorize no response|auth denied/i.test(msg)
}

export async function saveRenderToAlbum(photoId: number, renderId: number): Promise<void> {
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEAPP) {
    await Taro.showToast({ title: '请在小程序中保存到相册', icon: 'none' })
    return
  }
  await Taro.showLoading({ title: '保存中', mask: true })
  try {
    const dl = await getRenderDownload(photoId, renderId)
    const file = await Taro.downloadFile({ url: resolveUrl(dl.url) })
    if (file.statusCode !== 200) {
      Taro.hideLoading()
      await Taro.showToast({ title: '下载失败，请重试', icon: 'none' })
      return
    }
    await Taro.saveImageToPhotosAlbum({ filePath: file.tempFilePath })
    Taro.hideLoading()
    await Taro.showToast({ title: '已保存到相册', icon: 'success' })
  } catch (e) {
    Taro.hideLoading()
    if (isAuthDenied(e)) {
      const r = await Taro.showModal({
        title: '需要相册权限',
        content: '请在设置中允许“保存到相册”，再重新保存',
        confirmText: '去设置'
      })
      if (r.confirm) await Taro.openSetting()
      return
    }
    throw e
  }
}
