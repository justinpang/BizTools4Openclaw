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


# 全局单例，跨模块统一使用 `from configs.settings import settings`
settings = AppSettings()

__all__ = ["settings", "AppSettings", "ProjectSettings", "LogSettings", "AlertSettings"]
