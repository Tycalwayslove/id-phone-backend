import { PictureOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Empty, Image, Modal, Select, Space } from 'antd'
import { useEffect, useState } from 'react'
import { adminApi } from '../api/admin'
import type { Schema } from '../api/client'
import { dateText, mattingLevels, photoSources, photoStatus, qualityLevels } from '../format'
import { Loading, Problem, Section, Status } from './ui'

type Photo = Schema['AdminPhotoOut']
type PhotoDetail = Schema['AdminPhotoDetail']

export function PhotoView({ id, onClose }: { id: number; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['photos', 'detail', id],
    queryFn: ({ signal }) => adminApi.photo(id, signal),
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  const { data, refetch, dataUpdatedAt } = query
  useEffect(() => {
    if (!data) return
    const expiresAt = Date.parse(data.urls_expire_at)
    const refreshAt = expiresAt > dataUpdatedAt
      ? Math.min(expiresAt, dataUpdatedAt + 590_000)
      : dataUpdatedAt + 590_000
    let timer: number | undefined
    function scheduleRefresh() {
      window.clearTimeout(timer)
      if (document.hidden) return
      const remaining = refreshAt - Date.now()
      if (remaining <= 0) void refetch({ cancelRefetch: false })
      else timer = window.setTimeout(scheduleRefresh, remaining)
    }
    scheduleRefresh()
    document.addEventListener('visibilitychange', scheduleRefresh)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', scheduleRefresh)
    }
  }, [data, dataUpdatedAt, refetch])

  return (
    <Modal open title={`照片 #${id}`} width={740} footer={null} onCancel={onClose}>
      {query.isError
        ? <Problem error={query.error} retry={() => { void refetch() }} />
        : data
          ? <PhotoContents photo={data} refreshing={query.isFetching} refresh={() => { void refetch() }} />
          : <Loading />}
    </Modal>
  )
}

function PhotoContents({ photo, refreshing, refresh }: { photo: PhotoDetail; refreshing: boolean; refresh: () => void }) {
  const variants = [
    { key: 'original', label: '原图', url: photo.original_url, render: null },
    { key: 'matting', label: '抠图底片', url: photo.matting_url, render: null },
    ...photo.renders.map((render) => ({
      key: `render-${render.id}`,
      label: `${render.spec_name} / ${render.bg_color} / 美颜 ${render.beauty_level} / ${render.watermarked ? '有水印' : '无水印'}`,
      url: render.url,
      render,
    })),
  ]
  const [selected, setSelected] = useState<string>()
  const [failedUrl, setFailedUrl] = useState<string>()
  const variant = variants.find(({ key }) => key === selected) ?? variants.find(({ url }) => url) ?? variants[0]

  return (
    <>
      <Select
        className="photo-variant"
        aria-label="照片版本"
        value={variant.key}
        onChange={setSelected}
        options={variants.map(({ key, label, url }) => ({ value: key, label: url ? label : `${label}（文件不可用）` }))}
      />
      <div className="photo-stage">
        {variant.url
          ? <Image
            src={variant.url}
            alt={variant.label}
            referrerPolicy="no-referrer"
            onError={() => { if (variant.url) setFailedUrl(variant.url) }}
          />
          : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可查看的文件" />}
      </div>
      {variant.url && variant.url === failedUrl && (
        <Alert
          type="warning" showIcon message="图片加载失败"
          action={<Button size="small" loading={refreshing} onClick={() => { setFailedUrl(undefined); refresh() }}>刷新图片</Button>}
        />
      )}
      {variant.render && (
        <Descriptions size="small" column={1} items={[{ label: '导出时间', children: dateText(variant.render.created_at) }]} />
      )}
      <Section title="拍后检测">
        {photo.quality
          ? <>
            <Status value={photo.quality.level} labels={qualityLevels} />
            {photo.quality.issues.length > 0 && <ul className="photo-issues">
              {photo.quality.issues.map(({ code, message }) => <li key={code}>{message}</li>)}
            </ul>}
          </>
          : <span>暂无检测记录</span>}
      </Section>
    </>
  )
}

export function PhotoGallery({ photos }: { photos: Photo[] }) {
  const [openId, setOpenId] = useState<number>()
  if (!photos.length && openId === undefined) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无照片" />

  return (
    <>
      <ul className="photo-gallery">
        {photos.map((photo) => (
          <li key={photo.id}>
            <button className="photo-thumb" type="button" aria-label={`查看照片 ${photo.id}`} onClick={() => setOpenId(photo.id)}>
              {photo.thumbnail_url
                ? <img src={photo.thumbnail_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
                : <PictureOutlined aria-hidden />}
            </button>
            <div className="photo-caption">
              <Space wrap size={[6, 4]}><strong>#{photo.id}</strong><Status value={photo.status} labels={photoStatus} /></Space>
              <span>用户 {photo.user_id} ／ {photoSources[photo.source]}</span>
              <span>抠图 {photo.matting_level ? mattingLevels[photo.matting_level] : '—'}</span>
              <span>检测 {photo.quality_level ? qualityLevels[photo.quality_level] : '—'}</span>
              <span>创建 {dateText(photo.created_at)}</span>
              <span>保管到期 {dateText(photo.retain_until)}</span>
            </div>
          </li>
        ))}
      </ul>
      {openId !== undefined && <PhotoView key={openId} id={openId} onClose={() => setOpenId(undefined)} />}
    </>
  )
}
