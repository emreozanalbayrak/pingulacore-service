from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents.agent_service import AgentService
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
from app.services.pipeline_log_service import write_pipeline_log
from app.services.retry_service import RetrySettings, merge_retry_config
from app.services.sub_pipeline_files_service import write_html_file, write_layout_file, write_question_file
from app.services.yaml_service import load_yaml_file


class PipelineService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.agents = AgentService(self.settings)

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
        rules = self.agents.extract_rules(yaml_content)
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
            model_name=self.settings.gemini_light_model if not self.settings.use_stub_agents else "stub",
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
            question = self.agents.generate_question(yaml_content, feedback)
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
                model_name=self.settings.gemini_text_model if not self.settings.use_stub_agents else "stub",
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
                    model_name=self.settings.gemini_light_model if not self.settings.use_stub_agents else "stub",
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
            layout = self.agents.generate_layout(question, feedback)
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
                model_name=self.settings.gemini_text_model if not self.settings.use_stub_agents else "stub",
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
            validation = self.agents.validate_question_layout(question, layout)
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
                model_name=self.settings.gemini_text_model if not self.settings.use_stub_agents else "stub",
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
        layout: LayoutPlan,
        retry: RetrySettings,
        pipeline_id: str | None,
        sub_pipeline_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any], int, dict[str, str]]:
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
            },
        )
        feedback: str | None = None
        last_validation = None
        asset_map: dict[str, str] = {}

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
                details={"slug": asset.slug, "image_max_retries": retry.image_max_retries},
            )
            result = self.agents.generate_composite_image(asset, retry.image_max_retries)
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
            html = self.agents.generate_html(layout, asset_map, feedback)
            repository.record_agent_run(
                self.db,
                agent_name="main_generate_html",
                mode=mode,
                attempt_no=attempt,
                status="success",
                input_payload={"layout": layout.model_dump(), "asset_map": asset_map, "feedback": feedback},
                output_payload=html.model_dump(),
                feedback_text=feedback,
                error=None,
                model_name=self.settings.gemini_text_model if not self.settings.use_stub_agents else "stub",
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

            self._log(
                mode=mode,
                component="validation.layout_html",
                message="Layout/HTML validasyonu başlatıldı.",
                pipeline_id=pipeline_id,
                sub_pipeline_id=sub_pipeline_id,
                details={"attempt": attempt},
            )
            validation = self.agents.validate_layout_html(layout, html.html_content)
            last_validation = validation
            repository.record_agent_run(
                self.db,
                agent_name="validation_layout_html",
                mode=mode,
                attempt_no=attempt,
                status="success" if validation.overall_status == "pass" else "failed",
                input_payload={"layout": layout.model_dump(), "html": html.html_content},
                output_payload=validation.model_dump(),
                feedback_text=validation.feedback,
                error=None,
                model_name=self.settings.gemini_text_model if not self.settings.use_stub_agents else "stub",
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

            if validation.overall_status == "pass":
                self._log(
                    mode=mode,
                    component="pipeline",
                    message=f"Layout -> HTML adımı başarılı (attempt={attempt}).",
                    pipeline_id=pipeline_id,
                    sub_pipeline_id=sub_pipeline_id,
                )
                return html.model_dump(), validation.model_dump(), attempt, asset_map

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

        self._log(
            mode=mode,
            component="pipeline",
            message="Layout -> HTML döngüsü retry limitine takıldı.",
            pipeline_id=pipeline_id,
            sub_pipeline_id=sub_pipeline_id,
            level="error",
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "HTML generation retry limiti aşıldı.",
                "validation": last_validation.model_dump() if last_validation else {},
            },
        )

    async def run_full_pipeline(self, yaml_filename: str, retry_config: RetryConfig | None) -> FullPipelineRunResponse:
        retry = merge_retry_config(retry_config, self.settings)

        pipeline = repository.create_pipeline(
            self.db,
            yaml_filename=yaml_filename,
            retry_config=retry.__dict__,
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

            html, lh_validation, ha, asset_map = await self._run_layout_to_html_loop(
                mode="full",
                layout=layout,
                retry=retry,
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
                },
            )
            self._persist_sub_output_html(
                mode="full",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
                html_payload=html,
                question_id=layout.question_id,
            )
            self._log(
                mode="full",
                component="pipeline",
                message=f"Sub-pipeline tamamlandı: layout_to_html (attempts={ha})",
                pipeline_id=pipeline.id,
                sub_pipeline_id=sub_h.id,
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

    async def run_sub_yaml_to_question(self, yaml_filename: str, retry_config: RetryConfig | None) -> YamlToQuestionRunResponse:
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="yaml_to_question",
            mode="sub",
            pipeline_id=None,
            input_payload={"yaml_filename": yaml_filename},
        )
        sub_id = sub.id
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
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: yaml_to_question ({exc})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise

    async def run_sub_question_to_layout(
        self,
        question: QuestionSpec,
        retry_config: RetryConfig | None,
    ) -> QuestionToLayoutRunResponse:
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="question_to_layout",
            mode="sub",
            pipeline_id=None,
            input_payload=question.model_dump(),
        )
        sub_id = sub.id
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
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: question_to_layout ({exc})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise

    async def run_sub_layout_to_html(
        self,
        layout: LayoutPlan,
        retry_config: RetryConfig | None,
    ) -> LayoutToHtmlRunResponse:
        retry = merge_retry_config(retry_config, self.settings)
        sub = repository.create_sub_pipeline(
            self.db,
            kind="layout_to_html",
            mode="sub",
            pipeline_id=None,
            input_payload=layout.model_dump(),
        )
        sub_id = sub.id
        self._log(
            mode="sub",
            component="pipeline",
            message="Sub-pipeline başlatıldı: layout_to_html",
            pipeline_id=None,
            sub_pipeline_id=sub_id,
            details=retry.__dict__,
        )

        try:
            html, validation, attempts, asset_map = await self._run_layout_to_html_loop(
                mode="sub",
                layout=layout,
                retry=retry,
                pipeline_id=None,
                sub_pipeline_id=sub_id,
            )
            payload = {"html": html, "validation": validation, "attempts": attempts, "asset_map": asset_map}
            repository.finish_sub_pipeline(self.db, sub_id, status="success", output_payload=payload)
            self._persist_sub_output_html(
                mode="sub",
                sub_pipeline_id=sub_id,
                html_payload=html,
                question_id=layout.question_id,
            )
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
            )
        except Exception as exc:
            self._log(
                mode="sub",
                component="pipeline",
                message=f"Sub-pipeline hata ile sonlandı: layout_to_html ({exc})",
                pipeline_id=None,
                sub_pipeline_id=sub_id,
                level="error",
            )
            repository.finish_sub_pipeline(self.db, sub_id, status="failed", error=str(exc))
            raise
