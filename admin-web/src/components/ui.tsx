import { Alert, Button, Empty, Form, Input, InputNumber, Space, Spin, Table, Tag, type FormProps, type TablePaginationConfig, type TableProps } from 'antd'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { startTransition, useEffect, useId, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { PagingParams } from '../api/admin'
import { errorText } from '../api/client'

export function PageHeading({ title, action }: { title: string; action?: ReactNode }) {
  return <div className="page-heading"><h1>{title}</h1>{action}</div>
}

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="detail-section">
      <div className="detail-section-heading"><h3>{title}</h3>{action}</div>
      {children}
    </section>
  )
}

export function Problem({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Alert
      showIcon
      type="error"
      message={errorText(error)}
      action={retry && <Button size="small" onClick={retry}>重试</Button>}
    />
  )
}

export function Loading() {
  return <div className="loading"><Spin aria-label="正在加载" /></div>
}

const statusColors: Record<string, string> = {
  active: 'green', enabled: 'green', on_sale: 'green', paid: 'green', completed: 'green',
  success: 'green', sent: 'green', processing: 'blue', submitted: 'blue', pending: 'gold', unknown: 'gold',
  rejected: 'volcano', failed: 'red', circuit_open: 'red', part_refunded: 'purple', refunded: 'purple',
}

export function Status<T extends string>({ value, labels }: { value: T; labels: Record<T, string> }) {
  return <Tag color={statusColors[value]}>{labels[value] ?? value}</Tag>
}

export function TextFilter({ name, label, minLength, maxLength }: {
  name: string; label: string; minLength?: number; maxLength: number
}) {
  return (
    <Form.Item name={name} label={label} rules={minLength ? [{ transform: (value) => value?.trim(), min: minLength, message: `至少输入 ${minLength} 个字符` }] : []}>
      <Input allowClear maxLength={maxLength} autoComplete="off" />
    </Form.Item>
  )
}

export function IdFilter({ name = 'user_id', label = '用户 ID' }: { name?: string; label?: string }) {
  return (
    <Form.Item name={name} label={label} rules={[{ type: 'integer', min: 1, max: Number.MAX_SAFE_INTEGER, message: '请输入有效 ID' }]}>
      <InputNumber min={1} max={Number.MAX_SAFE_INTEGER} step={1} controls={false} />
    </Form.Item>
  )
}

export function FilterForm<T extends object>({ children, onFinish, initialValues }: {
  children: ReactNode; onFinish: FormProps<T>['onFinish']; initialValues?: T
}) {
  const [form] = Form.useForm<T>()
  return (
    <Form<T> form={form} layout="vertical" className="filter-bar" onFinish={onFinish} initialValues={initialValues}>
      {children}
      <Space className="filter-actions">
        <Button type="primary" htmlType="submit">查询</Button>
        <Button onClick={() => { form.resetFields(); form.submit() }}>重置</Button>
      </Space>
    </Form>
  )
}

type Page<Row> = PagingParams & { items: Row[]; total: number }
const pageSizes = [10, 20, 50, 100] as const satisfies readonly PagingParams['page_size'][]
const defaultPageSize = 20

function isPageSize(value: number): value is PagingParams['page_size'] {
  return pageSizes.some((size) => size === value)
}

export function usePagedList<Filters extends object, Row>(
  resource: string,
  fetchPage: (params: Filters & PagingParams, signal: AbortSignal) => Promise<Page<Row>>,
  initialFilters: Filters,
  { prefix = '', enabled = true }: { prefix?: string; enabled?: boolean } = {},
) {
  const instance = useId()
  const [search, setSearch] = useSearchParams()
  const [filterState, setFilters] = useState({ values: initialFilters, version: 0 })
  const pageKey = `${prefix}page`
  const sizeKey = `${prefix}page_size`
  const requestedPage = Number(search.get(pageKey))
  const requestedSize = Number(search.get(sizeKey))
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  const pageSize = isPageSize(requestedSize) ? requestedSize : defaultPageSize
  const query = useQuery({
    // 筛选条件可能含手机号，只用版本号作为缓存键。
    queryKey: [resource, instance, filterState.version, page, pageSize],
    enabled,
    queryFn: ({ signal }) => fetchPage({ ...filterState.values, page, page_size: pageSize }, signal),
    placeholderData: keepPreviousData,
  })

  const total = query.data?.total
  const lastPage = Math.max(1, Math.ceil((total ?? 0) / pageSize))
  useEffect(() => {
    if (total === undefined || query.isPlaceholderData || page <= lastPage) return
    const next = new URLSearchParams(search)
    next.set(pageKey, String(lastPage))
    setSearch(next, { replace: true })
  }, [total, query.isPlaceholderData, page, lastPage, search, pageKey, setSearch])

  function setPage(nextPage: number, nextSize: number, replace = false) {
    if (nextPage === page && nextSize === pageSize) return
    const next = new URLSearchParams(search)
    next.set(pageKey, String(nextPage))
    next.set(sizeKey, String(nextSize))
    setSearch(next, { replace })
  }

  const pagination: TablePaginationConfig = {
    current: page,
    pageSize: query.isPlaceholderData ? (query.data?.page_size ?? pageSize) : pageSize,
    total: total ?? 0,
    pageSizeOptions: [...pageSizes],
    showTotal: (count) => `共 ${count} 条`,
    showSizeChanger: true,
    showQuickJumper: true,
    onChange: (nextPage, nextSize) => setPage(nextSize === pageSize ? nextPage : 1, nextSize),
  }
  return {
    ...query,
    rows: query.data?.items ?? [],
    pagination,
    apply: (values: Filters) => startTransition(() => {
      setFilters((previous) => ({ values, version: previous.version + 1 }))
      setPage(1, pageSize, true)
    }),
  }
}

export function DataTable<Row extends object>(props: TableProps<Row>) {
  return (
    <Table<Row>
      size="middle"
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无记录" /> }}
      {...props}
    />
  )
}

export function PagedTable<Row extends object>({ query, ...props }: Omit<TableProps<Row>, 'dataSource' | 'pagination' | 'loading'> & {
  query: Pick<ReturnType<typeof usePagedList<object, Row>>, 'rows' | 'pagination' | 'isError' | 'error' | 'refetch' | 'isFetching'>
}) {
  return (
    <div className="data-surface">
      {query.isError && <Problem error={query.error} retry={() => { void query.refetch() }} />}
      <DataTable<Row> {...props} dataSource={query.rows} pagination={query.pagination} loading={query.isFetching} />
    </div>
  )
}
