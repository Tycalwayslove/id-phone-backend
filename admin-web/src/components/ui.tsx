import { Alert, Button, Empty, Form, Input, InputNumber, Space, Spin, Table, Tag, type FormProps, type TableProps } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useId, useState, type ReactNode } from 'react'
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

export function FilterForm<T>({ children, onFinish }: { children: ReactNode; onFinish: FormProps<T>['onFinish'] }) {
  const [form] = Form.useForm<T>()
  return (
    <Form<T> form={form} layout="vertical" className="filter-bar" onFinish={onFinish}>
      {children}
      <Space className="filter-actions">
        <Button type="primary" htmlType="submit">查询</Button>
        <Button onClick={() => { form.resetFields(); form.submit() }}>重置</Button>
      </Space>
    </Form>
  )
}

type Page<Row> = { items: Row[]; next_cursor?: string | null }

export function useCursorList<Row>(
  resource: string,
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<Page<Row>>,
  filterVersion = 0,
  enabled = true,
) {
  const instance = useId()
  const query = useInfiniteQuery({
    queryKey: [resource, instance, filterVersion],
    enabled,
    queryFn: ({ pageParam, signal }) => fetchPage(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  })

  return { ...query, rows: query.data?.pages.flatMap((page) => page.items) ?? [] }
}

export function useFilters<T extends object>() {
  const [search, setSearch] = useState<{ filters: T; version: number }>()
  return {
    filters: search?.filters,
    version: search?.version ?? 0,
    apply: (filters: T) => setSearch((previous) => ({ filters, version: (previous?.version ?? 0) + 1 })),
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

export function CursorTable<Row extends object>({ query, ...props }: Omit<TableProps<Row>, 'dataSource'> & {
  query: ReturnType<typeof useCursorList<Row>>
}) {
  return (
    <div className="data-surface">
      {query.isError && (
        <Problem error={query.error} retry={() => { void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch()) }} />
      )}
      <DataTable<Row> {...props} dataSource={query.rows} loading={query.isPending} />
      {query.data && query.rows.length > 0 && (
        <div className="table-footer">
          <span>已加载 {query.rows.length} 条</span>
          {query.hasNextPage && (
            <Button loading={query.isFetchingNextPage} disabled={query.isFetching && !query.isFetchingNextPage} onClick={() => { void query.fetchNextPage() }}>
              加载更多
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
