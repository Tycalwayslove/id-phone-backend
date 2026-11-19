import type { components } from './schema'
import { request, uploadFile } from './client'

type UploadOut = components['schemas']['UploadOut']
type PhotoOut = components['schemas']['PhotoOut']
type PhotoPage = components['schemas']['PhotoPage']
type PhotoDetail = components['schemas']['PhotoDetail']
type RenderOut = components['schemas']['RenderOut']
type DownloadOut = components['schemas']['DownloadOut']
type OkResponse = components['schemas']['OkResponse']

/** 上传原图（本地临时路径） */
export function uploadPhotoFile(filePath: string): Promise<UploadOut> {
  return uploadFile(filePath)
}

export function createPhoto(body: components['schemas']['PhotoCreate']): Promise<PhotoOut> {
  return request<PhotoOut>({ method: 'POST', path: '/photos', body })
}

export function listPhotos(cursor?: string | null, limit?: number): Promise<PhotoPage> {
  return request<PhotoPage>({ path: '/photos', query: { cursor, limit } })
}

export function getPhoto(photoId: number): Promise<PhotoDetail> {
  return request<PhotoDetail>({ path: `/photos/${photoId}` })
}

export function deletePhoto(photoId: number): Promise<OkResponse> {
  return request<OkResponse>({ method: 'DELETE', path: `/photos/${photoId}` })
}

export function createRender(
  photoId: number,
  body: components['schemas']['RenderCreate']
): Promise<RenderOut> {
  return request<RenderOut>({ method: 'POST', path: `/photos/${photoId}/renders`, body })
}

/** 取无水印图的临时下载链接（权益有效才可用） */
export function getRenderDownload(photoId: number, renderId: number): Promise<DownloadOut> {
  return request<DownloadOut>({ path: `/photos/${photoId}/renders/${renderId}/download` })
}
