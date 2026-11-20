/** 选图、上传与创建照片 */
import Taro from '@tarojs/taro'
import type { components } from '../api/schema'
import { createPhoto, uploadPhotoFile } from '../api/photos'
import { isUserCancel } from './errors'

type PhotoOut = components['schemas']['PhotoOut']
export type PhotoSource = components['schemas']['PhotoCreate']['source']

/** 选一张图，返回本地临时路径；用户取消返回 null */
export async function pickPhotoFile(source: PhotoSource): Promise<string | null> {
  const sourceType: Array<'camera' | 'album'> = [source === 'camera' ? 'camera' : 'album']
  try {
    if (Taro.getEnv() === Taro.ENV_TYPE.WEAPP) {
      const res = await Taro.chooseMedia({ count: 1, mediaType: ['image'], sourceType, camera: 'back' })
      return res.tempFiles[0]?.tempFilePath ?? null
    }
    const res = await Taro.chooseImage({ count: 1, sourceType })
    return res.tempFilePaths[0] ?? null
  } catch (e) {
    if (isUserCancel(e)) return null
    throw e
  }
}

/** 用相机或相册返回的临时文件创建照片 */
export async function createPhotoFromFile(path: string, source: PhotoSource): Promise<PhotoOut> {
  await Taro.showLoading({ title: '上传中', mask: true })
  try {
    const up = await uploadPhotoFile(path)
    return await createPhoto({ file_id: up.file_id, source })
  } finally {
    Taro.hideLoading()
  }
}

/** 拍照/相册选图并创建照片；取消返回 null，接口失败抛 ApiError */
export async function pickAndCreatePhoto(source: PhotoSource): Promise<PhotoOut | null> {
  const path = await pickPhotoFile(source)
  return path ? createPhotoFromFile(path, source) : null
}
