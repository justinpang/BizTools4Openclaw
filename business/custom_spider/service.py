"""business/custom_spider/service — 采集方案业务服务层。

核心能力：
  - 方案 CRUD + 版本管理（规则变更自动生成版本，可回滚）
  - 测试运行（单条 URL 快速验证规则效果）
  - 调度启停（对接 TaskScheduler，注册/注销 cron job）
  - 采集执行（调用 T25 rule_engine → 合规预检 → 入库 spider_raw_data）
  - 导入/导出（跨环境迁移方案配置）
  - 统计查询（运行次数、成功次数、总条目数）
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from infra.logger_setup import get_logger

logger = get_logger("custom_spider.service")


# ============================================================
# 工具函数：保存单个步骤执行结果到 custom_spider_run_steps 表
# ============================================================
def _save_step(
    *, plan_id: int, run_id: int, step_index: int,
    step_type: str, step_name: str,
    status: str, step_description: Optional[str] = None,
    input_json: Optional[dict] = None, output_json: Optional[dict] = None,
    items_in: int = 0, items_out: int = 0,
    error_message: Optional[str] = None,
    save_detail: bool = True, duration_ms: Optional[int] = None,
) -> int:
    """保存单个步骤执行结果。

    返回新记录 ID；失败返回 0，不抛出异常。
    """
    try:
        from business.custom_spider.data_models import CustomSpiderRunStep
        from business.custom_spider.repository import _session_scope
        from datetime import datetime

        if not save_detail:
            input_json = None
            output_json = None

        now = datetime.utcnow()

        with _session_scope() as session:
            if session is None:
                logger.warning("_save_step: session is None, skipping")
                return 0

            existing = None
            if run_id > 0:
                existing = (
                    session.query(CustomSpiderRunStep)
                    .filter(CustomSpiderRunStep.run_id == run_id)
                    .filter(CustomSpiderRunStep.step_index == step_index)
                    .order_by(CustomSpiderRunStep.id.desc())
                    .first()
                )

            if existing and status == "running":
                return int(existing.id or 0)

            if existing and status != "running":
                existing.status = status
                existing.error_message = error_message
                existing.items_in = items_in
                existing.items_out = items_out
                existing.duration_ms = duration_ms
                existing.output_json = output_json
                existing.step_description = step_description or existing.step_description
                if status != "running":
                    existing.finished_at = now
                session.flush()
                return int(existing.id)

            step = CustomSpiderRunStep(
                plan_id=plan_id,
                run_id=run_id if run_id > 0 else None,
                step_index=step_index,
                step_type=step_type,
                step_name=step_name,
                status=status,
                input_json=input_json,
                output_json=output_json,
                items_in=items_in,
                items_out=items_out,
                duration_ms=duration_ms,
                save_detail=save_detail,
                error_message=error_message,
                step_description=step_description,
                created_at=now,
                finished_at=now if status != "running" else None,
            )
            session.add(step)
            session.flush()
            return int(step.id)
    except Exception as exc:
        logger.warning(f"_save_step failed (plan={plan_id}, run={run_id}, step={step_index}): {exc}")
        return 0


# ============================================================
# 工具函数
# ============================================================
def _gen_plan_code(name: str) -> str:
    """生成 plan_code：plan_{md5(name+ts)[:12]}。"""
    ts = str(int(time.time() * 1000))
    raw = f"{name}:{ts}"
    return f"plan_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _dict_deep_eq(a: dict, b: dict) -> bool:
    """比较两个 dict 是否深度相等（用于判断规则是否变更）。"""
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except Exception:
        return False


def _extract_rule_fields(rule_config: dict) -> Dict[str, Any]:
    """从 rule_config 提取关键信息用于版本变更判断。"""
    key_fields = ["list_rule", "detail_rule", "field_mapping", "pagination", "_editor_steps"]
    return {k: rule_config.get(k) for k in key_fields if k in rule_config}


def _call_t25_engine(rule_config: dict, *, max_items: Optional[int] = None) -> Dict[str, Any]:
    """调用采集引擎，返回执行结果。

    优先使用 :class:`StepService`（基于编辑器步骤），
    失败时回退到 :class:`RuleCrawlEngine`（基于旧规则配置）。

    对依赖缺失/异常容错，保证上层业务能继续。
    """
    # ---- 优先路径 1：基于 StepsPackage 的新引擎 ----
    steps_data = (rule_config or {}).get("_steps_package") or (rule_config or {}).get("_editor_steps")
    if steps_data and isinstance(steps_data, (list, dict)):
        try:
            from business.custom_spider.step_service import StepTester
            from business.custom_spider.step_models import StepsPackage

            if isinstance(steps_data, list):
                # 兼容旧存储格式：只存了步骤列表
                pkg = StepsPackage(
                    plan_name=rule_config.get("name") or "",
                    spider_type=rule_config.get("spider_type") or "generic",
                    steps=[],
                )
                for s in steps_data:
                    step = type("StepConfig", (), {
                        "step_type": s.get("step_type", ""),
                        "config": s.get("config") or {},
                        "title": s.get("title") or s.get("step_type", ""),
                        "step_id": s.get("step_id") or s.get("step_type", ""),
                        "step_order": s.get("step_order", 0),
                    })()
                    pkg.steps.append(step)
            else:
                # 标准格式：完整的 StepsPackage dict
                pkg = StepsPackage.from_dict(steps_data)

            pkg.normalize()

            # 如果调用方传入了 max_items 限制，注入到 list_detect 步骤
            if max_items is not None:
                for s in pkg.steps:
                    if getattr(s, "step_type", None) == "list_detect":
                        cfg = getattr(s, "config", None) or {}
                        cfg["max_items_limit"] = max_items

            ss_result = StepTester.run_all(pkg)

            # 从 StepService 输出中提取 items + 步骤诊断信息
            items = ss_result.get("final_items") or []
            if not isinstance(items, list):
                items = [items] if items else []

            # 过滤空记录（所有字段值都为空的 items 不视为有效数据）
            real_items = []
            for item in items:
                if not item:
                    continue
                if isinstance(item, dict):
                    values = [v for v in item.values() if v is not None and str(v).strip()]
                    if values:
                        real_items.append(item)
                else:
                    real_items.append(item)

            # 收集步骤诊断信息（用于调试和用户反馈）
            steps_info = ss_result.get("steps") or []
            failed_steps = [s for s in steps_info if not s.get("success")]
            step_messages = [f"[{s.get('step_type', s.get('step_id', '?'))}] {s.get('message', '')}"
                             for s in steps_info[:8]]

            errors_list = []
            if failed_steps:
                for fs in failed_steps:
                    errors_list.append(
                        f"{fs.get('step_type', fs.get('step_id', 'step'))}: {fs.get('message', '')}"
                    )
            if not real_items:
                errors_list.append("没有可提取的有效数据：可能是页面访问受限（HTTP 403/503），"
                                   "或列表页结构与选择器不匹配，或附件解析内容与字段映射规则不符")

            return {
                "success": bool(real_items),
                "items": real_items,
                "success_items": len(real_items),
                "total_items": len(real_items),
                "field_match_rate": 1.0 if real_items else 0.0,
                "alerts": [],
                "errors": errors_list,
                "total_pages_crawled": 1,
                "engine": "StepService",
                "_steps_package": steps_data,
                "_step_messages": step_messages,
            }
        except Exception as exc:
            logger.warning(f"StepService 路径失败，回退到 RuleCrawlEngine: {exc}")

    # ---- 回退路径 2：旧的 RuleCrawlEngine ----
    try:
        from core.spider_core.rule_engine import RuleCrawlEngine

        rule_set = dict(rule_config or {})
        if max_items is not None:
            rule_set["max_items"] = max_items

        engine = RuleCrawlEngine()
        return engine.run(rule_set)  # type: ignore
    except Exception as exc:
        logger.error(f"T25 引擎调用失败: {exc}")
        return {"success": False, "error": str(exc), "items": [], "success_items": 0, "total_items": 0}


def _parse_engine_result(result: Any) -> Tuple[List[dict], int, int, Optional[float], str, List[dict]]:
    """从 T25 引擎返回结果提取标准字段。

    返回: (items, success, total, match_rate, error, alerts)
    """
    items: List[dict] = []
    success_count = 0
    total_count = 0
    match_rate: Optional[float] = None
    error_msg = ""
    alerts: List[dict] = []

    if result is None:
        return items, success_count, total_count, match_rate, "T25 engine returned None", alerts

    # dict 形式
    if isinstance(result, dict):
        items = result.get("items") or result.get("extracted_items") or []
        items = [dict(it) if hasattr(it, "__dict__") else it for it in items]
        items = [it for it in items if isinstance(it, dict)]
        success_count = int(result.get("success_items") or result.get("success_count") or len(items))
        total_count = int(result.get("total_items") or result.get("item_count") or len(items))
        match_rate = result.get("field_match_rate")
        if match_rate is not None:
            match_rate = float(match_rate)
        error_msg = result.get("error") or result.get("error_msg") or ""
        alerts = result.get("alerts") or []
        _error_list = result.get("errors") or result.get("error_list") or []
        if _error_list:
            _joined = "; ".join(str(e) for e in _error_list)
            error_msg = error_msg or _joined
    else:
        # 可能是一个 EngineResult 对象
        try:
            items = getattr(result, "items", []) or []
            items = [dict(it) if hasattr(it, "__dict__") else it for it in items]
            items = [it for it in items if isinstance(it, dict)]
            success_count = int(getattr(result, "success_items", len(items)) or len(items))
            total_count = int(getattr(result, "total_items", len(items)) or len(items))
            match_rate = getattr(result, "field_match_rate", None)
            if match_rate is not None:
                match_rate = float(match_rate)
            error_msg = str(getattr(result, "error", "") or "")
            alerts = getattr(result, "alerts", []) or []
            _error_list = getattr(result, "errors", []) or []
            if _error_list and not error_msg:
                error_msg = "; ".join(str(e) for e in _error_list)
        except Exception:
            pass

    if not error_msg and not items and not success_count:
        error_msg = "引擎返回空结果，可能规则解析失败"

    return items, success_count, total_count, match_rate, error_msg, alerts


def _compliance_check_items(items: List[dict]) -> List[dict]:
    """T06 合规预检。如果合规检查模块不可用则原样返回。"""
    if not items:
        return []
    try:
        from core.compliance.pii_mask import pii_mask

        masked_items: List[dict] = []
        for item in items:
            try:
                new_item = {}
                for k, v in item.items():
                    if isinstance(v, str):
                        new_item[k] = pii_mask.mask_phone(v) if hasattr(pii_mask, "mask_phone") else v
                    else:
                        new_item[k] = v
                new_item["_compliance_masked"] = True
                masked_items.append(new_item)
            except Exception:
                masked_items.append(item)
        return masked_items
    except Exception as exc:
        logger.warning(f"T06 合规检查不可用，跳过: {exc}")
        return items


def _write_to_spider_raw(
    items: List[dict],
    *,
    plan_code: str,
    source_url: Optional[str] = None,
) -> int:
    """写入 T04 spider_raw_data 表。

    每条 item 作为一个结构化条目，spider_name 标记为 "custom_spider:{plan_code}"。
    """
    if not items:
        return 0
    written = 0
    try:
        from business.custom_spider.repository import _get_session
        from infra.db_models import SpiderRawData

        session = _get_session()
        if session is None:
            logger.warning("DB session 不可达，跳过写入 spider_raw_data")
            return 0

        for idx, item in enumerate(items):
            try:
                # 构造 source_url
                url = item.get("_source_url") or source_url or f"custom_spider:{plan_code}:item_{idx}"
                # 构造 source_id（增量去重）
                source_id_fields = [item.get("title"), item.get("url"), item.get("publish_time")]
                source_id_raw = "|".join([str(f) for f in source_id_fields if f])
                source_id = hashlib.md5(source_id_raw.encode("utf-8")).hexdigest() if source_id_raw else None

                entity = SpiderRawData(
                    spider_name=f"custom_spider:{plan_code}",
                    source_url=url,
                    source_id=source_id,
                    raw_payload=dict(item),
                    raw_text=str(item.get("content") or item.get("title") or ""),
                    fetch_status=1,
                    fetch_error=None,
                    source_country=None,
                )
                session.add(entity)
                written += 1
                # 每 50 条 flush 一次
                if written % 50 == 0:
                    session.commit()
            except Exception as exc:
                logger.warning(f"写入 spider_raw_data 失败: {exc}")

        session.commit()
        session.close()
    except Exception as exc:
        logger.error(f"_write_to_spider_raw 整体失败: {exc}")
    return written


# ============================================================
# PlanService — 采集方案业务服务
# ============================================================
class PlanService:
    """采集方案业务服务。

    纯 Python API，不依赖 Web 框架，可由任何上层调用方使用。
    """

    # ---------- 创建方案 ----------
    def create_plan(
        self,
        plan_name: str,
        target_domain: str,
        spider_type: str,
        rule_config: dict,
        *,
        plan_code: Optional[str] = None,
        description: Optional[str] = None,
        schedule_config: Optional[dict] = None,
        increment_config: Optional[dict] = None,
        cookie_raw: Optional[str] = None,
        operator: str = "system",
    ) -> Dict[str, Any]:
        """创建新方案，自动生成 v1 版本。"""
        from business.custom_spider.repository import PlanRepository, VersionRepository, LogRepository

        if not plan_name or not target_domain or not rule_config:
            return {"success": False, "error": "plan_name/target_domain/rule_config 必填"}

        code = plan_code or _gen_plan_code(plan_name)

        # 创建方案
        plan = PlanRepository.create(
            plan_name=plan_name,
            plan_code=code,
            target_domain=target_domain,
            spider_type=spider_type or "generic",
            rule_config=rule_config,
            description=description,
            schedule_config=schedule_config,
            increment_config=increment_config,
            cookie_raw=cookie_raw,
            created_by=operator,
        )
        if plan is None:
            LogRepository.create("create", operator=operator, success=False, error_message="DB 创建失败")
            return {"success": False, "error": "DB 创建失败"}

        plan_id = int(plan.id)

        # 创建 v1 版本
        VersionRepository.create(
            plan_id=plan_id,
            version_number=1,
            rule_config=rule_config,
            schedule_config=schedule_config,
            changed_by=operator,
            is_current=True,
        )

        LogRepository.create(
            "create", plan_id=plan_id, operator=operator, detail=f"创建方案: {plan_name} ({code})"
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "plan_code": code,
            "version_number": 1,
            "plan_name": plan_name,
        }

    # ---------- 更新方案 ----------
    def update_plan(
        self,
        plan_id: int,
        *,
        plan_name: Optional[str] = None,
        status: Optional[str] = None,
        rule_config: Optional[dict] = None,
        schedule_config: Optional[dict] = None,
        increment_config: Optional[dict] = None,
        cookie_raw: Optional[str] = None,
        change_note: Optional[str] = None,
        operator: str = "system",
    ) -> Dict[str, Any]:
        """更新方案。如果 rule_config 变更则自动生成新版本。"""
        from business.custom_spider.repository import PlanRepository, VersionRepository, LogRepository

        # 获取当前方案
        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        # 判断规则是否变更
        current_rule = plan.rule_config or {}
        rule_changed = False
        if rule_config is not None and not _dict_deep_eq(_extract_rule_fields(current_rule), _extract_rule_fields(rule_config)):
            rule_changed = True

        # 组装更新字段
        updates: Dict[str, Any] = {}
        if plan_name:
            updates["plan_name"] = plan_name
        if status:
            updates["status"] = status
        if schedule_config is not None:
            updates["schedule_config"] = schedule_config
        if increment_config is not None:
            updates["increment_config"] = increment_config
        if cookie_raw is not None:
            updates["cookie_encrypted"] = cookie_raw

        new_version = None
        if rule_changed and rule_config is not None:
            # 规则变更：新版本号 = max_version + 1
            max_v = VersionRepository.get_max_version(plan_id)
            new_version = max_v + 1
            updates["rule_config"] = rule_config
            updates["current_version"] = new_version

            VersionRepository.create(
                plan_id=plan_id,
                version_number=new_version,
                rule_config=rule_config,
                schedule_config=schedule_config,
                change_note=change_note or "规则变更",
                changed_by=operator,
                is_current=True,
            )
            logger.info(f"方案 {plan_id} 规则变更，生成 v{new_version}")

        # 如果 schedule 变更但规则没变更，仍需更新
        if updates:
            PlanRepository.update(plan_id, updates)
            LogRepository.create(
                "update",
                plan_id=plan_id,
                operator=operator,
                detail=change_note or (f"规则变更 v{new_version}" if new_version else "配置更新"),
            )

        return {
            "success": True,
            "plan_id": plan_id,
            "new_version": new_version,
            "rule_changed": rule_changed,
        }

    # ---------- 克隆方案 ----------
    def clone_plan(
        self, plan_id: int, *, new_plan_name: str, new_plan_code: Optional[str] = None, operator: str = "system"
    ) -> Dict[str, Any]:
        """克隆一个已存在的方案，配置完全复制。"""
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        return self.create_plan(
            plan_name=new_plan_name,
            target_domain=plan.target_domain,
            spider_type=plan.spider_type,
            rule_config=dict(plan.rule_config) if plan.rule_config else {},
            plan_code=new_plan_code,
            description=f"(克隆自方案 {plan.plan_name}) {plan.description or ''}",
            schedule_config=dict(plan.schedule_config) if plan.schedule_config else None,
            increment_config=dict(plan.increment_config) if plan.increment_config else None,
            cookie_raw=None,  # cookie 不克隆
            operator=operator,
        )

    # ---------- 删除方案 ----------
    def delete_plan(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """软删除方案（is_archived = True）。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        ok = PlanRepository.delete(plan_id)
        LogRepository.create(
            "delete", plan_id=plan_id if ok else None, operator=operator, success=ok,
            error_message=None if ok else "DB 删除失败"
        )
        # 停用调度
        if ok:
            try:
                self.disable_schedule(plan_id, operator=operator)
            except Exception:
                pass
        return {"success": ok}

    # ---------- 查询单条 ----------
    def get_plan(self, plan_id: int) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return None
        return plan.to_public_dict() if hasattr(plan, "to_public_dict") else {"id": plan.id, "plan_name": plan.plan_name}

    def get_plan_by_code(self, plan_code: str) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_code(plan_code)
        if plan is None:
            return None
        return plan.to_public_dict() if hasattr(plan, "to_public_dict") else {"id": plan.id, "plan_code": plan_code}

    # ---------- 列表查询 ----------
    def list_plans(
        self,
        *,
        status: Optional[str] = None,
        spider_type: Optional[str] = None,
        target_domain: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        from business.custom_spider.repository import PlanRepository

        items, total = PlanRepository.list(
            status=status,
            spider_type=spider_type,
            target_domain=target_domain,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        out = []
        for it in items:
            if hasattr(it, "to_public_dict"):
                out.append(it.to_public_dict())
            else:
                out.append({"id": getattr(it, "id", None), "plan_name": getattr(it, "plan_name", "")})
        return {"items": out, "total": total, "page": page, "page_size": page_size}

    # ---------- 版本管理 ----------
    def list_versions(self, plan_id: int) -> List[Dict[str, Any]]:
        from business.custom_spider.repository import VersionRepository

        versions = VersionRepository.list_by_plan(plan_id)
        out = []
        for v in versions:
            if hasattr(v, "to_public_dict"):
                out.append(v.to_public_dict())
            else:
                out.append({"id": getattr(v, "id", None), "version_number": getattr(v, "version_number", 0)})
        return out

    def rollback_to_version(self, plan_id: int, version_number: int, *, operator: str = "system") -> Dict[str, Any]:
        """回滚到指定版本：把该版本的规则作为一个新版本。"""
        from business.custom_spider.repository import VersionRepository

        ver = VersionRepository.get_by_version(plan_id, version_number)
        if ver is None:
            return {"success": False, "error": f"版本 v{version_number} 不存在"}

        return self.update_plan(
            plan_id,
            rule_config=dict(ver.rule_config) if ver.rule_config else {},
            schedule_config=dict(ver.schedule_config) if ver.schedule_config else None,
            change_note=f"回滚到 v{version_number}",
            operator=operator,
        )

    # ---------- 测试运行 ----------
    def test_plan(
        self, plan_id: int, *, test_url: Optional[str] = None, max_items: int = 5, operator: str = "system"
    ) -> Dict[str, Any]:
        """单条 URL 测试运行，不入库。"""
        from business.custom_spider.repository import PlanRepository, RunRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        # 构造测试规则（如果有 test_url，则覆盖 list_rule 的 URL）
        rule_config = dict(plan.rule_config or {})
        if test_url and "list_rule" in rule_config:
            lr = dict(rule_config["list_rule"])
            lr["url_template"] = test_url
            rule_config["list_rule"] = lr

        # 1. 写入一条 running 记录
        run = RunRepository.create(plan_id=plan_id, run_mode="test", trigger_by=operator, status="running")
        run_id = int(run.id) if run else 0

        start_ts = time.monotonic()

        # 2. 调用 T25 引擎
        engine_result = _call_t25_engine(rule_config, max_items=max_items)

        # 3. 解析结果
        items, success_count, total_count, match_rate, error_msg, alerts = _parse_engine_result(engine_result)

        # 4. 合规预检（测试运行也需要合规脱敏展示）
        items_masked = _compliance_check_items(items)

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        run_status = "completed" if not error_msg else "failed"

        # 5. 更新运行记录
        if run_id:
            RunRepository.update(
                run_id,
                {
                    "status": run_status,
                    "items_total": total_count,
                    "items_success": success_count,
                    "items_failed": max(0, total_count - success_count),
                    "field_match_rate": match_rate,
                    "error_summary": error_msg if error_msg else None,
                    "alerts_json": {"alerts": alerts} if alerts else None,
                    "duration_ms": duration_ms,
                },
            )

        LogRepository.create(
            "test", plan_id=plan_id, operator=operator, detail=f"测试运行，采集 {len(items_masked)} 条"
        )

        return {
            "success": not error_msg,
            "plan_id": plan_id,
            "run_id": run_id,
            "items": items_masked[:max_items],
            "items_total": total_count,
            "items_success": success_count,
            "field_match_rate": match_rate,
            "duration_ms": duration_ms,
            "error": error_msg or None,
            "alerts": alerts,
        }

    # ---------- 立即执行采集 ----------
    def run_plan_now(
        self, plan_id: int, *, operator: str = "system", max_items: Optional[int] = None
    ) -> Dict[str, Any]:
        """立即执行一次采集（同步），结果写入 spider_raw_data。

        执行流程：
          步骤 1: 调用 T25 引擎 → 抓取/解析
          步骤 2: 合规预检（敏感信息替换/黑名单过滤）
          步骤 3: 写入 spider_raw_data（采集阶段）
          步骤 4: 自动触发清洗 pipeline → 写入 cleaned_opportunity（清洗阶段）

        每个步骤都保存到 CustomSpiderRunStep，供前端"执行详情"查看。
        """
        from business.custom_spider.repository import PlanRepository, RunRepository, LogRepository
        from datetime import datetime

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        # 方案配置：是否保存中间结果（默认开启）
        plan_config = dict(plan.increment_config or {}) if plan.increment_config else {}
        save_middle_result = bool(plan_config.get("save_middle_result", True))

        rule_config = dict(plan.rule_config or {})
        plan_code = plan.plan_code
        source_url = None
        if rule_config.get("list_rule"):
            source_url = rule_config["list_rule"].get("url_template")

        run = RunRepository.create(plan_id=plan_id, run_mode="manual", trigger_by=operator, status="running")
        run_id = int(run.id) if run else 0
        start_ts = time.monotonic()

        # ==================== 步骤 1: T25 引擎采集 ====================
        step1_start = time.monotonic()
        try:
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=1,
                step_type="crawl", step_name="引擎采集",
                step_description="调用 T25 规则引擎，执行列表页抓取与详情解析",
                status="running", input_json={
                    "plan_code": plan_code,
                    "rule_config_keys": list(rule_config.keys())[:10],
                    "max_items": max_items,
                    "source_url": source_url,
                }, save_detail=save_middle_result,
            )

            engine_result = _call_t25_engine(rule_config, max_items=max_items)
            items, success_count, total_count, match_rate, error_msg, alerts = _parse_engine_result(engine_result)

            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=1,
                step_type="crawl", step_name="引擎采集",
                status="success" if not error_msg else "failed",
                items_in=total_count, items_out=success_count,
                output_json={
                    "total_count": total_count,
                    "success_count": success_count,
                    "match_rate": float(match_rate) if match_rate else None,
                    "sample_items": items[:3] if save_middle_result and items else None,
                }, error_message=error_msg, save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step1_start) * 1000),
            )
        except Exception as exc:
            error_msg = f"步骤1异常: {exc}"
            items, total_count, success_count, match_rate, alerts = [], 0, 0, None, []
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=1,
                step_type="crawl", step_name="引擎采集",
                status="failed", error_message=error_msg, save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step1_start) * 1000),
            )

        # ==================== 步骤 2: 合规预检 ====================
        step2_start = time.monotonic()
        try:
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=2,
                step_type="compliance", step_name="合规预检",
                step_description="对采集到的条目做敏感信息过滤与合规检查",
                status="running", input_json={"raw_items_count": len(items)},
                save_detail=save_middle_result,
            )

            items_masked = _compliance_check_items(items)

            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=2,
                step_type="compliance", step_name="合规预检",
                status="success", items_in=len(items), items_out=len(items_masked),
                output_json={"final_items_count": len(items_masked)},
                save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step2_start) * 1000),
            )
        except Exception as exc:
            items_masked = items
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=2,
                step_type="compliance", step_name="合规预检",
                status="failed", error_message=str(exc), save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step2_start) * 1000),
            )

        # ==================== 步骤 3: 写入 spider_raw_data（采集阶段） ====================
        step3_start = time.monotonic()
        try:
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=3,
                step_type="storage", step_name="写入采集库",
                step_description=f"将 {len(items_masked)} 条条目写入 spider_raw_data",
                status="running", input_json={"items_masked_count": len(items_masked)},
                save_detail=save_middle_result,
            )

            written = _write_to_spider_raw(items_masked, plan_code=plan_code, source_url=source_url)

            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=3,
                step_type="storage", step_name="写入采集库",
                status="success", items_in=len(items_masked), items_out=written,
                output_json={"spider_raw_data_rows": written, "spider_name": f"custom_spider:{plan_code}"},
                save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step3_start) * 1000),
            )
        except Exception as exc:
            written = 0
            _save_step(
                plan_id=plan_id, run_id=run_id, step_index=3,
                step_type="storage", step_name="写入采集库",
                status="failed", error_message=str(exc), save_detail=save_middle_result,
                duration_ms=int((time.monotonic() - step3_start) * 1000),
            )

        # ==================== 步骤 4: 清洗阶段 → 写入 cleaned_opportunity 供漏斗看板 ====================
        cleaned_count = 0
        step4_start = time.monotonic()
        if written > 0 and not error_msg:
            try:
                _save_step(
                    plan_id=plan_id, run_id=run_id, step_index=4,
                    step_type="clean", step_name="清洗结构化",
                    step_description="从 spider_raw_data 读取新数据，进入 data_clean pipeline，写入 cleaned_opportunity",
                    status="running", input_json={"spider_raw_data_rows": written},
                    save_detail=save_middle_result,
                )

                from business.data_clean import run_cleaning
                from business.data_clean.models import CleanTaskParams

                clean_params = CleanTaskParams(
                    task_id=f"custom_spider_{plan_id}_{int(time.time())}",
                    tenant_id="default",
                    batch_size=written,
                    spider_names=[f"custom_spider:{plan_code}"],
                    run_engine=True,
                    run_storage=True,
                    run_enterprise_enrich=False,
                )
                clean_result = run_cleaning(clean_params)
                cleaned_count = int(getattr(clean_result, "processed", 0) or 0)

                _save_step(
                    plan_id=plan_id, run_id=run_id, step_index=4,
                    step_type="clean", step_name="清洗结构化",
                    status="success", items_in=written, items_out=cleaned_count,
                    output_json={
                        "cleaned_opportunity_rows": cleaned_count,
                        "task_id": clean_params.task_id,
                        "funnel_visible": True,  # 标记数据对漏斗看板可见
                    }, save_detail=save_middle_result,
                    duration_ms=int((time.monotonic() - step4_start) * 1000),
                )
                logger.info(f"清洗阶段完成: {plan.plan_name} → {cleaned_count} 条处理")
            except Exception as exc:
                _save_step(
                    plan_id=plan_id, run_id=run_id, step_index=4,
                    step_type="clean", step_name="清洗结构化",
                    status="failed", error_message=str(exc), save_detail=save_middle_result,
                    duration_ms=int((time.monotonic() - step4_start) * 1000),
                )
                logger.warning(f"清洗阶段失败: {exc}")
        else:
            # 没有可清洗的数据，跳过步骤4
            if not error_msg:
                _save_step(
                    plan_id=plan_id, run_id=run_id, step_index=4,
                    step_type="clean", step_name="清洗结构化",
                    status="skipped", step_description="无新数据，跳过清洗",
                    save_detail=save_middle_result, duration_ms=0,
                )

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        run_status = "completed" if not error_msg else "failed"

        # 更新运行记录
        if run_id:
            RunRepository.update(
                run_id,
                {
                    "status": run_status,
                    "items_total": total_count,
                    "items_success": written,
                    "items_failed": max(0, total_count - written),
                    "field_match_rate": match_rate,
                    "error_summary": error_msg if error_msg else None,
                    "alerts_json": {"alerts": alerts} if alerts else None,
                    "duration_ms": duration_ms,
                },
            )

        # 更新 plan 的累计统计
        try:
            PlanRepository.update(
                plan_id,
                {
                    "run_count_total": (plan.run_count_total or 0) + 1,
                    "run_count_success": (plan.run_count_success or 0) + (1 if run_status == "completed" else 0),
                    "items_total": (plan.items_total or 0) + written,
                    "last_run_status": run_status,
                    "last_run_error": error_msg if error_msg else None,
                },
            )
        except Exception as exc:
            logger.warning(f"更新 plan 统计失败: {exc}")

        LogRepository.create(
            "run", plan_id=plan_id, operator=operator,
            detail=f"立即执行，采集 {written}/{total_count} 条，耗时 {duration_ms}ms",
            success=run_status == "completed",
            error_message=error_msg if error_msg else None,
        )

        return {
            "success": run_status == "completed",
            "plan_id": plan_id,
            "run_id": run_id,
            "items_total": total_count,
            "items_written": written,
            "items_cleaned": cleaned_count,
            "field_match_rate": match_rate,
            "duration_ms": duration_ms,
            "error": error_msg or None,
            "alerts": alerts,
            "funnel_visible": cleaned_count > 0,  # 标记数据对漏斗看板可见
            "save_middle_result": save_middle_result,
        }

    # ---------- 调度启停 ----------
    def enable_schedule(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """启用调度：注册到 TaskScheduler。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        schedule = dict(plan.schedule_config or {})
        cron = schedule.get("cron")
        if not cron:
            return {"success": False, "error": "schedule_config.cron 未配置"}

        try:
            from infra.task_scheduler import TaskScheduler

            scheduler = TaskScheduler()
            job_id = f"custom_spider:{plan.plan_code}"

            # 构造计划函数：通过 plan_code 反查配置
            scheduler.add_cron(
                job_id,
                _make_scheduled_runner(plan.plan_code),
                cron=cron,
            )
            PlanRepository.update(plan_id, {"status": "active"})
            LogRepository.create(
                "start", plan_id=plan_id, operator=operator, detail=f"启用调度，cron={cron}"
            )
            return {"success": True, "job_id": job_id, "cron": cron}
        except Exception as exc:
            msg = f"TaskScheduler 注册失败: {exc}"
            logger.error(msg)
            LogRepository.create("start", plan_id=plan_id, operator=operator, success=False, error_message=msg)
            return {"success": False, "error": msg}

    def disable_schedule(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """停用调度：从 TaskScheduler 移除。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        try:
            from infra.task_scheduler import TaskScheduler

            scheduler = TaskScheduler()
            job_id = f"custom_spider:{plan.plan_code}"

            # 尝试移除 job
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass

            PlanRepository.update(plan_id, {"status": "paused"})
            LogRepository.create(
                "stop", plan_id=plan_id, operator=operator, detail="停用调度"
            )
            return {"success": True, "job_id": job_id}
        except Exception as exc:
            msg = f"TaskScheduler 停用失败: {exc}"
            logger.error(msg)
            return {"success": False, "error": msg}

    # ---------- 导入/导出 ----------
    def export_plan(self, plan_id: int) -> Dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}
        return {
            "success": True,
            "export": {
                "plan_name": plan.get("plan_name"),
                "target_domain": plan.get("target_domain"),
                "spider_type": plan.get("spider_type"),
                "description": plan.get("description"),
                "rule_config": plan.get("rule_config"),
                "schedule_config": plan.get("schedule_config"),
                "increment_config": plan.get("increment_config"),
                "version": plan.get("current_version"),
                "_exported_at": datetime.utcnow().isoformat() + "Z",
            },
        }

    def import_plan(
        self, config: dict, *, plan_name: Optional[str] = None, plan_code: Optional[str] = None, operator: str = "system"
    ) -> Dict[str, Any]:
        if not config or not config.get("rule_config"):
            return {"success": False, "error": "导入配置缺少 rule_config"}

        name = plan_name or config.get("plan_name") or f"imported_{int(time.time())}"
        return self.create_plan(
            plan_name=name,
            target_domain=config.get("target_domain") or "unknown",
            spider_type=config.get("spider_type") or "generic",
            rule_config=config["rule_config"],
            plan_code=plan_code,
            description=config.get("description"),
            schedule_config=config.get("schedule_config"),
            increment_config=config.get("increment_config"),
            operator=operator,
        )

    # ---------- 统计 ----------
    def get_plan_stats(self, plan_id: int) -> Dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        runs, _ = self.list_runs(plan_id, page=1, page_size=1000)
        return {
            "success": True,
            "plan": plan,
            "run_count_total": plan.get("run_count_total") or 0,
            "run_count_success": plan.get("run_count_success") or 0,
            "items_total": plan.get("items_total") or 0,
            "last_run_status": plan.get("last_run_status"),
            "last_run_at": plan.get("last_run_at"),
            "recent_runs": runs[:10],
        }

    def list_runs(
        self, plan_id: int, *, status: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        from business.custom_spider.repository import RunRepository

        runs, total = RunRepository.list_by_plan(plan_id, status=status, page=page, page_size=page_size)
        out = []
        for r in runs:
            if hasattr(r, "to_public_dict"):
                out.append(r.to_public_dict())
            else:
                out.append({"id": getattr(r, "id", None), "status": getattr(r, "status", "")})
        return out, total

    def get_run_detail(self, run_id: int) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import RunRepository

        run = RunRepository.get_by_id(run_id)
        if run is None:
            return None
        return run.to_public_dict() if hasattr(run, "to_public_dict") else {"id": run_id}

    def delete_run(self, run_id: int) -> bool:
        from business.custom_spider.repository import RunRepository

        return RunRepository.delete(run_id)

    # ---------- 步骤级执行详情：采集/清洗各步骤的输入/输出/耗时 ----------
    def get_run_steps(
        self, plan_id: int, *, run_id: Optional[int] = None,
        page: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        """查询某个方案/运行的步骤级执行详情。

        - 若提供 run_id：只查询这次运行的步骤；
        - 否则：返回最近 page_size 条步骤（按创建时间倒序）。
        """
        try:
            from business.custom_spider.repository import _session_scope
            from business.custom_spider.data_models import CustomSpiderRunStep

            with _session_scope() as session:
                q = session.query(CustomSpiderRunStep).filter(
                    CustomSpiderRunStep.plan_id == plan_id
                )
                if run_id is not None:
                    q = q.filter(CustomSpiderRunStep.run_id == run_id)
                q = q.order_by(
                    CustomSpiderRunStep.run_id.asc(),
                    CustomSpiderRunStep.step_index.asc(),
                )
                total = q.count()
                rows = q.limit(page_size).offset(max(0, (page - 1) * page_size)).all()

                steps = []
                for r in rows:
                    if hasattr(r, "to_public_dict"):
                        steps.append(r.to_public_dict())
                    else:
                        steps.append({
                            "id": r.id,
                            "step_index": r.step_index,
                            "step_name": r.step_name,
                            "status": r.status,
                        })
                return {
                    "success": True,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "steps": steps,
                }
        except Exception as exc:
            logger.warning(f"get_run_steps failed (plan={plan_id}): {exc}")
            return {"success": False, "error": str(exc), "total": 0, "steps": []}

    def list_recent_runs_with_steps(
        self, plan_id: int, *, page: int = 1, page_size: int = 10,
    ) -> Dict[str, Any]:
        """返回最近 N 次运行，以及每次运行对应的步骤详情（前端"执行详情"区块使用）。"""
        try:
            runs, total = self.list_runs(plan_id, page=page, page_size=page_size)
            # 对每个 run，附加步骤详情
            runs_with_steps = []
            for r in runs:
                run_id = r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
                steps_result = self.get_run_steps(plan_id, run_id=run_id, page=1, page_size=20)
                r["steps"] = steps_result.get("steps", []) if isinstance(r, dict) else r
                runs_with_steps.append(r)
            return {
                "success": True,
                "total": total,
                "page": page,
                "page_size": page_size,
                "runs": runs_with_steps,
            }
        except Exception as exc:
            logger.warning(f"list_recent_runs_with_steps failed (plan={plan_id}): {exc}")
            return {"success": False, "error": str(exc), "total": 0, "runs": []}


# ============================================================
# 调度执行入口 — TaskScheduler 回调函数
# ============================================================
def _make_scheduled_runner(plan_code: str):
    """构造一个可被 TaskScheduler 调用的函数。"""

    def _runner():
        try:
            service = PlanService()
            plan = service.get_plan_by_code(plan_code)
            if plan is None:
                logger.warning(f"[schedule] plan_code={plan_code} not found")
                return
            service.run_plan_now(int(plan["id"]), operator="scheduler")
        except Exception as exc:
            logger.error(f"[schedule] plan_code={plan_code} 执行异常: {exc}")

    return _runner


def execute_scheduled_plan(plan_code: str) -> Dict[str, Any]:
    """被 TaskScheduler 调用的入口函数。"""
    runner = _make_scheduled_runner(plan_code)
    try:
        runner()
        return {"success": True, "plan_code": plan_code}
    except Exception as exc:
        return {"success": False, "error": str(exc), "plan_code": plan_code}


__all__ = [
    "PlanService",
    "execute_scheduled_plan",
    "_save_step",
]
