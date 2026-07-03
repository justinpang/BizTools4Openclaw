"""business/customer_send — T11 商机多渠道触达。"""

from business.customer_send.models import (
    BatchSendParams,
    BatchSendResult,
    H5PageSpec,
    SendBehaviorLog,
    SendTarget,
    SingleSendResult,
)
from business.customer_send.pipeline import CustomerSendPipeline
from business.customer_send.registry import (
    TASK_HANDLER_NAME,
    async_run,
    list_runs,
    run_batch,
)
from business.customer_send.template_engine import build_variables, render, render_from_string

__all__ = [
    "BatchSendParams",
    "BatchSendResult",
    "H5PageSpec",
    "SendBehaviorLog",
    "SendTarget",
    "SingleSendResult",
    "CustomerSendPipeline",
    "run_batch",
    "async_run",
    "list_runs",
    "TASK_HANDLER_NAME",
    "render",
    "render_from_string",
    "build_variables",
]
