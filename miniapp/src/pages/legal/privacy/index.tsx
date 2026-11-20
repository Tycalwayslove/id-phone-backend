import LegalDocument from '../LegalDocument'
import PrivacyPopup from '../../../components/PrivacyPopup'
import { LEGAL_PAGES } from '../routes'

const sections = [
  { title: '运营主体与适用范围', body: '运营主体、生效日期及政策版本待填写。本模板适用于智拍证件照小程序。' },
  { title: '收集的信息', body: '微信账号标识和你提供的昵称、头像与手机号。你在制作证件照时拍摄或选取的照片，办理回执时填写的姓名、身份证号码等必要资料，以及产生的订单、支付状态和通知授权记录。' },
  { title: '使用目的', body: '用于登录和账号管理、制作和保存照片、办理回执、处理订单与支付，以及在授权后发送回执结果或到期提醒。加企业微信和关注公众号由你自愿选择。照片仅用于你请求的服务，不用于营销。有关联系方式用于运营或营销的授权和退出方式待确认。' },
  { title: '存储期限与安全', body: '照片按所购套餐约定的期限提供云端保管服务。照片到期后的清理期限及账号、订单、回执等记录的具体保存期限待填写。手机号和身份证号加密存储。' },
  { title: '注销与照片删除', body: '你可在「我的」选择「注销账号」。注销后立即删除账号下的全部照片文件，删除后无法恢复。其他记录的处理方式和期限待填写。' },
  { title: '第三方服务', body: '微信支付处理交易及支付结果。回执服务商处理办理所需的照片和申请资料。云存储服务商存放照片文件。各服务商的主体、共享字段和隐私政策链接待填写。' },
  { title: '你的权利', body: '你可申请访问、更正、删除或获取个人信息副本，撤回授权或注销账号。你可通过微信设置管理授权。具体申请渠道、核验流程和处理时限待填写。' },
  { title: '联系我们', body: '个人信息保护负责人、客服邮箱、联系电话及通讯地址待填写。' }
]

export default function Privacy() {
  return (
    <LegalDocument title='隐私政策' sections={sections}>
      <PrivacyPopup page={LEGAL_PAGES.privacy} />
    </LegalDocument>
  )
}
