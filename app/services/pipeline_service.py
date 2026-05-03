from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents.agent_service import AgentService
from app.agents.config import get_agent_settings
from app.core.config import Settings, get_settings
from app.db import repository
from app.schemas.api import (
    FullPipelineRunResponse,
    LayoutToHtmlRunResponse,
    QuestionToLayoutRunResponse,
    RetryConfig,
    YamlToQuestionRunResponse,
)
from app.schemas.domain import LayoutPlan, QuestionSpec
from app.services.log_stream_service import publish_done, publish_event
from app.services.pipeline_log_service import write_pipeline_log
from app.services.retry_service import RetrySettings, merge_retry_config
from app.services.object_storage_service import ObjectStorageService


class PipelineService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.agents = AgentService(self.settings)
        self.storage = ObjectStorageService(self.settings)
        self._log_path: Path | None = None
        self._stream_key: str | None = None

    def _log(
        self,
        *,
        mode: str,
        component: str,
        message: str,
        pipeline_id: str | None,
        sub_pipeline_id: str | None,
        level: str = "info",
        details: Any | None = None,
    ) -> None:
        write_pipeline_log(
            self.db,
            mode=mode,
            component=component,
            message=message,
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level=level,
            details=details,
            log_path=self._log_path,
            stream_key=self._stream_key,
        )

    def _artifact_response_url(self, artifact_id: str) -> str:
        return f"/v1/assets/{artifact_id}"

    def _load_yaml_instance_payload(self, yaml_instance_id: str) -> dict[str, Any]:
        row = repository.get_yaml_instance(self.db, yaml_instance_id)
        if row is None:
            raise HTTPException(status_code=404, detail="YAML instance bulunamadı")
        data = repository.parse_json(row.values_json)
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="YAML instance values dict olmalı")
        if not row.rendered_yaml_text:
            repository.update_yaml_instance(
                self.db,
                yaml_instance_id,
                rendered_yaml_text=str(data),
            )
        return data

    def _create_json_artifact(
        self,
        *,
        kind: str,
        payload: Any,
        pipeline_id: str | None = None,
        sub_pipeline_id: str | None = None,
        text: str | None = None,
    ) -> str:
        artifact = repository.create_artifact(
            self.db,
            kind=kind,
            content_json=payload,
            content_text=text,
            source_pipeline_id=pipeline_id,
            source_sub_pipeline_id=sub_pipeline_id,
        )
        return artifact.id

    def _upload_file_artifact(
        self,
        *,
        kind: str,
        path: Path,
        bucket: str,
        key: str,
        mime_type: str,
        pipeline_id: str | None = None,
        sub_pipeline_id: str | None = None,
    ) -> str:
        existing = repository.get_artifact_by_object(self.db, bucket=bucket, key=key)
        if existing is not None:
            return existing.id
        self.storage.upload_file(bucket=bucket, key=key, path=path, content_type=mime_type)
        artifact = repository.create_artifact(
            self.db,
            kind=kind,
            object_bucket=bucket,
            object_key=key,
            mime_type=mime_type,
            source_pipeline_id=pipeline_id,
            source_sub_pipeline_id=sub_pipeline_id,
        )
        return artifact.id

    def _artifactize_html_asset_urls(
        self,
        html_content: str,
        asset_map: dict[str, str],
        asset_artifact_ids: dict[str, str],
    ) -> str:
        updated = html_content
        for slug, artifact_id in asset_artifact_ids.items():
            url = self._artifact_response_url(artifact_id)
            mapped = asset_map.get(slug)
            candidates = [mapped, Path(str(mapped)).name if mapped else None]
            for candidate in [item for item in candidates if item]:
                updated = updated.replace(f"catalog/{candidate}", url)
                updated = updated.replace(f"generated_assets/{candidate}", url)
                updated = updated.replace(f"runs/{candidate}", url)
                updated = updated.replace(str(candidate), url)
        return updated

    def _normalize_html_payload_for_server(self, html_payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(html_payload)
        normalized["html_content"] = self.agents.normalize_html_asset_urls_for_server(
            str(html_payload.get("html_content") or "")
        )
        return normalized

    async def _run_yaml_to_question_loop(
        self,
        *,
        mode: str,
        yaml_content: dict[str, Any],
        retry: RetrySettings,
        pipeline_id: str | None,
        sub_pipeline_id: str | None,
    ) -> tuple[QuestionSpec, dict[str, Any], int]:
        self._log(
            mode=mode,
            component="pipeline",
            message="YAML -> Question döngüsü başladı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={
                "question_max_retries": retry.question_max_retries,
                "rule_eval_parallelism": retry.rule_eval_parallelism,
            },
        )
        self._log(
            mode=mode,
            component="validation.extract_rules",
            message="Rule extraction başlatıldı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
        )
        rules = await asyncio.to_thread(self.agents.extract_rules, yaml_content)
        original_rule_count = len(rules.items)
        if original_rule_count > self.settings.rule_eval_max_rules:
            rules.items = rules.items[: self.settings.rule_eval_max_rules]
            self._log(
                mode=mode,
                component="validation.extract_rules",
                message=(
                    f"Rule set kırpıldı: {original_rule_count} -> {len(rules.items)} "
                    f"(limit={self.settings.rule_eval_max_rules})"
                ),
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                level="warning",
                details={
                    "original_rule_count": original_rule_count,
                    "used_rule_count": len(rules.items),
                    "limit": self.settings.rule_eval_max_rules,
                },
            )
        repository.record_agent_run(
            self.db,
            agent_name="validation_extract_rules",
            mode=mode,
            attempt_no=1,
            status="success",
            input_payload=yaml_content,
            output_payload=rules.model_dump(),
            feedback_text=None,
            error=None,
            model_name=get_agent_settings().extract_rules.primary_model if not self.settings.use_stub_agents else "stub",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
        )
        self._log(
            mode=mode,
            component="validation.extract_rules",
            message=f"Rule extraction tamamlandı. {len(rules.items)} kural çıkarıldı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={"rule_count": len(rules.items)},
        )

        feedback: str | None = None
        feedback_history: list[str] = []
        last_eval = None
        last_question: QuestionSpec | None = None
        for attempt in range(1, retry.question_max_retries + 1):
            self._log(
                mode=mode,
                component="main.generate_question",
                message=f"Question generation attempt {attempt}/{retry.question_max_retries} başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            question = await asyncio.to_thread(self.agents.generate_question, yaml_content, feedback)
            last_question = question
            repository.record_agent_run(
                self.db,
                agent_name="main_generate_question",
                mode=mode,
                attempt_no=attempt,
                status="success",
                input_payload={"yaml": yaml_content, "feedback": feedback},
                output_payload=question.model_dump(),
                feedback_text=feedback,
                error=None,
                model_name=get_agent_settings().generate_question.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="main.generate_question",
                message=f"Question generation tamamlandı. question_id={question.question_id}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "question_id": question.question_id},
            )

            total_rules = len(rules.items)
            self._log(
                mode=mode,
                component="validation.evaluate_rules",
                message=f"Rule evaluation başlatıldı. Toplam {total_rules} kural, paralellik={retry.rule_eval_parallelism}.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={
                    "attempt": attempt,
                    "total_rules": total_rules,
                    "parallelism": retry.rule_eval_parallelism,
                },
            )
            eval_set = await self.agents.evaluate_rules_parallel(
                rules.items,
                question,
                parallelism=retry.rule_eval_parallelism,
                on_progress=lambda idx, total, item: self._log(
                    mode=mode,
                    component="validation.evaluate_rule",
                    message=f"Rule evaluation {idx}/{total}: {item.rule_id} -> {item.status}",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                    details={
                        "attempt": attempt,
                        "index": idx,
                        "total": total,
                        "rule_id": item.rule_id,
                        "status": item.status,
                    },
                ),
            )
            last_eval = eval_set
            for item in eval_set.items:
                repository.record_agent_run(
                    self.db,
                    agent_name="validation_evaluate_rule",
                    mode=mode,
                    attempt_no=attempt,
                    status="success" if item.status != "fail" else "failed",
                    input_payload={"rule": item.rule_id, "attempt": attempt, "question_id": question.question_id},
                    output_payload=item.model_dump(),
                    feedback_text=item.rationale,
                    error=None,
                    model_name=get_agent_settings().evaluate_rule.primary_model if not self.settings.use_stub_agents else "stub",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )

            failed = [it for it in eval_set.items if it.status == "fail"]
            if not failed:
                self._log(
                    mode=mode,
                    component="validation.evaluate_rules",
                    message=f"Rule evaluation başarılı. Attempt {attempt} ile soru kabul edildi.",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                    details={"attempt": attempt, "failed_count": 0},
                )
                return question, eval_set.model_dump(), attempt

            feedback = "\n".join([f"- {row.rule_id}: {row.rationale}" for row in failed])
            self._log(
                mode=mode,
                component="retry.feedback",
                message=f"Question validasyonu başarısız. {len(failed)} kural fail; feedback bir sonraki denemeye aktarıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                level="warning",
                details={
                    "attempt": attempt,
                    "failed_rule_ids": [row.rule_id for row in failed],
                    "feedback": feedback,
                },
            )

        self._log(
            mode=mode,
            component="pipeline",
            message="YAML -> Question retry limiti doldu; son deneme çıktısı döndürülüyor.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="warning",
            details={
                "attempts": retry.question_max_retries,
                "validation_status": "failed",
                "failed_rule_count": len([it for it in last_eval.items if it.status == "fail"]) if last_eval else None,
            },
        )
        if last_question is None:
            raise HTTPException(
                status_code=500,
                detail="Question generation retry döngüsü tamamlandı ancak question üretilemedi.",
            )

        last_eval_payload = last_eval.model_dump() if last_eval else {"items": []}
        return last_question, last_eval_payload, retry.question_max_retries

    async def _run_question_to_layout_loop(
        self,
        *,
        mode: str,
        question: QuestionSpec,
        retry: RetrySettings,
        pipeline_id: str | None,
        sub_pipeline_id: str | None,
    ) -> tuple[LayoutPlan, dict[str, Any], int]:
        self._log(
            mode=mode,
            component="pipeline",
            message="Question -> Layout döngüsü başladı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={"layout_max_retries": retry.layout_max_retries, "question_id": question.question_id},
        )
        feedback: str | None = None
        last_validation = None
        last_layout: LayoutPlan | None = None

        for attempt in range(1, retry.layout_max_retries + 1):
            self._log(
                mode=mode,
                component="main.generate_layout",
                message=f"Layout generation attempt {attempt}/{retry.layout_max_retries} başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            layout = await asyncio.to_thread(self.agents.generate_layout, question, feedback)
            last_layout = layout
            repository.record_agent_run(
                self.db,
                agent_name="main_generate_layout",
                mode=mode,
                attempt_no=attempt,
                status="success",
                input_payload={"question": question.model_dump(), "feedback": feedback},
                output_payload=layout.model_dump(),
                feedback_text=feedback,
                error=None,
                model_name=get_agent_settings().generate_layout.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="main.generate_layout",
                message=f"Layout generation tamamlandı. asset_count={len(layout.asset_library)}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "asset_count": len(layout.asset_library)},
            )

            self._log(
                mode=mode,
                component="validation.question_layout",
                message="Question/Layout validasyonu başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            validation = await asyncio.to_thread(self.agents.validate_question_layout, question, layout)
            last_validation = validation
            repository.record_agent_run(
                self.db,
                agent_name="validation_question_layout",
                mode=mode,
                attempt_no=attempt,
                status="success" if validation.overall_status == "pass" else "failed",
                input_payload={"question": question.model_dump(), "layout": layout.model_dump()},
                output_payload=validation.model_dump(),
                feedback_text=validation.feedback,
                error=None,
                model_name=get_agent_settings().validate_question_layout.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="validation.question_layout",
                message=f"Question/Layout validasyonu tamamlandı. status={validation.overall_status}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "issues": validation.issues, "feedback": validation.feedback},
            )

            if validation.overall_status == "pass":
                self._log(
                    mode=mode,
                    component="pipeline",
                    message=f"Question -> Layout adımı başarılı (attempt={attempt}).",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
                return layout, validation.model_dump(), attempt

            feedback = validation.feedback or "\n".join(validation.issues)
            self._log(
                mode=mode,
                component="retry.feedback",
                message="Layout validasyonu başarısız; feedback bir sonraki denemeye aktarıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                level="warning",
                details={"attempt": attempt, "feedback": feedback},
            )

        self._log(
            mode=mode,
            component="pipeline",
            message="Question -> Layout retry limiti doldu; son deneme çıktısı döndürülüyor.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="warning",
            details={
                "attempts": retry.layout_max_retries,
                "validation_status": last_validation.overall_status if last_validation is not None else "unknown",
            },
        )
        if last_layout is None:
            raise HTTPException(
                status_code=500,
                detail="Layout generation retry döngüsü tamamlandı ancak layout üretilemedi.",
            )
        return (
            last_layout,
            last_validation.model_dump() if last_validation is not None else {"overall_status": "fail", "issues": [], "feedback": ""},
            retry.layout_max_retries,
        )

    async def _run_layout_to_html_loop(
        self,
        *,
        mode: str,
        question: QuestionSpec,
        layout: LayoutPlan,
        retry: RetrySettings,
        pipeline_id: str | None,
        sub_pipeline_id: str | None,
        run_dir: Path | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], int, dict[str, str], str | None, str | None]:
        self._log(
            mode=mode,
            component="pipeline",
            message="Layout -> HTML döngüsü başladı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={
                "html_max_retries": retry.html_max_retries,
                "image_max_retries": retry.image_max_retries,
                "asset_count": len(layout.asset_library),
                "question_id": question.question_id,
            },
        )
        feedback: str | None = None
        feedback_history: list[str] = []
        previous_raw_html: str | None = None
        previous_validation_feedback_history: list[dict[str, Any]] = []
        validate_html_param_count = len(inspect.signature(self.agents.validate_html).parameters)
        validate_html_supports_feedback_history = validate_html_param_count >= 3
        last_validation = None
        last_html: dict[str, Any] | None = None
        last_rendered_image_path: str | None = None
        last_rendered_image_artifact_id: str | None = None
        asset_map: dict[str, str] = {}
        asset_artifact_ids: dict[str, str] = {}
        catalog_context_filenames = sorted(
            {
                Path(asset.source_filename or asset.output_filename).name
                for asset in layout.asset_library.values()
                if asset.asset_type.value == "catalog_component"
            }
        )

        for asset in layout.asset_library.values():
            if asset.asset_type.value == "catalog_component":
                filename = Path(asset.source_filename or asset.output_filename).name
                asset_map[asset.slug] = filename
                catalog_path = self.settings.catalog_dir / filename
                if catalog_path.exists() and catalog_path.is_file():
                    asset_artifact_ids[asset.slug] = self._upload_file_artifact(
                        kind="catalog_asset",
                        path=catalog_path,
                        bucket=self.settings.s3_catalog_bucket,
                        key=filename,
                        mime_type="image/png",
                        pipeline_id=pipeline_id,
                        sub_pipeline_id=sub_pipeline_id,
                    )
                self._log(
                    mode=mode,
                    component="helper.assets",
                    message=f"Catalog asset eşlendi: {asset.slug}",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                    details={
                        "slug": asset.slug,
                        "filename": asset_map[asset.slug],
                        "type": "catalog_component",
                        "artifact_id": asset_artifact_ids.get(asset.slug),
                    },
                )
                continue

            self._log(
                mode=mode,
                component="helper.generate_composite_image",
                message=f"Composite image generation başlatıldı: {asset.slug}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={
                    "slug": asset.slug,
                    "image_max_retries": retry.image_max_retries,
                    "catalog_context_count": len(catalog_context_filenames),
                },
            )
            result = await asyncio.to_thread(
                self.agents.generate_composite_image,
                asset,
                retry.image_max_retries,
                catalog_context_filenames=catalog_context_filenames,
                output_path=None,
            )
            generated_path = Path(result.image_path)
            asset_map[asset.slug] = generated_path.name
            if generated_path.exists() and generated_path.is_file():
                asset_artifact_ids[asset.slug] = self._upload_file_artifact(
                    kind="generated_asset",
                    path=generated_path,
                    bucket=self.settings.s3_generated_bucket,
                    key=f"{sub_pipeline_id or pipeline_id or 'standalone'}/{generated_path.name}",
                    mime_type="image/png",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
            repository.record_agent_run(
                self.db,
                agent_name="helper_generate_composite_image",
                mode=mode,
                attempt_no=1,
                status="success",
                input_payload=asset.model_dump(),
                output_payload=result.model_dump(),
                feedback_text=result.note,
                error=None,
                model_name=get_agent_settings().generate_image.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="helper.generate_composite_image",
                message=f"Composite image hazır: {asset.slug} -> {asset_map[asset.slug]}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={
                    "slug": asset.slug,
                    "filename": asset_map[asset.slug],
                    "artifact_id": asset_artifact_ids.get(asset.slug),
                    "note": result.note,
                },
            )

        for attempt in range(1, retry.html_max_retries + 1):
            safe_question = self.agents.question_payload_for_generate_html(question)
            self._log(
                mode=mode,
                component="main.generate_html",
                message=f"HTML generation attempt {attempt}/{retry.html_max_retries} başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "asset_map_count": len(asset_map)},
            )
            html = await asyncio.to_thread(
                self.agents.generate_html,
                question,
                layout,
                asset_map,
                feedback,
                previous_raw_html,
            )
            current_raw_html = html.html_content
            html.html_content = self.agents.post_process_html_asset_paths(
                html.html_content,
                layout,
                asset_map,
            )
            repository.record_agent_run(
                self.db,
                agent_name="main_generate_html",
                mode=mode,
                attempt_no=attempt,
                status="success",
                input_payload={
                    "question": safe_question,
                    "layout": layout.model_dump(),
                    "asset_map": asset_map,
                    "feedback": feedback,
                    "previous_raw_html": previous_raw_html,
                },
                output_payload=html.model_dump(),
                feedback_text=feedback,
                error=None,
                model_name=get_agent_settings().generate_html.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="main.generate_html",
                message=f"HTML generation tamamlandı. html_length={len(html.html_content)}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "html_length": len(html.html_content)},
            )

            rendered_image_internal_path = await asyncio.to_thread(
                self.agents.render_html_to_image,
                html.html_content,
                asset_map=asset_map,
                question_id=layout.question_id,
                attempt=attempt,
                run_assets_dir=None,
                render_dir=None,
            )
            rendered_internal = Path(rendered_image_internal_path)
            rendered_image_artifact_id = None
            if rendered_internal.exists() and rendered_internal.is_file():
                rendered_image_artifact_id = self._upload_file_artifact(
                    kind="rendered_image",
                    path=rendered_internal,
                    bucket=self.settings.s3_rendered_bucket,
                    key=f"{sub_pipeline_id or pipeline_id or 'standalone'}/{rendered_internal.name}",
                    mime_type="image/png",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
            rendered_image_path = (
                self._artifact_response_url(rendered_image_artifact_id)
                if rendered_image_artifact_id
                else rendered_image_internal_path
            )
            last_html = html.model_dump()
            last_rendered_image_path = rendered_image_path
            last_rendered_image_artifact_id = rendered_image_artifact_id
            self._log(
                mode=mode,
                component="html.render",
                message=f"HTML render edildi: {Path(rendered_image_internal_path).name}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "rendered_image_path": rendered_image_path},
            )

            # Publish render completion immediately so UI can show PNG while validation is running.
            publish_event(self._stream_key or "", "html_render", {
                "attempt": attempt,
                "max_attempts": retry.html_max_retries,
                "rendered_image_path": rendered_image_path,
            })

            self._log(
                mode=mode,
                component="validation.layout_html",
                message="Layout/HTML validasyonu başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            if validate_html_supports_feedback_history:
                validation = await asyncio.to_thread(
                    self.agents.validate_html,
                    html.html_content,
                    rendered_image_internal_path,
                    list(previous_validation_feedback_history),
                )
            else:
                validation = await asyncio.to_thread(
                    self.agents.validate_html,
                    html.html_content,
                    rendered_image_internal_path,
                )
            last_validation = validation
            repository.record_agent_run(
                self.db,
                agent_name="validation_layout_html",
                mode=mode,
                attempt_no=attempt,
                status="success" if validation.overall_status == "pass" else "failed",
                input_payload={
                    "html": html.html_content,
                    "rendered_image_path": rendered_image_internal_path,
                    "prior_feedback_history": list(previous_validation_feedback_history),
                },
                output_payload=validation.model_dump(),
                feedback_text=validation.feedback,
                error=None,
                model_name=get_agent_settings().validate_html.primary_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="validation.layout_html",
                message=f"Layout/HTML validasyonu tamamlandı. status={validation.overall_status}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "issues": validation.issues, "feedback": validation.feedback},
            )
            previous_validation_feedback_history.append(
                {
                    "attempt": attempt,
                    "status": validation.overall_status,
                    "feedback": validation.feedback,
                    "issues": list(validation.issues),
                }
            )

            # Publish validation completion separately from render completion.
            publish_event(self._stream_key or "", "html_validation", {
                "attempt": attempt,
                "status": validation.overall_status,
                "feedback": validation.feedback if validation.overall_status != "pass" else None,
                "issues": validation.issues if validation.overall_status != "pass" else [],
            })

            if validation.overall_status == "pass":
                final_rendered_image_path = rendered_image_path
                final_html_payload = html.model_dump()
                final_html_payload["html_content"] = self._artifactize_html_asset_urls(
                    str(final_html_payload.get("html_content") or ""),
                    asset_map,
                    asset_artifact_ids,
                )
                self._log(
                    mode=mode,
                    component="pipeline",
                    message=f"Layout -> HTML adımı başarılı (attempt={attempt}).",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
                return (
                    final_html_payload,
                    validation.model_dump(),
                    attempt,
                    {slug: self._artifact_response_url(artifact_id) for slug, artifact_id in asset_artifact_ids.items()},
                    final_rendered_image_path,
                    rendered_image_artifact_id,
                )

            current_feedback = validation.feedback or "\n".join(validation.issues)
            feedback_history.append(current_feedback)
            feedback = "\n\n".join(feedback_history)
            previous_raw_html = current_raw_html
            self._log(
                mode=mode,
                component="retry.feedback",
                message="HTML validasyonu başarısız; feedback bir sonraki denemeye aktarıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                level="warning",
                details={"attempt": attempt, "feedback": feedback, "current_feedback": current_feedback},
            )

        if last_validation is None:
            last_validation_payload = {
                "overall_status": "fail",
                "issues": ["HTML validasyon sonucu alınamadı."],
                "feedback": "HTML denemeleri tamamlandı ancak geçerli bir kalite validasyon çıktısı üretilmedi.",
            }
        else:
            last_validation_payload = last_validation.model_dump()

        if last_html is None:
            last_html = {"selected_template": "unknown", "html_content": "", "schema_version": "question-html.v1"}
        else:
            last_html["html_content"] = self._artifactize_html_asset_urls(
                str(last_html.get("html_content") or ""),
                asset_map,
                asset_artifact_ids,
            )

        self._log(
            mode=mode,
            component="pipeline",
            message="Layout -> HTML retry limiti doldu; son deneme çıktısı hata atmadan döndürülüyor.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="warning",
            details={
                "attempts": retry.html_max_retries,
                "validation_status": last_validation_payload.get("overall_status"),
                "rendered_image_path": last_rendered_image_path,
            },
        )
        return (
            last_html,
            last_validation_payload,
            retry.html_max_retries,
            {slug: self._artifact_response_url(artifact_id) for slug, artifact_id in asset_artifact_ids.items()},
            last_rendered_image_path,
            last_rendered_image_artifact_id,
        )

    def _question_from_artifact(self, artifact_id: str) -> QuestionSpec:
        artifact = repository.get_artifact(self.db, artifact_id)
        if artifact is None or artifact.kind != "question":
            raise HTTPException(status_code=404, detail="Question artifact bulunamadı")
        data = repository.parse_json(artifact.content_json)
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Question artifact içeriği geçersiz")
        return QuestionSpec.model_validate(data)

    def _layout_from_artifact(self, artifact_id: str) -> LayoutPlan:
        artifact = repository.get_artifact(self.db, artifact_id)
        if artifact is None or artifact.kind != "layout":
            raise HTTPException(status_code=404, detail="Layout artifact bulunamadı")
        data = repository.parse_json(artifact.content_json)
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Layout artifact içeriği geçersiz")
        return LayoutPlan.model_validate(data)

    async def run_full_pipeline(self, yaml_instance_id: str, retry_config: RetryConfig | None, stream_key: str | None = None) -> FullPipelineRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)

        pipeline = repository.create_pipeline(
            self.db,
            yaml_filename="",
            yaml_instance_id=yaml_instance_id,
            retry_config=retry.__dict__,
        )
        self.agents.stream_key = self._stream_key

        self._log(
            mode="full",
            component="pipeline",
            message=f"Full pipeline başlatıldı. yaml_instance_id={yaml_instance_id}",
            pipeline_id=pipeline.id,
            sub_pipeline_id=None,
            details=retry.__dict__,
        )

        sub_q = repository.create_sub_pipeline(
            self.db,
            kind="yaml_to_question",
            mode="full",
            pipeline_id=pipeline.id,
            input_payload={"yaml_instance_id": yaml_instance_id},
        )
        sub_l = repository.create_sub_pipeline(
            self.db,
            kind="question_to_layout",
            mode="full",
            pipeline_id=pipeline.id,
            input_payload={},
        )
        sub_h = repository.create_sub_pipeline(
            self.db,
            kind="layout_to_html",
            mode="full",
            pipeline_id=pipeline.id,
            input_payload={},
        )
        self._log(
            mode="full",
            component="pipeline",
            message="Sub-pipeline kayıtları açıldı.",
            pipeline_id=pipeline.id,
            sub_pipeline_id=None,
            details={
                "yaml_to_question": sub_q.id,
                "question_to_layout": sub_l.id,
                "layout_to_html": sub_h.id,
            },
        )

        try:
            self._log(
                mode="full",
                component="pipeline",
                message=f"YAML instance okunuyor: {yaml_instance_id}",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
            )
            yaml_content = self._load_yaml_instance_payload(yaml_instance_id)
            self._log(
                mode="full",
                component="pipeline",
                message="YAML instance başarıyla okundu.",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
                details={"top_level_keys": sorted(list(yaml_content.keys()))},
            )

            question, rule_eval, qa = await self._run_yaml_to_question_loop(
                mode="full",
                yaml_content=yaml_content,
                retry=retry,
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
            )
            repository.finish_sub_pipeline(
                self.db,
                sub_q.id,
                status="success",
                output_payload={
                    "question": question.model_dump(),
                    "rule_evaluation": rule_eval,
                    "attempts": qa,
                },
            )
            question_artifact_id = self._create_json_artifact(
                kind="question",
                payload=question.model_dump(),
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
            )
            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: yaml_to_question (attempts={qa})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
                details={"question_artifact_id": question_artifact_id},
            )

            layout, ql_validation, la = await self._run_question_to_layout_loop(
                mode="full",
                question=question,
                retry=retry,
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_l.id,
            )
            repository.finish_sub_pipeline(
                self.db,
                sub_l.id,
                status="success",
                output_payload={"layout": layout.model_dump(), "validation": ql_validation, "attempts": la},
            )
            layout_artifact_id = self._create_json_artifact(
                kind="layout",
                payload=layout.model_dump(),
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_l.id,
            )
            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: question_to_layout (attempts={la})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_l.id,
                details={"layout_artifact_id": layout_artifact_id},
            )

            raw_html, lh_validation, ha, asset_map, rendered_image_path, rendered_image_artifact_id = await self._run_layout_to_html_loop(
                mode="full",
                question=question,
                layout=layout,
                retry=retry,
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
                run_dir=None,
            )
            html = self._normalize_html_payload_for_server(raw_html)
            html_artifact_id = self._create_json_artifact(
                kind="html",
                payload=html,
                text=str(html.get("html_content") or ""),
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
            )
            repository.finish_sub_pipeline(
                self.db,
                sub_h.id,
                status="success",
                output_payload={
                    "html": html,
                    "validation": lh_validation,
                    "attempts": ha,
                    "asset_map": asset_map,
                    "rendered_image_path": rendered_image_path,
                    "html_artifact_id": html_artifact_id,
                    "rendered_image_artifact_id": rendered_image_artifact_id,
                },
            )

            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: layout_to_html (attempts={ha})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
                details={
                    "html_artifact_id": html_artifact_id,
                    "rendered_image_artifact_id": rendered_image_artifact_id,
                },
            )

            repository.finish_pipeline(self.db, pipeline.id, status="success")
            self._log(
                mode="full",
                component="pipeline",
                message="Full pipeline başarıyla tamamlandı.",
                pipeline_id=pipeline.id,
                sub_pipeline_id=None,
            )

            return FullPipelineRunResponse(
                pipeline_id=pipeline.id,
                sub_pipeline_ids={
                    "yaml_to_question": sub_q.id,
                    "question_to_layout": sub_l.id,
                    "layout_to_html": sub_h.id,
                },
                question_artifact_id=question_artifact_id,
                layout_artifact_id=layout_artifact_id,
                html_artifact_id=html_artifact_id,
                rendered_image_artifact_id=rendered_image_artifact_id,
                question_json=question,
                layout_plan_json=layout,
                question_html=html,
            )
        except Exception as exc:
            self._log(
                mode="full",
                component="pipeline",
                message=f"Full pipeline hata ile sonlandı: {exc}",
                pipeline_id=pipeline.id,
                sub_pipeline_id=None,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_q.id, status="failed", error=str(exc))
            repository.finish_sub_pipeline(self.db, sub_l.id, status="failed", error=str(exc))
            repository.finish_sub_pipeline(self.db, sub_h.id, status="failed", error=str(exc))
            repository.finish_pipeline(self.db, pipeline.id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_yaml_to_question(self, yaml_instance_id: str, retry_config: RetryConfig | None, stream_key: str | None = None) -> YamlToQuestionRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="yaml_to_question",
            mode="sub",
            pipeline_id=None,
            input_payload={"yaml_instance_id": yaml_instance_id},
        )
        sub_id = sub.id
        self.agents.stream_key = self._stream_key

        self._log(
            mode="sub",
            component="pipeline",
            message=f"Sub-pipeline başlatıldı: yaml_to_question (yaml_instance_id={yaml_instance_id})",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"YAML instance okunuyor: {yaml_instance_id}",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            yaml_content = self._load_yaml_instance_payload(yaml_instance_id)
            self._log(
                mode="sub",
                component="pipeline",
                message="YAML instance başarıyla okundu.",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                details={"top_level_keys": sorted(list(yaml_content.keys()))},
            )
            question, rule_eval, attempts = await self._run_yaml_to_question_loop(
                mode="sub",
                yaml_content=yaml_content,
                retry=retry,
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            payload = {"question": question.model_dump(), "rule_evaluation": rule_eval, "attempts": attempts}
            repository.finish_sub_pipeline(self.db, sub_id, status="success", output_payload=payload)
            question_artifact_id = self._create_json_artifact(
                kind="question",
                payload=question.model_dump(),
                sub_pipeline_id=sub_id,
            )

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: yaml_to_question (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                details={"question_artifact_id": question_artifact_id},
            )
            return YamlToQuestionRunResponse(
                sub_pipeline_id=sub_id,
                question_artifact_id=question_artifact_id,
                question_json=question,
                rule_evaluation=rule_eval,
                attempts=attempts,
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: yaml_to_question ({exc.args[0] if exc.args else str(exc)})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_question_to_layout(
        self,
        question_artifact_id: str,
        retry_config: RetryConfig | None,
        stream_key: str | None = None,
    ) -> QuestionToLayoutRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        question = self._question_from_artifact(question_artifact_id)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="question_to_layout",
            mode="sub",
            pipeline_id=None,
            input_payload={"question_artifact_id": question_artifact_id},
        )
        sub_id = sub.id
        self.agents.stream_key = self._stream_key

        self._log(
            mode="sub",
            component="pipeline",
            message="Sub-pipeline başlatıldı: question_to_layout",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            layout, validation, attempts = await self._run_question_to_layout_loop(
                mode="sub",
                question=question,
                retry=retry,
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            payload = {"layout": layout.model_dump(), "validation": validation, "attempts": attempts}
            repository.finish_sub_pipeline(self.db, sub_id, status="success", output_payload=payload)
            layout_artifact_id = self._create_json_artifact(
                kind="layout",
                payload=layout.model_dump(),
                sub_pipeline_id=sub_id,
            )

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: question_to_layout (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                details={"layout_artifact_id": layout_artifact_id},
            )
            return QuestionToLayoutRunResponse(
                sub_pipeline_id=sub_id,
                layout_artifact_id=layout_artifact_id,
                layout_plan_json=layout,
                validation=validation,
                attempts=attempts,
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: question_to_layout ({exc.args[0] if exc.args else str(exc)})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_layout_to_html(
        self,
        question_artifact_id: str,
        layout_artifact_id: str,
        retry_config: RetryConfig | None,
        stream_key: str | None = None,
    ) -> LayoutToHtmlRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        question = self._question_from_artifact(question_artifact_id)
        layout = self._layout_from_artifact(layout_artifact_id)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="layout_to_html",
            mode="sub",
            pipeline_id=None,
            input_payload={"question_artifact_id": question_artifact_id, "layout_artifact_id": layout_artifact_id},
        )
        sub_id = sub.id
        self.agents.stream_key = self._stream_key

        self._log(
            mode="sub",
            component="pipeline",
            message="Sub-pipeline başlatıldı: layout_to_html",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            raw_html, validation, attempts, asset_map, rendered_image_path, rendered_image_artifact_id = await self._run_layout_to_html_loop(
                mode="sub",
                question=question,
                layout=layout,
                retry=retry,
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                run_dir=None,
            )
            html = self._normalize_html_payload_for_server(raw_html)
            html_artifact_id = self._create_json_artifact(
                kind="html",
                payload=html,
                text=str(html.get("html_content") or ""),
                sub_pipeline_id=sub_id,
            )
            payload = {
                "html": html,
                "validation": validation,
                "attempts": attempts,
                "asset_map": asset_map,
                "rendered_image_path": rendered_image_path,
                "html_artifact_id": html_artifact_id,
                "rendered_image_artifact_id": rendered_image_artifact_id,
            }
            repository.finish_sub_pipeline(self.db, sub_id, status="success", output_payload=payload)

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: layout_to_html (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                details={
                    "html_artifact_id": html_artifact_id,
                    "rendered_image_artifact_id": rendered_image_artifact_id,
                },
            )
            return LayoutToHtmlRunResponse(
                sub_pipeline_id=sub_id,
                html_artifact_id=html_artifact_id,
                rendered_image_artifact_id=rendered_image_artifact_id,
                question_html=html,
                validation=validation,
                attempts=attempts,
                generated_assets=asset_map,
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: layout_to_html ({exc.args[0] if exc.args else str(exc)})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")
