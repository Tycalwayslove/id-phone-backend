import { Text, View } from '@tarojs/components'
import type { components } from '../../api/schema'
import { formatDate } from '../../utils/format'
import { PAGES, navigate } from '../../utils/nav'
import './index.scss'

type EntitlementOut = components['schemas']['EntitlementOut']

export default function EntitlementCard({ entitlement: e, showDetails = false }: {
  entitlement: EntitlementOut
  showDetails?: boolean
}) {
  return (
    <View className='card ent-item'>
      <View className='ent-item__head'>
        <Text className='ent-item__name'>{e.plan_name}</Text>
        <Text className={`ent-item__state${e.is_active ? ' ent-item__state--on' : ''}`}>
          {e.is_active ? '有效' : '已失效'}
        </Text>
      </View>
      <View className='ent-item__row'>
        <Text className='hint'>有效期</Text>
        <Text>
          {formatDate(e.starts_at)} 至 {formatDate(e.ends_at)}
        </Text>
      </View>
      <View className='ent-item__row'>
        <Text className='hint'>回执次数</Text>
        <Text>
          {e.receipt_quota_total > 0 ? `剩余 ${e.receipt_quota_left} / 共 ${e.receipt_quota_total}` : '不含回执'}
        </Text>
      </View>
      <View className='ent-item__row'>
        <Text className='hint'>更换规格</Text>
        <Text>{e.spec_change ? '期内无限换' : '不支持'}</Text>
      </View>
      {e.resubmit_limit > 0 ? (
        <View className='ent-item__row'>
          <Text className='hint'>驳回免费重提</Text>
          <Text>{e.resubmit_limit} 次</Text>
        </View>
      ) : null}
      {e.one_person ? (
        <View className='ent-item__row'>
          <Text className='hint'>使用限制</Text>
          <Text>一卡一人</Text>
        </View>
      ) : null}
      <View className='ent-item__row'>
        <Text className='hint'>适用照片</Text>
        {e.photo_id !== null ? (
          <Text className='ent-item__link' onClick={() => navigate(PAGES.photoDetail, { id: e.photo_id })}>
            查看照片 &gt;
          </Text>
        ) : (
          <Text>全部照片</Text>
        )}
      </View>
      <View className='ent-item__actions'>
        {showDetails ? (
          <Text className='ent-item__link' onClick={() => navigate(PAGES.entitlementDetail, { id: e.id })}>
            查看详情
          </Text>
        ) : null}
        {e.can_renew ? (
          <Text
            className='ent-item__btn'
            onClick={() => navigate(PAGES.plans, { renew_entitlement_id: e.id })}
          >
            续费
          </Text>
        ) : null}
        {e.is_active ? (
          <Text
            className='ent-item__btn'
            onClick={() =>
              navigate(PAGES.plans, { parent_entitlement_id: e.id, photo_id: e.photo_id })
            }
          >
            加办一种回执
          </Text>
        ) : null}
      </View>
    </View>
  )
}
