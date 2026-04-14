from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.schemas.api import RetryConfig


@dataclass(frozen=True)
class RetrySettings:
    question_max_retries: int
    layout_max_retries: int
    html_max_retries: int
    image_max_retries: int
    rule_eval_parallelism: int



def merge_retry_config(retry_config: RetryConfig | None, settings: Settings | None = None) -> RetrySettings:
    s = settings or get_settings()

    return RetrySettings(
        question_max_retries=max(1, retry_config.question_max_retries) if retry_config and retry_config.question_max_retries else s.question_max_retries,
        layout_max_retries=max(1, retry_config.layout_max_retries) if retry_config and retry_config.layout_max_retries else s.layout_max_retries,
        html_max_retries=max(1, retry_config.html_max_retries) if retry_config and retry_config.html_max_retries else s.html_max_retries,
        image_max_retries=max(1, retry_config.image_max_retries) if retry_config and retry_config.image_max_retries else s.image_max_retries,
        rule_eval_parallelism=max(1, retry_config.rule_eval_parallelism) if retry_config and retry_config.rule_eval_parallelism else s.rule_eval_parallelism,
    )
