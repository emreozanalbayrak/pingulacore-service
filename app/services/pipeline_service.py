from __future__ import annotations

import asyncio
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
from app.services.run_dir_service import (
    create_full_run_dir,
    create_sub_run_dir,
    run_relative_path,
    update_manifest_status,
    write_manifest,
)
from app.services.sub_pipeline_files_service import write_html_file, write_layout_file, write_question_file
from app.services.yaml_service import load_yaml_file


class PipelineService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.agents = AgentService(self.settings)
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

    def _persist_sub_output_question(
        self,
        *,
        mode: str,
        sub_pipeline_id: str,
        question: QuestionSpec,
        pipeline_id: str | None = None,
    ) -> None:
        filename = write_question_file(question, sub_pipeline_id=sub_pipeline_id)
        self._log(
            mode=mode,
            component="filesystem",
            message=f"QuestionSpec dosyaya kaydedildi: sp_files/q_json/{filename}",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={"file": filename, "kind": "q_json"},
        )

    def _persist_sub_output_layout(
        self,
        *,
        mode: str,
        sub_pipeline_id: str,
        layout: LayoutPlan,
        pipeline_id: str | None = None,
    ) -> None:
        filename = write_layout_file(layout, sub_pipeline_id=sub_pipeline_id)
        self._log(
            mode=mode,
            component="filesystem",
            message=f"LayoutPlan dosyaya kaydedildi: sp_files/layout/{filename}",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={"file": filename, "kind": "layout"},
        )

    def _persist_sub_output_html(
        self,
        *,
        mode: str,
        sub_pipeline_id: str,
        html_payload: dict[str, Any],
        question_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> None:
        filename = write_html_file(html_payload, sub_pipeline_id=sub_pipeline_id, question_id=question_id)
        self._log(
            mode=mode,
            component="filesystem",
            message=f"HTML dosyaya kaydedildi: sp_files/q_html/{filename}",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            details={"file": filename, "kind": "q_html"},
        )

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
        last_eval = None
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
            message="YAML -> Question döngüsü retry limitine takıldı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="error",
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Question generation retry limiti aşıldı.",
                "rule_evaluation": last_eval.model_dump() if last_eval else {},
            },
        )

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
            message="Question -> Layout döngüsü retry limitine takıldı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="error",
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Layout generation retry limiti aşıldı.",
                "validation": last_validation.model_dump() if last_validation else {},
            },
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
    ) -> tuple[dict[str, Any], dict[str, Any], int, dict[str, str], str | None]:
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
        last_validation = None
        last_html: dict[str, Any] | None = None
        last_rendered_image_path: str | None = None
        asset_map: dict[str, str] = {}
        catalog_context_filenames = sorted(
            {
                Path(asset.source_filename or asset.output_filename).name
                for asset in layout.asset_library.values()
                if asset.asset_type.value == "catalog_component"
            }
        )

        for asset in layout.asset_library.values():
            if asset.asset_type.value == "catalog_component":
                asset_map[asset.slug] = Path(asset.source_filename or asset.output_filename).name
                self._log(
                    mode=mode,
                    component="helper.assets",
                    message=f"Catalog asset eşlendi: {asset.slug}",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                    details={"slug": asset.slug, "filename": asset_map[asset.slug], "type": "catalog_component"},
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
            img_output_path = (
                run_dir / "assets" / f"{asset.slug}.png" if run_dir is not None else None
            )
            result = await asyncio.to_thread(
                self.agents.generate_composite_image,
                asset,
                retry.image_max_retries,
                catalog_context_filenames=catalog_context_filenames,
                output_path=img_output_path,
            )
            if run_dir is not None:
                asset_map[asset.slug] = run_relative_path(run_dir, self.settings.runs_dir, "assets", f"{asset.slug}.png")
            else:
                asset_map[asset.slug] = Path(result.image_path).name
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
                model_name=self.settings.gemini_image_model if not self.settings.use_stub_agents else "stub",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
            )
            self._log(
                mode=mode,
                component="helper.generate_composite_image",
                message=f"Composite image hazır: {asset.slug} -> {asset_map[asset.slug]}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"slug": asset.slug, "filename": asset_map[asset.slug], "note": result.note},
            )

        for attempt in range(1, retry.html_max_retries + 1):
            self._log(
                mode=mode,
                component="main.generate_html",
                message=f"HTML generation attempt {attempt}/{retry.html_max_retries} başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "asset_map_count": len(asset_map)},
            )
            html = await asyncio.to_thread(self.agents.generate_html, question, layout, asset_map, feedback)
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
                    "question": question.model_dump(),
                    "layout": layout.model_dump(),
                    "asset_map": asset_map,
                    "feedback": feedback,
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

            rendered_image_path = await asyncio.to_thread(
                self.agents.render_html_to_image,
                html.html_content,
                asset_map=asset_map,
                question_id=layout.question_id,
                run_assets_dir=run_dir / "assets" if run_dir is not None else None,
                render_dir=run_dir,
            )
            last_html = html.model_dump()
            last_rendered_image_path = rendered_image_path
            self._log(
                mode=mode,
                component="html.render",
                message=f"HTML render edildi: {Path(rendered_image_path).name}",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt, "rendered_image_path": rendered_image_path},
            )

            self._log(
                mode=mode,
                component="validation.layout_html",
                message="Layout/HTML validasyonu başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            validation = await asyncio.to_thread(self.agents.validate_html, html.html_content, rendered_image_path)
            last_validation = validation
            repository.record_agent_run(
                self.db,
                agent_name="validation_layout_html",
                mode=mode,
                attempt_no=attempt,
                status="success" if validation.overall_status == "pass" else "failed",
                input_payload={"html": html.html_content, "rendered_image_path": rendered_image_path},
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

            # Publish real-time iteration event for frontend
            publish_event(self._stream_key or "", "html_iteration", {
                "attempt": attempt,
                "max_attempts": retry.html_max_retries,
                "rendered_image_path": rendered_image_path,
                "status": validation.overall_status,
                "feedback": validation.feedback if validation.overall_status != "pass" else None,
                "issues": validation.issues if validation.overall_status != "pass" else [],
            })

            if validation.overall_status == "pass":
                self._log(
                    mode=mode,
                    component="pipeline",
                    message=f"Layout -> HTML adımı başarılı (attempt={attempt}).",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
                return html.model_dump(), validation.model_dump(), attempt, asset_map, rendered_image_path

            feedback = validation.feedback or "\n".join(validation.issues)
            self._log(
                mode=mode,
                component="retry.feedback",
                message="HTML validasyonu başarısız; feedback bir sonraki denemeye aktarıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                level="warning",
                details={"attempt": attempt, "feedback": feedback},
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
        return last_html, last_validation_payload, retry.html_max_retries, asset_map, last_rendered_image_path

    async def run_full_pipeline(self, yaml_filename: str, retry_config: RetryConfig | None, stream_key: str | None = None) -> FullPipelineRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)

        pipeline = repository.create_pipeline(
            self.db,
            yaml_filename=yaml_filename,
            retry_config=retry.__dict__,
        )

        run_dir = create_full_run_dir(self.settings.runs_dir, yaml_filename)
        self._log_path = run_dir / "log.txt"
        self.agents.log_path = self._log_path
        self.agents.stream_key = self._stream_key
        write_manifest(
            run_dir,
            run_type="full",
            yaml_filename=yaml_filename,
            agent_name=None,
            pipeline_id=pipeline.id,
            sub_pipeline_id=None,
            sub_kind=None,
        )

        self._log(
            mode="full",
            component="pipeline",
            message=f"Full pipeline başlatıldı. yaml={yaml_filename}",
            pipeline_id=pipeline.id,
            sub_pipeline_id=None,
            details=retry.__dict__,
        )

        sub_q = repository.create_sub_pipeline(
            self.db,
            kind="yaml_to_question",
            mode="full",
            pipeline_id=pipeline.id,
            input_payload={"yaml_filename": yaml_filename},
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
                message=f"YAML okunuyor: {yaml_filename}",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
            )
            yaml_content = load_yaml_file(yaml_filename)
            self._log(
                mode="full",
                component="pipeline",
                message="YAML başarıyla okundu ve parse edildi.",
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
            self._persist_sub_output_question(
                mode="full",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
                question=question,
            )
            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: yaml_to_question (attempts={qa})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_q.id,
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
            self._persist_sub_output_layout(
                mode="full",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_l.id,
                layout=layout,
            )
            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: question_to_layout (attempts={la})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_l.id,
            )

            html, lh_validation, ha, asset_map, rendered_image_path = await self._run_layout_to_html_loop(
                mode="full",
                question=question,
                layout=layout,
                retry=retry,
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
                run_dir=run_dir,
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
                },
            )
            self._persist_sub_output_html(
                mode="full",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
                html_payload=html,
                question_id=layout.question_id,
            )

            # Write all pipeline artifacts into the structured run directory
            (run_dir / "question.json").write_text(question.model_dump_json(indent=2), encoding="utf-8")
            (run_dir / "layout.json").write_text(layout.model_dump_json(indent=2), encoding="utf-8")
            (run_dir / "question.html").write_text(html.get("html_content", ""), encoding="utf-8")

            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: layout_to_html (attempts={ha})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
            )

            repository.finish_pipeline(self.db, pipeline.id, status="success")
            update_manifest_status(run_dir, "success")
            self._log(
                mode="full",
                component="pipeline",
                message="Full pipeline başarıyla tamamlandı.",
                pipeline_id=pipeline.id,
                sub_pipeline_id=None,
            )

            run_path = str(run_dir.relative_to(self.settings.root_dir))
            return FullPipelineRunResponse(
                pipeline_id=pipeline.id,
                sub_pipeline_ids={
                    "yaml_to_question": sub_q.id,
                    "question_to_layout": sub_l.id,
                    "layout_to_html": sub_h.id,
                },
                question_json=question,
                layout_plan_json=layout,
                question_html=html,
                rendered_image_path=rendered_image_path,
                run_path=run_path,
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
            update_manifest_status(run_dir, "failed")
            repository.finish_sub_pipeline(self.db, sub_q.id, status="failed", error=str(exc))
            repository.finish_sub_pipeline(self.db, sub_l.id, status="failed", error=str(exc))
            repository.finish_sub_pipeline(self.db, sub_h.id, status="failed", error=str(exc))
            repository.finish_pipeline(self.db, pipeline.id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_yaml_to_question(self, yaml_filename: str, retry_config: RetryConfig | None, stream_key: str | None = None) -> YamlToQuestionRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="yaml_to_question",
            mode="sub",
            pipeline_id=None,
            input_payload={"yaml_filename": yaml_filename},
        )
        sub_id = sub.id

        run_dir = create_sub_run_dir(self.settings.runs_dir, yaml_filename=yaml_filename)
        self._log_path = run_dir / "log.txt"
        self.agents.log_path = self._log_path
        self.agents.stream_key = self._stream_key
        write_manifest(
            run_dir,
            run_type="sub",
            yaml_filename=yaml_filename,
            agent_name=None,
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            sub_kind="yaml_to_question",
        )

        self._log(
            mode="sub",
            component="pipeline",
            message=f"Sub-pipeline başlatıldı: yaml_to_question (yaml={yaml_filename})",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"YAML okunuyor: {yaml_filename}",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            yaml_content = load_yaml_file(yaml_filename)
            self._log(
                mode="sub",
                component="pipeline",
                message="YAML başarıyla okundu.",
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
            self._persist_sub_output_question(mode="sub", sub_pipeline_id=sub_id, question=question)

            (run_dir / "question.json").write_text(question.model_dump_json(indent=2), encoding="utf-8")
            update_manifest_status(run_dir, "success")

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: yaml_to_question (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            return YamlToQuestionRunResponse(
                sub_pipeline_id=sub_id,
                question_json=question,
                rule_evaluation=rule_eval,
                attempts=attempts,
                run_path=str(run_dir.relative_to(self.settings.root_dir)),
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
            update_manifest_status(run_dir, "failed")
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_question_to_layout(
        self,
        question: QuestionSpec,
        retry_config: RetryConfig | None,
        stream_key: str | None = None,
    ) -> QuestionToLayoutRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="question_to_layout",
            mode="sub",
            pipeline_id=None,
            input_payload=question.model_dump(),
        )
        sub_id = sub.id

        run_dir = create_sub_run_dir(self.settings.runs_dir, token=question.question_id)
        self._log_path = run_dir / "log.txt"
        self.agents.log_path = self._log_path
        self.agents.stream_key = self._stream_key
        write_manifest(
            run_dir,
            run_type="sub",
            yaml_filename=None,
            agent_name=None,
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            sub_kind="question_to_layout",
        )

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
            self._persist_sub_output_layout(mode="sub", sub_pipeline_id=sub_id, layout=layout)

            (run_dir / "layout.json").write_text(layout.model_dump_json(indent=2), encoding="utf-8")
            update_manifest_status(run_dir, "success")

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: question_to_layout (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            return QuestionToLayoutRunResponse(
                sub_pipeline_id=sub_id,
                layout_plan_json=layout,
                validation=validation,
                attempts=attempts,
                run_path=str(run_dir.relative_to(self.settings.root_dir)),
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
            update_manifest_status(run_dir, "failed")
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")

    async def run_sub_layout_to_html(
        self,
        question: QuestionSpec,
        layout: LayoutPlan,
        retry_config: RetryConfig | None,
        stream_key: str | None = None,
    ) -> LayoutToHtmlRunResponse:
        self._stream_key = stream_key
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="layout_to_html",
            mode="sub",
            pipeline_id=None,
            input_payload={"question": question.model_dump(), "layout": layout.model_dump()},
        )
        sub_id = sub.id

        run_dir = create_sub_run_dir(self.settings.runs_dir, token=question.question_id)
        self._log_path = run_dir / "log.txt"
        self.agents.log_path = self._log_path
        self.agents.stream_key = self._stream_key
        write_manifest(
            run_dir,
            run_type="sub",
            yaml_filename=None,
            agent_name=None,
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            sub_kind="layout_to_html",
        )

        self._log(
            mode="sub",
            component="pipeline",
            message="Sub-pipeline başlatıldı: layout_to_html",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            html, validation, attempts, asset_map, rendered_image_path = await self._run_layout_to_html_loop(
                mode="sub",
                question=question,
                layout=layout,
                retry=retry,
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                run_dir=run_dir,
            )
            payload = {
                "html": html,
                "validation": validation,
                "attempts": attempts,
                "asset_map": asset_map,
                "rendered_image_path": rendered_image_path,
            }
            repository.finish_sub_pipeline(self.db, sub_id, status="success", output_payload=payload)
            self._persist_sub_output_html(
                mode="sub",
                sub_pipeline_id=sub_id,
                html_payload=html,
                question_id=layout.question_id,
            )

            (run_dir / "question.html").write_text(html.get("html_content", ""), encoding="utf-8")
            update_manifest_status(run_dir, "success")

            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline başarıyla tamamlandı: layout_to_html (attempts={attempts})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            return LayoutToHtmlRunResponse(
                sub_pipeline_id=sub_id,
                question_html=html,
                validation=validation,
                attempts=attempts,
                generated_assets=asset_map,
                rendered_image_path=rendered_image_path,
                run_path=str(run_dir.relative_to(self.settings.root_dir)),
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
            update_manifest_status(run_dir, "failed")
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
        finally:
            publish_done(self._stream_key or "")
