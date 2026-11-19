import { Text } from '@tarojs/components'
import type { components } from '../../api/schema'
import { APPLICATION_STATUS, ATTEMPT_STATUS, ORDER_STATUS } from '../../utils/status'
import type { StatusMeta } from '../../utils/status'
import './index.scss'

type S = components['schemas']

type Props =
  | { kind: 'application'; status: S['ApplicationOut']['status'] }
  | { kind: 'attempt'; status: S['AttemptOut']['status'] }
  | { kind: 'order'; status: S['OrderOut']['status'] }

function resolve(p: Props): StatusMeta {
  if (p.kind === 'application') return APPLICATION_STATUS[p.status]
  if (p.kind === 'attempt') return ATTEMPT_STATUS[p.status]
  return ORDER_STATUS[p.status]
}

/** 状态标签：中文文案 + 颜色 */
export default function StatusTag(props: Props) {
  const meta = resolve(props)
  return <Text className={`status-tag status-tag--${meta.tone}`}>{meta.text}</Text>
}
