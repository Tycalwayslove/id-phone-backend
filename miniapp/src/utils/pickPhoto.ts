/** 选图、上传与创建照片 */
import Taro from '@tarojs/taro'
import type { components } from '../api/schema'
import { createPhoto, uploadPhotoFile } from '../api/photos'
import { isUserCancel, UserFacingError } from './errors'

type PhotoOut = components['schemas']['PhotoOut']
export type PhotoSource = components['schemas']['PhotoCreate']['source']

/** 选一张图，返回本地临时路径；用户取消返回 null */
export async function pickPhotoFile(source: PhotoSource): Promise<string | null> {
  const sourceType: Array<'camera' | 'album'> = [source === 'camera' ? 'camera' : 'album']
  try {
    if (Taro.getEnv() === Taro.ENV_TYPE.WEAPP) {
      const res = await Taro.chooseMedia({ count: 1, mediaType: ['image'], sourceType, sizeType: ['compressed'], camera: 'back' })
      return res.tempFiles[0]?.tempFilePath ?? null
    }
    const res = await Taro.chooseImage({ count: 1, sourceType, sizeType: ['compressed'] })
    return res.tempFilePaths[0] ?? null
  } catch (e) {
    if (isUserCancel(e)) return null
    throw e
  }
}

/** 压缩后的目标大小；真机调试的上传上限是 2MB，后端上限 10MB */
const MAX_UPLOAD_BYTES = 1.8 * 1024 * 1024
const HARD_LIMIT_BYTES = 2 * 1024 * 1024
/** 只调画质逐级压缩（按尺寸压缩的参数在部分环境不支持，会直接失败） */
const QUALITY_STEPS = [80, 60, 40]

function fileSize(path: string): Promise<number | null> {
  const fs = Taro.getFileSystemManager()
  return new Promise((resolve) => {
    fs.getFileInfo({
      filePath: path,
      success: (res) => resolve(res.size),
      fail: () => {
        // 部分环境下临时文件 getFileInfo 会失败，改用 stat 再试一次
        try {
          const stat = fs.statSync(path) as unknown as { size?: number }
          resolve(typeof stat?.size === 'number' ? stat.size : null)
        } catch {
          console.warn('[上传压缩] 读取文件大小失败', path)
          resolve(null)
        }
      }
    })
  })
}

const kb = (bytes: number | null) => (bytes === null ? '未知' : `${Math.round(bytes / 1024)}KB`)

/** 照片太大时先在手机上压缩再上传；每一步都检查大小，并在调试台打印走了哪条路径 */
async function shrinkForUpload(path: string): Promise<string> {
  if (Taro.getEnv() !== Taro.ENV_TYPE.WEAPP) return path
  const original = await fileSize(path)
  if (original !== null && original <= MAX_UPLOAD_BYTES) return path
  let best = path
  let bestSize = original
  for (const quality of QUALITY_STEPS) {
    try {
      const { tempFilePath } = await Taro.compressImage({ src: path, quality })
      const size = await fileSize(tempFilePath)
      console.info(`[上传压缩] 画质 ${quality}：${kb(original)} → ${kb(size)}`)
      if (size !== null && (bestSize === null || size < bestSize)) {
        best = tempFilePath
        bestSize = size
      }
      if (size !== null && size <= MAX_UPLOAD_BYTES) break
    } catch (e) {
      console.warn(`[上传压缩] 画质 ${quality} 压缩失败`, e)
    }
  }
  if (bestSize !== null && bestSize > HARD_LIMIT_BYTES) {
    throw new UserFacingError('照片太大，请重新拍一张或换一张照片')
  }
  return best
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
