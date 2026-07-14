"""business/custom_spider/repository — 数据访问层（Repository 模式）。

每个方法独立管理 session 生命周期，保证事务边界清晰。
- 所有查询强制带 tenant_id 过滤（默认 "default"）
- 所有删除使用软删除（is_archived = True）
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from infra.logger_setup import get_logger

logger = get_logger("custom_spider.repository")

# 共享 SQLite 回退 session 工厂（懒初始化，确保所有操作走同一个 DB）
_fallback_session_factory: Any = None
_fallback_engine: Any = None

# 默认 tenant_id
_DEFAULT_TENANT = "default"


# ============================================================
# Session 管理
# ============================================================
def _get_session():
    """从 Database 懒加载 session。

    - 首选: infra.db_base.Database 单例（项目全局配置的数据库）
    - 回退: 内存 SQLite（模块级，用于测试/无配置环境）
    """
    try:
        from infra.db_base import Database

        db = Database()
        db.ensure_connected()
        return db.session()
    except Exception as exc:
        logger.debug(f"Database() 不可达: {exc}，尝试回退到共享 SQLite session")

    # ---- 回退：模块级共享 SQLite session ----
    global _fallback_session_factory, _fallback_engine
    try:
        if _fallback_session_factory is None:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from infra.db_base import Base

            _fallback_engine = create_engine("sqlite://", echo=False, connect_args={"check_same_thread": False})
            # 确保 custom_spider 表创建
            from business.custom_spider.data_models import (
                CustomSpiderPlan,
                CustomSpiderPlanVersion,
                CustomSpiderRun,
                CustomSpiderOperationLog,
            )
            Base.metadata.create_all(bind=_fallback_engine)  # type: ignore[attr-defined]
            _fallback_session_factory = sessionmaker(bind=_fallback_engine, expire_on_commit=False)
        return _fallback_session_factory()
    except Exception as exc2:
        logger.warning(f"fallback session 创建失败: {exc2}")
        return None


@contextmanager
def _session_scope():
    """上下文管理器：自动 commit/rollback/close。"""
    session = _get_session()
    if session is None:
        yield None
        return
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass


# ============================================================
# PlanRepository — 方案 CRUD
# ============================================================
class PlanRepository:
    @staticmethod
    def create(
        plan_name: str,
        plan_code: str,
        target_domain: str,
        spider_type: str,
        rule_config: dict,
        *,
        description: Optional[str] = None,
        schedule_config: Optional[dict] = None,
        increment_config: Optional[dict] = None,
        cookie_raw: Optional[str] = None,
        created_by: str = "system",
        tenant_id: str = _DEFAULT_TENANT,
    ) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return None
            plan = CustomSpiderPlan(
                plan_name=plan_name,
                plan_code=plan_code,
                target_domain=target_domain,
                spider_type=spider_type,
                status="draft",
                created_by=created_by,
                description=description,
                rule_config=rule_config or {},
                schedule_config=schedule_config,
                increment_config=increment_config,
                cookie_encrypted=cookie_raw,  # SensitiveString 自动加密
                current_version=1,
            )
            plan.tenant_id = tenant_id
            session.add(plan)
            session.flush()
            # 重新查询以便获取完整的 ORM 实例
            new_id = plan.id
            return session.get(CustomSpiderPlan, new_id)

    @staticmethod
    def get_by_id(plan_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return None
            return (
                session.query(CustomSpiderPlan)
                .filter(CustomSpiderPlan.id == plan_id, CustomSpiderPlan.tenant_id == tenant_id)
                .first()
            )

    @staticmethod
    def get_by_code(plan_code: str, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return None
            return (
                session.query(CustomSpiderPlan)
                .filter(CustomSpiderPlan.plan_code == plan_code, CustomSpiderPlan.tenant_id == tenant_id)
                .first()
            )

    @staticmethod
    def update(plan_id: int, updates: dict, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return None
            plan = (
                session.query(CustomSpiderPlan)
                .filter(CustomSpiderPlan.id == plan_id, CustomSpiderPlan.tenant_id == tenant_id)
                .with_for_update()
                .first()
            )
            if plan is None:
                return None
            for key, value in updates.items():
                if hasattr(plan, key) and value is not None:
                    setattr(plan, key, value)
            session.flush()
            return session.get(CustomSpiderPlan, plan_id)

    @staticmethod
    def delete(plan_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return False
            plan = (
                session.query(CustomSpiderPlan)
                .filter(CustomSpiderPlan.id == plan_id, CustomSpiderPlan.tenant_id == tenant_id)
                .first()
            )
            if plan is None:
                return False
            plan.is_archived = True
            plan.status = "deleted"
            return True

    @staticmethod
    def list(
        *,
        status: Optional[str] = None,
        spider_type: Optional[str] = None,
        target_domain: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        tenant_id: str = _DEFAULT_TENANT,
    ) -> Tuple[List[Any], int]:
        from business.custom_spider.data_models import CustomSpiderPlan

        with _session_scope() as session:
            if session is None:
                return [], 0
            query = session.query(CustomSpiderPlan).filter(
                CustomSpiderPlan.tenant_id == tenant_id,
                CustomSpiderPlan.is_archived == False,  # noqa: E712
            )
            if status:
                query = query.filter(CustomSpiderPlan.status == status)
            if spider_type:
                query = query.filter(CustomSpiderPlan.spider_type == spider_type)
            if target_domain:
                query = query.filter(CustomSpiderPlan.target_domain.like(f"%{target_domain}%"))
            if keyword:
                like = f"%{keyword}%"
                query = query.filter(
                    (CustomSpiderPlan.plan_name.like(like)) | (CustomSpiderPlan.description.like(like))
                )

            total = query.count()
            items = (
                query.order_by(CustomSpiderPlan.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return list(items), total


# ============================================================
# VersionRepository — 版本管理
# ============================================================
class VersionRepository:
    @staticmethod
    def create(
        plan_id: int,
        version_number: int,
        rule_config: dict,
        *,
        schedule_config: Optional[dict] = None,
        change_note: Optional[str] = None,
        changed_by: str = "system",
        is_current: bool = True,
        rollback_from_version: Optional[int] = None,
        tenant_id: str = _DEFAULT_TENANT,
    ) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlanVersion

        with _session_scope() as session:
            if session is None:
                return None
            # 如果 is_current=True，先把其他版本的 is_current 设为 False
            if is_current:
                session.query(CustomSpiderPlanVersion).filter(
                    CustomSpiderPlanVersion.plan_id == plan_id,
                    CustomSpiderPlanVersion.tenant_id == tenant_id,
                ).update({CustomSpiderPlanVersion.is_current: False})

            ver = CustomSpiderPlanVersion(
                plan_id=plan_id,
                version_number=version_number,
                rule_config=rule_config or {},
                schedule_config=schedule_config,
                change_note=change_note,
                changed_by=changed_by,
                is_current=is_current,
                rollback_from_version=rollback_from_version,
            )
            ver.tenant_id = tenant_id
            session.add(ver)
            session.flush()
            return session.get(CustomSpiderPlanVersion, ver.id)

    @staticmethod
    def list_by_plan(plan_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> List[Any]:
        from business.custom_spider.data_models import CustomSpiderPlanVersion

        with _session_scope() as session:
            if session is None:
                return []
            items = (
                session.query(CustomSpiderPlanVersion)
                .filter(
                    CustomSpiderPlanVersion.plan_id == plan_id,
                    CustomSpiderPlanVersion.tenant_id == tenant_id,
                )
                .order_by(CustomSpiderPlanVersion.version_number.desc())
                .all()
            )
            return list(items)

    @staticmethod
    def get_by_version(plan_id: int, version_number: int, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderPlanVersion

        with _session_scope() as session:
            if session is None:
                return None
            return (
                session.query(CustomSpiderPlanVersion)
                .filter(
                    CustomSpiderPlanVersion.plan_id == plan_id,
                    CustomSpiderPlanVersion.version_number == version_number,
                    CustomSpiderPlanVersion.tenant_id == tenant_id,
                )
                .first()
            )

    @staticmethod
    def get_max_version(plan_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> int:
        from business.custom_spider.data_models import CustomSpiderPlanVersion
        from sqlalchemy import func

        with _session_scope() as session:
            if session is None:
                return 0
            result = (
                session.query(func.max(CustomSpiderPlanVersion.version_number))
                .filter(
                    CustomSpiderPlanVersion.plan_id == plan_id,
                    CustomSpiderPlanVersion.tenant_id == tenant_id,
                )
                .scalar()
            )
            return int(result or 0)


# ============================================================
# RunRepository — 运行记录
# ============================================================
class RunRepository:
    @staticmethod
    def create(
        plan_id: int,
        run_mode: str = "manual",
        *,
        trigger_by: Optional[str] = None,
        status: str = "running",
        tenant_id: str = _DEFAULT_TENANT,
    ) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderRun

        with _session_scope() as session:
            if session is None:
                return None
            run = CustomSpiderRun(
                plan_id=plan_id,
                run_mode=run_mode,
                trigger_by=trigger_by,
                status=status,
                items_total=0,
                items_success=0,
                items_failed=0,
            )
            run.tenant_id = tenant_id
            session.add(run)
            session.flush()
            return session.get(CustomSpiderRun, run.id)

    @staticmethod
    def update(run_id: int, updates: dict, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderRun

        with _session_scope() as session:
            if session is None:
                return None
            run = (
                session.query(CustomSpiderRun)
                .filter(CustomSpiderRun.id == run_id, CustomSpiderRun.tenant_id == tenant_id)
                .with_for_update()
                .first()
            )
            if run is None:
                return None
            for key, value in updates.items():
                if hasattr(run, key) and value is not None:
                    setattr(run, key, value)
            session.flush()
            return session.get(CustomSpiderRun, run_id)

    @staticmethod
    def list_by_plan(
        plan_id: int,
        *,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        tenant_id: str = _DEFAULT_TENANT,
    ) -> Tuple[List[Any], int]:
        from business.custom_spider.data_models import CustomSpiderRun

        with _session_scope() as session:
            if session is None:
                return [], 0
            query = session.query(CustomSpiderRun).filter(
                CustomSpiderRun.plan_id == plan_id, CustomSpiderRun.tenant_id == tenant_id
            )
            if status:
                query = query.filter(CustomSpiderRun.status == status)
            total = query.count()
            items = query.order_by(CustomSpiderRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            return list(items), total

    @staticmethod
    def get_by_id(run_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> Optional[Any]:
        from business.custom_spider.data_models import CustomSpiderRun

        with _session_scope() as session:
            if session is None:
                return None
            return (
                session.query(CustomSpiderRun)
                .filter(CustomSpiderRun.id == run_id, CustomSpiderRun.tenant_id == tenant_id)
                .first()
            )

    @staticmethod
    def delete(run_id: int, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
        from business.custom_spider.data_models import CustomSpiderRun, CustomSpiderRunStep

        with _session_scope() as session:
            if session is None:
                return False
            try:
                # 先删除步骤详情
                session.query(CustomSpiderRunStep).filter(
                    CustomSpiderRunStep.run_id == run_id,
                    CustomSpiderRunStep.tenant_id == tenant_id,
                ).delete(synchronize_session=False)
                # 再删除运行记录
                deleted = session.query(CustomSpiderRun).filter(
                    CustomSpiderRun.id == run_id,
                    CustomSpiderRun.tenant_id == tenant_id,
                ).delete(synchronize_session=False)
                return deleted > 0
            except Exception as exc:
                logger = _get_logger()
                logger.error(f"RunRepository.delete 失败: {exc}")
                return False


# ============================================================
# LogRepository — 操作日志
# ============================================================
class LogRepository:
    @staticmethod
    def create(
        operation: str,
        *,
        plan_id: Optional[int] = None,
        operator: Optional[str] = None,
        detail: Optional[str] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        tenant_id: str = _DEFAULT_TENANT,
    ) -> bool:
        from business.custom_spider.data_models import CustomSpiderOperationLog

        with _session_scope() as session:
            if session is None:
                return False
            log = CustomSpiderOperationLog(
                plan_id=plan_id,
                operation=operation,
                operator=operator,
                detail=detail,
                ip_address=ip_address,
                success=success,
                error_message=error_message,
            )
            log.tenant_id = tenant_id
            session.add(log)
            return True


__all__ = [
    "PlanRepository",
    "VersionRepository",
    "RunRepository",
    "LogRepository",
    "_session_scope",
    "_get_session",
]
