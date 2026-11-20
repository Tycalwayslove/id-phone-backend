"""黔微云证件照回执适配器。"""

from app.integrations.receipt_providers._zjz_common import ZjzReceiptProvider


class QianweiyunProvider(ZjzReceiptProvider):
    """黔微云通道，提交时同样携带回调地址。"""
