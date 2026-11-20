import { Text } from '@tarojs/components'
import type { components } from '../../api/schema'
import { APPLICATION_STATUS, ATTEMPT_STATUS, orderStatus } from '../../utils/status'
import type { StatusMeta } from '../../utils/status'
import './index.scss'

type S = components['schemas']

type Props =
  | { kind: 'application'; status: S['ApplicationOut']['status'] }
  | { kind: 'attempt'; status: S['AttemptOut']['status'] }
  | { kind: 'order'; order: Pick<S['OrderOut'], 'status' | 'refund_pending'> }

function resolve(p: Props): StatusMeta {
  if (p.kind === 'application') return APPLICATION_STATUS[p.status]
  if (p.kind === 'attempt') return ATTEMPT_STATUS[p.status]
  return orderStatus(p.order)
}

/** 状态标签：中文文案 + 颜色 */
export default function StatusTag(props: Props) {
  const meta = resolve(props)
  return <Text className={`status-tag status-tag--${meta.tone}`}>{meta.text}</Text>
}
