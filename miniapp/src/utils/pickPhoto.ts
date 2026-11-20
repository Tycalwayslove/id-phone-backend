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

/** 上传前的长边上限（像素）：后端抠图最多用到 1024px，证件照成品只有几百像素，2000px 足够 */
const MAX_SIDE_PX = 2000
/** 压缩后仍超过这个大小就再降一次画质；真机调试的上传上限是 2MB */
const MAX_UPLOAD_BYTES = 1.8 * 1024 * 1024

function fileSize(path: string): Promise<number | null> {
  return new Promise((resolve) => {
    Taro.getFileSystemManager().getFileInfo({
      filePath: path,
      success: (res) => resolve(res.size),
      fail: () => resolve(null)
    })
  })
}

async function compress(path: string, quality: number, longSide: number, landscape: boolean): Promise<string> {
  const res = await Taro.compressImage({
    src: path,
    quality,
    ...(landscape ? { compressedWidth: longSide } : { compressedHeight: longSide })
  } as Taro.compressImage.Option)
  return res.tempFilePath
}

/** 照片太大时先在手机上缩小再上传；压缩失败就用原图（大小由后端兜底校验） */
async function shrinkForUpload(path: string): Promise<string> {
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEAPP) return path
  try {
    const [info, size] = await Promise.all([Taro.getImageInfo({ src: path }), fileSize(path)])
    const longSide = Math.max(info.width, info.height)
    if (longSide <= MAX_SIDE_PX && size !== null && size <= MAX_UPLOAD_BYTES) return path
    const target = Math.min(longSide, MAX_SIDE_PX)
    const landscape = info.width >= info.height
    let out = await compress(path, 85, target, landscape)
    const outSize = await fileSize(out)
    if (outSize !== null && outSize > MAX_UPLOAD_BYTES) out = await compress(path, 70, target, landscape)
    return out
  } catch {
    return path
  }
}

/** 用相机或相册返回的临时文件创建照片 */
export async function createPhotoFromFile(path: string, source: PhotoSource): Promise<PhotoOut> {
  await Taro.showLoading({ title: '上传中', mask: true })
  try {
    const up = await uploadPhotoFile(await shrinkForUpload(path))
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
