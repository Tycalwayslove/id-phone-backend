import { Button, Form, Select } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { adminApi, type PhotoFilters } from '../api/admin'
import { PhotoGallery } from '../components/photo-gallery'
import { FilterForm, IdFilter, Loading, PageHeading, Problem, useCursorList, useFilters } from '../components/ui'
import { enumOptions, mattingLevels, photoStatus, qualityLevels } from '../format'

function PhotoList({ userId }: { userId?: number }) {
  const search = useFilters<PhotoFilters>()
  const filters = search.filters ?? { user_id: userId }
  const query = useCursorList('photos', (cursor, signal) => adminApi.photos({ ...filters, cursor }, signal), search.version)

  return (
    <>
      <PageHeading title="照片" />
      <FilterForm<PhotoFilters> initialValues={{ user_id: userId }} onFinish={search.apply}>
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
      {query.isError && <Problem error={query.error} retry={() => {
        void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())
      }} />}
      {query.isPending && <Loading />}
      {query.data && <PhotoGallery photos={query.rows} />}
      {query.data && query.rows.length > 0 && (
        <div className="table-footer">
          <span>已加载 {query.rows.length} 张</span>
          {query.hasNextPage && (
            <Button loading={query.isFetchingNextPage} disabled={query.isFetching} onClick={() => { void query.fetchNextPage() }}>
              加载更多
            </Button>
          )}
        </div>
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
