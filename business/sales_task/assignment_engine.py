"""business/sales_task/assignment_engine — 商机自动分配引擎。"""

from __future__ import annotations

from infra.logger_setup import get_logger
from configs.settings import settings
from business.sales_task.models import (
    Opportunity,
    OpportunityStatus,
    SalesOperationLog,
    Salesperson,
    _make_id,
    _now_iso,
)

logger = get_logger("sales_task.assignment")


class AssignmentEngine:
    """基于行业/地域/分值 + 负载均衡的加权分配引擎。"""

    def __init__(self, storage=None):
        self.storage = storage
        s = settings.sales_task
        self.industry_weight = float(s.SALES_TASK_ASSIGN_INDUSTRY_WEIGHT)
        self.region_weight = float(s.SALES_TASK_ASSIGN_REGION_WEIGHT)
        self.score_weight = float(s.SALES_TASK_ASSIGN_SCORE_WEIGHT)
        self.min_score_threshold = int(s.SALES_TASK_ASSIGN_MIN_SCORE_THRESHOLD)
        self.unassigned_alert_ratio = float(s.SALES_TASK_BATCH_UNASSIGNED_ALERT_RATIO)

    # ---------- 评分 ----------

    def score_candidate(self, opportunity: Opportunity, salesperson: Salesperson) -> float:
        """计算一个销售员对某商机的加权分数。

        规则：必须至少满足「行业匹配」或「地域匹配」之一，否则返回 0（不分配）。
        """
        industry_match = (
            bool(opportunity.industry) and opportunity.industry in (salesperson.industries or [])
        )
        region_match = (
            bool(opportunity.region) and opportunity.region in (salesperson.regions or [])
        )
        # 硬性规则：行业或地域必须至少有一项匹配
        if not industry_match and not region_match:
            return 0.0

        score = 0.0
        if industry_match:
            score += self.industry_weight
        if region_match:
            score += self.region_weight
        if opportunity.score >= salesperson.min_score:
            score += self.score_weight
        if score <= 0:
            return 0.0
        # current_load + 1 防止除零，值越小分数越高
        return score * float(salesperson.weight) / (float(salesperson.current_load or 0) + 1.0)

    # ---------- 批量分配 ----------

    def assign_batch(
        self,
        opportunities: list[Opportunity],
        salespersons: list[Salesperson],
        *,
        dry_run: bool = False,
    ) -> dict:
        """对一批商机执行分配。

        返回: {
            assigned: int,
            unassigned: int,
            no_match_reasons: list[str],
            assignments: list[(opportunity_id, sales_id, score)],
            operation_logs: list[SalesOperationLog],
        }
        """
        result = {
            "assigned": 0,
            "unassigned": 0,
            "no_match_reasons": [],
            "assignments": [],
            "operation_logs": [],
        }

        if not opportunities:
            return result
        if not salespersons:
            result["unassigned"] = len(opportunities)
            result["no_match_reasons"].append(
                f"NO_SALES_CONFIG: tenant={opportunities[0].tenant_id}, 无销售员配置"
            )
            self._maybe_alert(result, total=len(opportunities))
            return result

        # 复制一份销售员对象以便在本批次内更新 load（不回写数据库）
        sales_copy = [
            Salesperson(**s.model_dump()) for s in salespersons
        ]

        for opp in opportunities:
            if opp.status != OpportunityStatus.NEW.value:
                continue

            # 分值过低的商机不分配（减少垃圾商机）
            if (opp.score or 0) < self.min_score_threshold:
                result["unassigned"] += 1
                result["no_match_reasons"].append(
                    f"SCORE_BELOW_THRESHOLD: opp={opp.opportunity_id}, score={opp.score}"
                )
                continue

            best_sales = None
            best_score = 0.0
            for sp in sales_copy:
                s = self.score_candidate(opp, sp)
                if s > best_score:
                    best_score = s
                    best_sales = sp

            if best_sales is None:
                result["unassigned"] += 1
                result["no_match_reasons"].append(
                    f"NO_MATCH: opp={opp.opportunity_id}, industry={opp.industry}, region={opp.region}"
                )
                continue

            # 分配
            now = _now_iso()
            opp.status = OpportunityStatus.ASSIGNED.value
            opp.assigned_sales_id = best_sales.sales_id
            opp.assigned_at = now
            best_sales.current_load = (best_sales.current_load or 0) + 1

            result["assigned"] += 1
            result["assignments"].append((opp.opportunity_id, best_sales.sales_id, best_score))
            result["operation_logs"].append(
                SalesOperationLog(
                    log_id=_make_id("op", opp.tenant_id, opp.opportunity_id, "ASSIGN"),
                    tenant_id=opp.tenant_id,
                    opportunity_id=opp.opportunity_id,
                    sales_id=best_sales.sales_id,
                    op_type="ASSIGN",
                    before_value=OpportunityStatus.NEW.value,
                    after_value=OpportunityStatus.ASSIGNED.value,
                    detail=f"匹配得分: {best_score:.2f}",
                )
            )

        self._maybe_alert(result, total=len(opportunities))
        return result

    # ---------- 告警 ----------

    def _maybe_alert(self, result: dict, *, total: int) -> None:
        if total <= 0:
            return
        ratio = result["unassigned"] / total
        if ratio >= self.unassigned_alert_ratio:
            reason = "; ".join(result["no_match_reasons"][:5])
            logger.warning(
                f"批量分配异常: unassigned={result['unassigned']}/{total}, ratio={ratio:.2f}, reason={reason}"
            )
            try:
                from infra.alerting import alert_service
                if hasattr(alert_service, "service_exception_sync"):
                    alert_service.service_exception_sync(
                        service_name="sales_task",
                        message=(
                            f"[sales_task:assignment_alert] 批量分配异常 "
                            f"unassigned={result['unassigned']}/{total} ratio={ratio:.2f} {reason}"
                        ),
                    )
            except Exception as exc:
                logger.info(f"告警推送跳过: {exc}")


__all__ = ["AssignmentEngine"]
