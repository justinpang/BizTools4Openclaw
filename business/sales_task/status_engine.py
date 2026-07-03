"""business/sales_task/status_engine — 商机状态流转 + 销售操作。"""

from __future__ import annotations

from infra.logger_setup import get_logger
from business.sales_task.models import (
    FollowUpRecord,
    Opportunity,
    OpportunityStatus,
    SalesOperationLog,
    _make_id,
    _now_iso,
)

logger = get_logger("sales_task.status")

# 合法状态流转表: from -> set of allowed targets
_TRANSITION_MAP: dict[str, set[str]] = {
    OpportunityStatus.NEW.value: {
        OpportunityStatus.ASSIGNED.value,
    },
    OpportunityStatus.ASSIGNED.value: {
        OpportunityStatus.FOLLOWING.value,
        OpportunityStatus.COMMUNICATING.value,
        OpportunityStatus.HIGH_INTENT.value,
        OpportunityStatus.CLOSED_WON.value,
        OpportunityStatus.LOST.value,
    },
    OpportunityStatus.FOLLOWING.value: {
        OpportunityStatus.COMMUNICATING.value,
        OpportunityStatus.HIGH_INTENT.value,
        OpportunityStatus.CLOSED_WON.value,
        OpportunityStatus.LOST.value,
    },
    OpportunityStatus.COMMUNICATING.value: {
        OpportunityStatus.HIGH_INTENT.value,
        OpportunityStatus.CLOSED_WON.value,
        OpportunityStatus.LOST.value,
        OpportunityStatus.FOLLOWING.value,
    },
    OpportunityStatus.HIGH_INTENT.value: {
        OpportunityStatus.CLOSED_WON.value,
        OpportunityStatus.LOST.value,
    },
    OpportunityStatus.CLOSED_WON.value: set(),
    OpportunityStatus.LOST.value: set(),
}


class StatusEngine:
    """状态流转 + 销售操作（标签/跟进记录）。"""

    def __init__(self, storage=None):
        self.storage = storage

    # ---------- 状态流转 ----------

    def can_transition(self, from_status: str, to_status: str) -> bool:
        allowed = _TRANSITION_MAP.get(from_status, set())
        return to_status in allowed

    def transition(
        self,
        opportunity: Opportunity,
        target_status: str,
        operator_sales_id: str,
        detail: str | None = None,
    ) -> tuple[bool, SalesOperationLog | None, str | None]:
        """执行状态流转。"""
        before = opportunity.status
        if before == target_status:
            return True, None, "NO_CHANGE"

        if not self.can_transition(before, target_status):
            reason = f"ILLEGAL_TRANSITION: {before} -> {target_status}"
            logger.warning(reason)
            return False, None, reason

        opportunity.status = target_status
        opportunity.updated_at = _now_iso()

        log = SalesOperationLog(
            log_id=_make_id("op", opportunity.tenant_id, opportunity.opportunity_id, "STATUS", target_status),
            tenant_id=opportunity.tenant_id,
            opportunity_id=opportunity.opportunity_id,
            sales_id=operator_sales_id,
            op_type="STATUS_CHANGE",
            before_value=before,
            after_value=target_status,
            detail=detail,
        )
        return True, log, None

    # ---------- 标签 ----------

    def add_tag(
        self,
        opportunity: Opportunity,
        tag: str,
        operator_sales_id: str,
    ) -> SalesOperationLog | None:
        tag = (tag or "").strip()
        if not tag:
            return None
        tags = list(opportunity.tags or [])
        if tag in tags:
            return None
        tags.append(tag)
        before = ",".join(tags[:-1]) if len(tags) > 1 else ""
        opportunity.tags = tags
        opportunity.updated_at = _now_iso()
        return SalesOperationLog(
            log_id=_make_id("op", opportunity.tenant_id, opportunity.opportunity_id, "TAG_ADD", tag),
            tenant_id=opportunity.tenant_id,
            opportunity_id=opportunity.opportunity_id,
            sales_id=operator_sales_id,
            op_type="TAG_ADD",
            before_value=before,
            after_value=",".join(tags),
            detail=tag,
        )

    def remove_tag(
        self,
        opportunity: Opportunity,
        tag: str,
        operator_sales_id: str,
    ) -> SalesOperationLog | None:
        tags = list(opportunity.tags or [])
        if tag not in tags:
            return None
        before = ",".join(tags)
        tags.remove(tag)
        opportunity.tags = tags
        opportunity.updated_at = _now_iso()
        return SalesOperationLog(
            log_id=_make_id("op", opportunity.tenant_id, opportunity.opportunity_id, "TAG_REMOVE", tag),
            tenant_id=opportunity.tenant_id,
            opportunity_id=opportunity.opportunity_id,
            sales_id=operator_sales_id,
            op_type="TAG_REMOVE",
            before_value=before,
            after_value=",".join(tags),
            detail=tag,
        )

    # ---------- 跟进记录 ----------

    def record_follow_up(
        self,
        opportunity: Opportunity,
        sales_id: str,
        channel: str,
        content: str,
        next_follow_at: str | None = None,
    ) -> tuple[FollowUpRecord, SalesOperationLog]:
        """写入一条跟进记录，并同步更新 opportunity.last_follow_at。"""
        now = _now_iso()
        opp_status_before = opportunity.status

        # 首次跟进 → 自动升级为 FOLLOWING
        if opportunity.status == OpportunityStatus.ASSIGNED.value:
            opportunity.status = OpportunityStatus.FOLLOWING.value

        opportunity.last_follow_at = now
        opportunity.updated_at = now

        follow = FollowUpRecord(
            follow_id=_make_id("fl", opportunity.tenant_id, opportunity.opportunity_id, channel),
            opportunity_id=opportunity.opportunity_id,
            tenant_id=opportunity.tenant_id,
            sales_id=sales_id,
            channel=channel,
            content=content[:4000],
            next_follow_at=next_follow_at,
        )
        log = SalesOperationLog(
            log_id=_make_id("op", opportunity.tenant_id, opportunity.opportunity_id, "FOLLOW_UP"),
            tenant_id=opportunity.tenant_id,
            opportunity_id=opportunity.opportunity_id,
            sales_id=sales_id,
            op_type="FOLLOW_UP",
            before_value=opp_status_before,
            after_value=opportunity.status,
            detail=f"channel={channel} next={next_follow_at or '-'}",
        )
        return follow, log


__all__ = ["StatusEngine"]
