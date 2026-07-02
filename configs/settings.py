from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_MODE = Literal["dev", "test", "prod"]


class ProjectSettings(BaseSettings):
    """项目基础配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    PROJECT_NAME: str = "openclaw-business-tools"
    ENV: ENV_MODE = "dev"
    DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    API_PREFIX: str = "/api/v1"


class LogSettings(BaseSettings):
    """日志相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"
    LOG_ROTATION: str = "1 day"
    LOG_RETENTION: str = "30 days"
    LOG_CONSOLE_ENABLED: bool = True
    LOG_FILE_ENABLED: bool = True


class AlertSettings(BaseSettings):
    """告警相关配置（钉钉机器人 / SMTP 邮件）。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    ALERT_ENABLED: bool = False
    ALERT_ENV_PREFIX: str = "[openclaw-business-tools]"
    ALERT_MAX_BYTES: int = 10 * 1024  # 单条告警消息截断上限 10KB

    # 钉钉
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_SECRET: str = ""

    # 邮件
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TO: str = ""  # 多收件人逗号分隔
    SMTP_USE_SSL: bool = True

    # 三类告警场景开关
    ALERT_TASK_FAILURE_ENABLED: bool = True
    ALERT_SERVICE_EXCEPTION_ENABLED: bool = True
    ALERT_CRAWLER_RISK_ENABLED: bool = True


class QueueSettings(BaseSettings):
    """异步任务队列相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    QUEUE_REDIS_HOST: str = "127.0.0.1"
    QUEUE_REDIS_PORT: int = 6379
    QUEUE_REDIS_PASSWORD: str = ""
    QUEUE_REDIS_DB: int = 1
    QUEUE_PREFIX: str = "openclaw:queue"
    QUEUE_NAME: str = "default"
    QUEUE_POOL_SIZE: int = 10
    QUEUE_POOL_TIMEOUT: float = 30.0          # 连接池等待超时（秒）
    QUEUE_TASK_TIMEOUT: float = 300.0         # 单个任务执行超时（秒）
    QUEUE_MAX_RETRIES: int = 3
    QUEUE_RETRY_BACKOFF: float = 2.0          # 指数退避基数（秒）
    QUEUE_WORKER_CONCURRENCY: int = 4         # 同时消费的 worker 协程数
    QUEUE_BPOP_TIMEOUT: float = 5.0           # 单次 bpop 等待时间（秒）
    QUEUE_TASK_TTL: int = 7 * 24 * 3600       # 任务 meta/payload 过期（秒）


class SchedulerSettings(BaseSettings):
    """定时任务调度相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    SCHEDULER_MAX_CONCURRENT: int = 10
    SCHEDULER_MISFIRE_GRACE_TIME: int = 60    # 错过多久仍补执行（秒）
    SCHEDULER_COALESCE: bool = True
    SCHEDULER_JOBSTORES_REDIS: bool = False   # 用 Redis 持久化 job（可选）
    SCHEDULER_STORE_PREFIX: str = "openclaw:scheduler"


class AppSettings(BaseSettings):
    """全局单例配置对象。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project: ProjectSettings = Field(default_factory=ProjectSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    alert: AlertSettings = Field(default_factory=AlertSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


# 全局单例，跨模块统一使用 `from configs.settings import settings`
settings = AppSettings()

__all__ = [
    "settings",
    "AppSettings",
    "ProjectSettings",
    "LogSettings",
    "AlertSettings",
    "QueueSettings",
    "SchedulerSettings",
]
