"""集中导入所有模型，Alembic 才能“看见”它们。新增模型文件后记得在这里加一行。"""

from app.models.auth import AdminSession, AuthSession, IdempotencyKey
from app.models.base import Base
from app.models.ops import AdminUser, AuditLog, NotifyTask
from app.models.photo import File, Photo, PhotoRender, ShareLink
from app.models.receipt import ProviderCallback, ReceiptApplication, ReceiptAttempt
from app.models.spec import Provider, ProviderSpec, RouteRule, Spec
from app.models.trade import (
    Entitlement,
    EntitlementLedger,
    EntitlementQuota,
    Order,
    OrderItem,
    Payment,
    Plan,
    PlanBenefit,
    Refund,
)
from app.models.user import Channel, ClientApp, User, UserIdentity, UserTag, WecomContact

__all__ = [
    "AdminSession",
    "AdminUser",
    "AuditLog",
    "AuthSession",
    "Base",
    "Channel",
    "ClientApp",
    "Entitlement",
    "EntitlementLedger",
    "EntitlementQuota",
    "File",
    "IdempotencyKey",
    "NotifyTask",
    "Order",
    "OrderItem",
    "Payment",
    "Photo",
    "PhotoRender",
    "Plan",
    "PlanBenefit",
    "Provider",
    "ProviderCallback",
    "ProviderSpec",
    "ReceiptApplication",
    "ReceiptAttempt",
    "Refund",
    "RouteRule",
    "ShareLink",
    "Spec",
    "User",
    "UserIdentity",
    "UserTag",
    "WecomContact",
]
