import { Form, Pagination, Select, Spin } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { adminApi, type PhotoFilters } from '../api/admin'
import { PhotoGallery } from '../components/photo-gallery'
import { FilterForm, IdFilter, Loading, PageHeading, Problem, usePagedList } from '../components/ui'
import { enumOptions, mattingLevels, photoStatus, qualityLevels } from '../format'

function PhotoList({ userId }: { userId?: number }) {
  const initialFilters: PhotoFilters = { user_id: userId }
  const query = usePagedList('photos', adminApi.photos, initialFilters)

  return (
    <>
      <PageHeading title="照片" />
      <FilterForm<PhotoFilters> initialValues={initialFilters} onFinish={query.apply}>
        <IdFilter />
        <Form.Item label="照片状态" name="status">
          <Select allowClear className="filter-select" options={enumOptions(photoStatus)} />
        </Form.Item>
        <Form.Item label="抠图精度" name="matting_level">
          <Select allowClear className="filter-select" options={enumOptions(mattingLevels)} />
        </Form.Item>
        <Form.Item label="拍后检测" name="quality_level">
          <Select allowClear className="filter-select" options={enumOptions(qualityLevels)} />
        </Form.Item>
      </FilterForm>
      {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
      {query.isPending && <Loading />}
      {query.data && (
        <>
          <Spin spinning={query.isFetching}><PhotoGallery photos={query.rows} /></Spin>
          <Pagination className="photo-pagination" {...query.pagination} />
        </>
      )}
    </>
  )
}

export default function Photos() {
  const [params] = useSearchParams()
  const id = Number(params.get('user_id'))
  const userId = Number.isSafeInteger(id) && id > 0 ? id : undefined
  return <PhotoList key={userId ?? 'all'} userId={userId} />
}
