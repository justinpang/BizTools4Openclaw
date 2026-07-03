"""business/customer_send/channels — 渠道发送适配器。"""

from business.customer_send.channels.email_channel import EmailChannel
from business.customer_send.channels.feishu_channel import FeishuChannel
from business.customer_send.channels.wechat_channel import WechatChannel
from business.customer_send.channels.h5_landing import H5Landing

__all__ = [
    "EmailChannel",
    "WechatChannel",
    "FeishuChannel",
    "H5Landing",
]
