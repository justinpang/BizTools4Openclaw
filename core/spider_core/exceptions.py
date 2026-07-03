from __future__ import annotations

from infra.exceptions import BizException, ErrorCode


class SpiderError(BizException):
    """爬虫通用异常基类。"""

    def __init__(
        self,
        msg: str = "爬虫异常",
        *,
        code: int = ErrorCode.SPIDER_ERROR,
        http_status: int = 400,
        data: dict | None = None,
        trigger_alert: bool = False,
    ) -> None:
        super().__init__(
            msg,
            code=code,
            http_status=http_status,
            data=data,
            trigger_alert=trigger_alert,
        )


class ProxyUnavailableError(SpiderError):
    """代理批量失效或不可用。"""

    def __init__(self, msg: str = "代理不可用", *, data: dict | None = None) -> None:
        super().__init__(msg, code=ErrorCode.SPIDER_ERROR, data=data, trigger_alert=True)


class BlockedByRobotsError(SpiderError):
    """robots.txt 禁止该路径。"""

    def __init__(self, msg: str = "被 robots.txt 禁止访问", *, url: str = "", data: dict | None = None) -> None:
        payload = data or {}
        if url:
            payload["url"] = url
        super().__init__(msg, code=ErrorCode.SPIDER_ERROR, data=payload, trigger_alert=False)


class RateLimitExceededError(SpiderError):
    """达到并发 / 间隔上限。"""

    def __init__(self, msg: str = "触发限流保护", *, data: dict | None = None) -> None:
        super().__init__(msg, code=ErrorCode.SPIDER_ERROR, http_status=429, data=data, trigger_alert=False)


class CrawlerRiskDetectedError(SpiderError):
    """检测到风控 / 验证码 / 封禁。"""

    def __init__(self, msg: str = "检测到风控拦截", *, data: dict | None = None) -> None:
        super().__init__(msg, code=ErrorCode.SPIDER_RISK, http_status=429, data=data, trigger_alert=True)


class CheckpointNotFoundError(SpiderError):
    """断点恢复时 checkpoint 不存在。"""

    def __init__(self, msg: str = "checkpoint 不存在", *, data: dict | None = None) -> None:
        super().__init__(msg, code=ErrorCode.SPIDER_ERROR, data=data, trigger_alert=False)


class UAFileNotFoundError(SpiderError):
    """UA 池文件不存在。"""

    def __init__(self, msg: str = "UA 池文件不存在", *, data: dict | None = None) -> None:
        super().__init__(msg, code=ErrorCode.SPIDER_ERROR, data=data, trigger_alert=True)


__all__ = [
    "SpiderError",
    "ProxyUnavailableError",
    "BlockedByRobotsError",
    "RateLimitExceededError",
    "CrawlerRiskDetectedError",
    "CheckpointNotFoundError",
    "UAFileNotFoundError",
]
