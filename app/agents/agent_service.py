from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from app.core.config import Settings, get_settings
from app.schemas.domain import (
    AssetSpec,
    AssetType,
    CompositeImageResult,
    EntitySpec,
    GeneratedHtml,
    LayoutHtmlValidationResult,
    LayoutPlan,
    QuestionLayoutValidationResult,
    QuestionOptionSpec,
    QuestionScenarioSpec,
    QuestionSceneSpec,
    QuestionSpec,
    RuleEvaluation,
    RuleEvaluationSet,
    RuleExtractionResult,
    ValidationRule,
)
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings



try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None


PIXEL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axw0D0AAAAASUVORK5CYII="
)

QUESTION_AGENT_INSTRUCTIONS = (
    "You generate only QuestionSpec from curriculum YAML. "
    "Do not produce layout, coordinates, HTML, or render instructions. "
    "Use scenario.scenes as a list. "
    "Do not use a singular scene field."
)

RULE_EXTRACTOR_INSTRUCTIONS = (
    "Extract atomically testable validation rules from the YAML input. "
    "Prioritize only the most critical constraints for generation quality and correctness. "
    "Merge overlapping or near-duplicate rules into a single concise rule when possible. "
    "Return at most 12 rules."
)
RULE_EVALUATOR_INSTRUCTIONS = "Evaluate one rule against a QuestionSpec and return pass/partial/fail."
LAYOUT_PLANNER_INSTRUCTIONS = (
    "Generate a LayoutPlan from QuestionSpec. "
    "QuestionSpec.scenario.scenes may include multiple scene items; each enabled scene should map to a background asset. "
    "AI-generated assets are opaque and rectangular/square (not transparent), so place them carefully to avoid hiding critical objects. "
    "Catalog assets are transparent and can be layered above AI assets. "
    "Use binding layer and z_index so critical foreground objects remain visible. "
    "Use catalog components from the provided catalog_files list. "
    "For catalog_component assets, source_filename must be one of catalog_files and transparent_background should be true."
)
LAYOUT_VALIDATOR_INSTRUCTIONS = (
    "Validate consistency between QuestionSpec and LayoutPlan. "
    "Check multi-scene coverage and ensure opaque AI assets do not hide critical foreground elements."
)
HTML_GENERATOR_INSTRUCTIONS = (
    "Generate question HTML from LayoutPlan and asset map. "
    "Use src values from provided asset_map entries for catalog assets and do not invent unknown file paths."
)
HTML_VALIDATOR_INSTRUCTIONS = "Validate consistency between LayoutPlan and HTML."
IMAGE_COMPOSITE_SYSTEM_INSTRUCTIONS = (
    "Üreteceğin görsel, ek olarak verilen katalog görselleriyle birlikte katmanlı bir kompozisyonda kullanılacak. "
    "Bu yüzden görselini katalog ögeleriyle stil, perspektif, ışık, ölçek ve renk uyumu olacak şekilde üret. "
    "Görsel opak ve dikdörtgen/kare bir katman olarak yerleşecek; kritik ögeleri kapatmayacak, temiz ve kullanılabilir boş alan bırak."
)


class AgentService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _run_agent(
        self,
        *,
        model_name: str,
        output_type: type[Any],
        system_prompt: str,
        payload: Any,
        agent_name: str,
        thinking_level: str = "medium",
    ) -> Any:
        payload_text = str(payload)
        models = self._candidate_models(model_name)
        attempts_per_model = 5
        last_error: Exception | None = None
        print(
            f'{agent_name} agent, "{thinking_level}" düşünme seviyesiyle çalışmaya başladı.',
            flush=True,
        )

        for idx, candidate_model in enumerate(models):
            if idx > 0:
                print(f"[agent] fallback model aktif: {candidate_model}", flush=True)

            for attempt in range(1, attempts_per_model + 1):
                #if candidate_model.startswith("google-gla:"):

                agent = Agent(
                    model=candidate_model,
                    model_settings={"thinking": thinking_level},
                    output_type=output_type,
                    system_prompt=system_prompt,
                    retries=1,
                )

                def invoke_sync() -> Any:
                    result = agent.run_sync(user_prompt=payload_text)
                    return result.output

                # When called from async request contexts, run_sync may conflict with
                # the active loop. In that case execute it in a dedicated worker thread.
                try:
                    loop = asyncio.get_running_loop()
                    running = loop.is_running()
                except RuntimeError:
                    running = False

                try:
                    if running:
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            return executor.submit(invoke_sync).result()
                    return invoke_sync()
                except Exception as exc:  # pragma: no cover - live provider instability path
                    last_error = exc
                    status_code = getattr(exc, "status_code", None)
                    retryable = self._is_retryable_model_error(exc, status_code)
                    if retryable and attempt < attempts_per_model:
                        sleep_sec = min(1.5 * attempt, 5.0)
                        print(
                            f"[agent] transient model error (model={candidate_model}, attempt={attempt}/{attempts_per_model}, "
                            f"status={status_code}) -> retry in {sleep_sec:.1f}s: {exc}",
                            flush=True,
                        )
                        time.sleep(sleep_sec)
                        continue
                    break

        if last_error is not None:
            raise last_error
        raise RuntimeError("Agent run failed without a concrete error.")

    @staticmethod
    def _is_retryable_model_error(exc: Exception, status_code: Any) -> bool:
        if isinstance(exc, ModelHTTPError):
            return exc.status_code in {429, 500, 502, 503, 504}
        if isinstance(status_code, int):
            return status_code in {429, 500, 502, 503, 504}
        message = str(exc).lower()
        return "unavailable" in message or "timeout" in message or "rate limit" in message

    def _candidate_models(self, primary_model: str) -> list[str]:
        models = [primary_model]
        # Prefer same-provider fallback between configured text/light models.
        light_model = (self.settings.gemini_light_model or "").strip()
        text_model = (self.settings.gemini_text_model or "").strip()
        if light_model and light_model != primary_model:
            models.append(light_model)
        if text_model and text_model != primary_model:
            models.append(text_model)

        configured_fallback = (os.getenv("AI_TEXT_FALLBACK_MODEL") or "").strip()
        if configured_fallback and configured_fallback != primary_model:
            models.append(configured_fallback)

        # Remove duplicates while preserving order.
        deduped: list[str] = []
        for item in models:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def generate_question(self, yaml_content: dict[str, Any], feedback: str | None = None) -> QuestionSpec:
        if self.settings.use_stub_agents:
            return self._stub_generate_question(yaml_content, feedback)

        payload = {"yaml": yaml_content, "feedback": feedback or ""}
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=QuestionSpec,
                system_prompt=QUESTION_AGENT_INSTRUCTIONS,
                payload=payload,
                agent_name="question_generator",
                thinking_level="high",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] generate_question fallback to stub: {exc}", flush=True)
            return self._stub_generate_question(yaml_content, feedback)

    def extract_rules(self, yaml_content: dict[str, Any]) -> RuleExtractionResult:
        if self.settings.use_stub_agents:
            return self._stub_extract_rules(yaml_content)

        try:
            return self._run_agent(
                model_name=self.settings.gemini_light_model,
                output_type=RuleExtractionResult,
                system_prompt=RULE_EXTRACTOR_INSTRUCTIONS,
                payload={"yaml": yaml_content},
                agent_name="rule_extractor",
                thinking_level="medium",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] extract_rules fallback to stub: {exc}", flush=True)
            return self._stub_extract_rules(yaml_content)

    def evaluate_rule(self, rule: ValidationRule, question: QuestionSpec) -> RuleEvaluation:
        if self.settings.use_stub_agents:
            return self._stub_evaluate_rule(rule, question)

        try:
            return self._run_agent(
                model_name=self.settings.gemini_light_model,
                output_type=RuleEvaluation,
                system_prompt=RULE_EVALUATOR_INSTRUCTIONS,
                payload={"rule": rule.model_dump(), "question": question.model_dump()},
                agent_name="rule_evaluator",
                thinking_level="low",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] evaluate_rule fallback to stub: {exc}", flush=True)
            return self._stub_evaluate_rule(rule, question)

    async def evaluate_rules_parallel(
        self,
        rules: list[ValidationRule],
        question: QuestionSpec,
        parallelism: int,
        on_progress: Callable[[int, int, RuleEvaluation], None] | None = None,
    ) -> RuleEvaluationSet:
        sem = asyncio.Semaphore(max(1, parallelism))

        async def worker(rule: ValidationRule) -> RuleEvaluation:
            async with sem:
                return await asyncio.to_thread(self.evaluate_rule, rule, question)

        tasks = [asyncio.create_task(worker(rule)) for rule in rules]
        total = len(tasks)
        completed = 0
        items: list[RuleEvaluation] = []

        for task in asyncio.as_completed(tasks):
            item = await task
            completed += 1
            if on_progress is not None:
                on_progress(completed, total, item)
            items.append(item)

        items.sort(key=lambda x: x.rule_id)
        return RuleEvaluationSet(items=items)

    def generate_layout(self, question: QuestionSpec, feedback: str | None = None) -> LayoutPlan:
        if self.settings.use_stub_agents:
            return self._stub_generate_layout(question, feedback)

        payload = {
            "question": question.model_dump(),
            "feedback": feedback or "",
            "catalog_files": self._list_catalog_files(),
        }
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=LayoutPlan,
                system_prompt=LAYOUT_PLANNER_INSTRUCTIONS,
                payload=payload,
                agent_name="layout_generator",
                thinking_level="high",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] generate_layout fallback to stub: {exc}", flush=True)
            return self._stub_generate_layout(question, feedback)

    def validate_question_layout(self, question: QuestionSpec, layout: LayoutPlan) -> QuestionLayoutValidationResult:
        if self.settings.use_stub_agents:
            return self._stub_validate_question_layout(question, layout)

        payload = {"question": question.model_dump(), "layout": layout.model_dump()}
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=QuestionLayoutValidationResult,
                system_prompt=LAYOUT_VALIDATOR_INSTRUCTIONS,
                payload=payload,
                agent_name="question_layout_validator",
                thinking_level="medium",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] validate_question_layout fallback to stub: {exc}", flush=True)
            return self._stub_validate_question_layout(question, layout)

    def generate_html(
        self,
        layout: LayoutPlan,
        asset_map: dict[str, str],
        feedback: str | None = None,
    ) -> GeneratedHtml:
        if self.settings.use_stub_agents:
            return self._stub_generate_html(layout, asset_map, feedback)

        payload = {
            "layout": layout.model_dump(),
            "asset_map": asset_map,
            "feedback": feedback or "",
            "catalog_files": self._list_catalog_files(),
        }
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=GeneratedHtml,
                system_prompt=HTML_GENERATOR_INSTRUCTIONS,
                payload=payload,
                agent_name="html_generator",
                thinking_level="high",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] generate_html fallback to stub: {exc}", flush=True)
            return self._stub_generate_html(layout, asset_map, feedback)

    def validate_layout_html(self, layout: LayoutPlan, html_content: str) -> LayoutHtmlValidationResult:
        if self.settings.use_stub_agents:
            return self._stub_validate_layout_html(layout, html_content)

        payload = {"layout": layout.model_dump(), "html_content": html_content}
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=LayoutHtmlValidationResult,
                system_prompt=HTML_VALIDATOR_INSTRUCTIONS,
                payload=payload,
                agent_name="layout_html_validator",
                thinking_level="medium",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] validate_layout_html fallback to stub: {exc}", flush=True)
            return self._stub_validate_layout_html(layout, html_content)

    def generate_composite_image(
        self,
        asset: AssetSpec,
        max_retries: int,
        *,
        catalog_context_filenames: list[str] | None = None,
    ) -> CompositeImageResult:
        output_path = self.settings.output_dir / f"{asset.slug}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.settings.use_stub_agents or genai is None:
            output_path.write_bytes(PIXEL_PNG_BYTES)
            return CompositeImageResult(asset_slug=asset.slug, image_path=str(output_path), note="stub-image")

        api_key = self._google_api_key()
        if not api_key:
            output_path.write_bytes(PIXEL_PNG_BYTES)
            return CompositeImageResult(asset_slug=asset.slug, image_path=str(output_path), note="fallback-stub-image(no-key)")

        client = genai.Client(api_key=api_key)
        prompt = (
            f"Generate PNG for asset={asset.slug}. "
            f"description={asset.description}. "
            f"prompt={asset.prompt}. "
            "This image will be layered with provided catalog PNG assets in the final composition."
        )
        context_parts, used_catalog_files = self._build_catalog_context_parts(catalog_context_filenames or [])
        request_parts: list[Any] = [prompt, *context_parts]
        image_models = self._candidate_image_models(self.settings.gemini_image_model)
        last_error: str | None = None

        for image_model in image_models:
            for attempt in range(1, max(1, max_retries) + 1):
                try:
                    response = client.models.generate_content(
                        model=image_model,
                        contents=request_parts,
                        config={
                            "systemInstruction": IMAGE_COMPOSITE_SYSTEM_INSTRUCTIONS,
                        },
                    )
                except Exception as exc:  # pragma: no cover - live provider instability path
                    last_error = str(exc)
                    sleep_sec = min(1.0 * attempt, 4.0)
                    print(
                        f"[image-agent] model error (model={image_model}, attempt={attempt}) -> {exc}",
                        flush=True,
                    )
                    time.sleep(sleep_sec)
                    continue

                image_bytes = self._extract_image_bytes(response)
                if image_bytes is not None:
                    output_path.write_bytes(image_bytes)
                    return CompositeImageResult(
                        asset_slug=asset.slug,
                        image_path=str(output_path),
                        note=f"generated-by-image-model({image_model});catalog_refs={len(used_catalog_files)}",
                    )

        output_path.write_bytes(PIXEL_PNG_BYTES)
        if last_error:
            return CompositeImageResult(
                asset_slug=asset.slug,
                image_path=str(output_path),
                note=f"fallback-stub-image(error={last_error})",
            )
        return CompositeImageResult(asset_slug=asset.slug, image_path=str(output_path), note="fallback-stub-image(no-image-part)")

    def _build_catalog_context_parts(self, catalog_filenames: list[str]) -> tuple[list[Any], list[str]]:
        parts: list[Any] = []
        used: list[str] = []
        if genai is None:
            return parts, used

        safe_names: list[str] = []
        for name in catalog_filenames:
            token = Path(name).name
            if not token or token.startswith("."):
                continue
            if token not in safe_names:
                safe_names.append(token)

        for filename in safe_names:
            path = self.settings.catalog_dir / filename
            if not path.exists() or not path.is_file():
                continue
            mime, _ = mimetypes.guess_type(path.name)
            if not mime or not mime.startswith("image/"):
                continue
            try:
                data = path.read_bytes()
            except Exception:
                continue
            if not data:
                continue
            parts.append(genai.types.Part.from_bytes(data=data, mime_type=mime))
            used.append(filename)

        return parts, used

    @staticmethod
    def _candidate_image_models(primary_model: str) -> list[str]:
        # Keep configurable primary model first, then try known compatibility fallbacks.
        models = [
            primary_model,
            "gemini-2.5-flash-image",
        ]
        deduped: list[str] = []
        for item in models:
            token = (item or "").strip()
            if token and token not in deduped:
                deduped.append(token)
        return deduped

    @staticmethod
    def _google_api_key() -> str:
        import os

        return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""

    @staticmethod
    def _extract_image_bytes(response: Any) -> bytes | None:
        parts = getattr(response, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, bytes):
                    return data
                if isinstance(data, str):
                    try:
                        return base64.b64decode(data)
                    except Exception:
                        pass

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            cparts = getattr(content, "parts", None) or []
            for part in cparts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    if isinstance(data, bytes):
                        return data
                    if isinstance(data, str):
                        try:
                            return base64.b64decode(data)
                        except Exception:
                            pass
        return None

    @staticmethod
    def _slugify(value: str) -> str:
        token = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
        return token.strip("_") or "asset"

    def _list_catalog_files(self) -> list[str]:
        folder = self.settings.catalog_dir
        if not folder.exists() or not folder.is_dir():
            return []
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
        return sorted(
            path.name
            for path in folder.iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in allowed
        )

    @staticmethod
    def _map_difficulty(value: str | None) -> Literal["easy", "medium", "hard"]:
        token = (value or "").strip().lower()
        if token in {"easy", "kolay"}:
            return "easy"
        if token in {"hard", "zor"}:
            return "hard"
        return "medium"

    def _stub_generate_question(self, yaml_content: dict[str, Any], feedback: str | None = None) -> QuestionSpec:
        meta = yaml_content.get("meta", {})
        context = yaml_content.get("context", {})
        fmt = yaml_content.get("format", {})
        options_cfg = fmt.get("options", {})
        labels = options_cfg.get("labels", ["A", "B", "C"])
        option_style = str(options_cfg.get("style", "text_only")).lower()
        has_visual = any(token in option_style for token in ["visual", "image"])

        grade_raw = int(meta.get("sinif_seviyesi", 2) or 2)
        grade = min(max(grade_raw, 1), 8)

        stem = "Doğru cevabı seçiniz."
        questions = context.get("questions", [])
        if questions and isinstance(questions[0], dict):
            stems = questions[0].get("soru_kokleri", [])
            if stems:
                stem = str(stems[0])

        scenario_scenes: list[QuestionSceneSpec] = []
        gorsel = yaml_content.get("gorsel", {})
        if isinstance(gorsel, dict):
            if gorsel.get("ana_gorsel"):
                scenario_scenes.append(
                    QuestionSceneSpec(
                        enabled=True,
                        description_prompt=(
                            "Primary school friendly soft illustration background, with ample empty space "
                            "for foreground entities and options."
                        ),
                        color_scheme="pastel",
                    )
                )

            raw_scenes = gorsel.get("sahneler") or gorsel.get("scenes") or []
            if isinstance(raw_scenes, list):
                for idx, item in enumerate(raw_scenes, start=1):
                    if not isinstance(item, dict):
                        continue
                    prompt = str(item.get("description_prompt") or item.get("prompt") or "").strip()
                    if not prompt:
                        prompt = f"Scene {idx}: classroom-compatible background with safe empty foreground space."
                    scenario_scenes.append(
                        QuestionSceneSpec(
                            enabled=bool(item.get("enabled", True)),
                            description_prompt=prompt,
                            color_scheme=str(item.get("color_scheme") or "pastel"),
                        )
                    )

        if has_visual and not scenario_scenes:
            scenario_scenes.append(
                QuestionSceneSpec(
                    enabled=True,
                    description_prompt=(
                        "Simple educational background with generous empty space for foreground transparent catalog assets."
                    ),
                    color_scheme="pastel",
                )
            )

        scenario = QuestionScenarioSpec(
            entities=[EntitySpec(name="object", description="countable object", quantity=3)],
            scenes=scenario_scenes,
            characters=[],
            story=f"{context.get('type', 'genel')} bağlamında kısa hikaye.",
        )

        options: list[QuestionOptionSpec] = []
        for i, label in enumerate(labels):
            is_correct = i == 0
            if has_visual and i == 1:
                options.append(
                    QuestionOptionSpec(
                        label=str(label),
                        modality="visual",
                        is_correct=is_correct,
                        content=[EntitySpec(name="object", description="option entity", quantity=10 + i)],
                    )
                )
            else:
                options.append(
                    QuestionOptionSpec(
                        label=str(label),
                        modality="text",
                        is_correct=is_correct,
                        content=str(10 + i),
                    )
                )

        if feedback:
            stem = f"{stem}"

        return QuestionSpec(
            question_id=str(meta.get("id") or uuid4()),
            scenario=scenario,
            options=options,
            solution=["Stub çözüm: doğru seçenek ilk seçenek."],
            stem=stem,
            grade=grade,
            difficulty=self._map_difficulty(meta.get("difficulty")),
        )

    def _stub_extract_rules(self, yaml_content: dict[str, Any]) -> RuleExtractionResult:
        generation = ((yaml_content.get("context") or {}).get("generation") or {})
        rules_raw = generation.get("kurallar") or []
        items: list[ValidationRule] = []
        for i, text in enumerate(rules_raw[:12], start=1):
            items.append(
                ValidationRule(
                    id=f"R{i:02d}",
                    category="content",
                    text=str(text),
                    source_path=f"context.generation.kurallar[{i-1}]",
                )
            )

        if not items:
            items = [
                ValidationRule(
                    id="R01",
                    category="format",
                    text="Şık sayısı 3 olmalı.",
                    source_path="format.options.count",
                )
            ]
        return RuleExtractionResult(items=items)

    def _stub_evaluate_rule(self, rule: ValidationRule, question: QuestionSpec) -> RuleEvaluation:
        status: str = "pass"
        rationale = "Kural sağlandı."

        text_low = rule.text.lower()
        if "3" in text_low and "şık" in text_low and len(question.options) != 3:
            status = "fail"
            rationale = "Şık sayısı 3 değil."
        elif "tek" in text_low and "doğru" in text_low:
            if sum(1 for opt in question.options if opt.is_correct) != 1:
                status = "fail"
                rationale = "Tek doğru seçenek kuralı sağlanmıyor."

        correct_labels = [o.label for o in question.options if o.is_correct]
        return RuleEvaluation(
            rule_id=rule.id,
            category=rule.category,
            rule_text=rule.text,
            status=status,
            rationale=rationale,
            confidence=0.95 if status == "pass" else 0.75,
            evidence=f"options={len(question.options)}, correct_labels={correct_labels}",
        )

    def _stub_generate_layout(self, question: QuestionSpec, feedback: str | None = None) -> LayoutPlan:
        _ = feedback
        asset_library: dict[str, AssetSpec] = {}
        root_children: list[dict[str, Any]] = []

        enabled_scenes = [scene for scene in (question.scenario.scenes or []) if scene.enabled]
        if enabled_scenes:
            scene_bindings: list[dict[str, Any]] = []
            total = len(enabled_scenes)
            panel_width = 100.0 / total
            for idx, scene in enumerate(enabled_scenes, start=1):
                scene_slug = "scenario_scene" if total == 1 else f"scenario_scene_{idx}"
                asset_library[scene_slug] = AssetSpec(
                    slug=scene_slug,
                    asset_type=AssetType.GENERATED_COMPOSITE,
                    description=f"Scenario background scene {idx}",
                    prompt=scene.description_prompt,
                    output_filename=f"{scene_slug}.png",
                    kind="background",
                    transparent_background=False,
                    render_shape="rectangle",
                )
                scene_bindings.append(
                    {
                        "asset_slug": scene_slug,
                        "repeat": 1,
                        "placement_hint": f"scene_panel_{idx}",
                        "layer": "background",
                        "z_index": 0,
                        "must_remain_visible": False,
                        "allow_occlusion": True,
                        "frame": {
                            "x_pct": (idx - 1) * panel_width,
                            "y_pct": 0,
                            "width_pct": panel_width,
                            "height_pct": 100,
                        },
                    }
                )

            root_children.append(
                {
                    "slug": "scenes",
                    "node_type": "scenes",
                    "bindings": scene_bindings,
                    "children": [],
                }
            )

        option_bindings: list[dict[str, Any]] = []
        for option in question.options:
            if option.modality == "visual":
                slug = f"option_{self._slugify(option.label)}"
                entities = option.content if isinstance(option.content, list) else []
                entity_text = ", ".join([f"{e.quantity}x {e.name}" for e in entities])
                asset_library[slug] = AssetSpec(
                    slug=slug,
                    asset_type=AssetType.GENERATED_COMPOSITE,
                    description=f"Visual option {option.label}",
                    prompt=f"Generate visual option with entities: {entity_text}",
                    output_filename=f"{slug}.png",
                    kind="option_visual",
                    transparent_background=False,
                    render_shape="rectangle",
                )
                option_bindings.append(
                    {
                        "asset_slug": slug,
                        "repeat": 1,
                        "placement_hint": f"option_{option.label}",
                        "layer": "content",
                        "z_index": 20,
                        "must_remain_visible": False,
                        "allow_occlusion": True,
                    }
                )

        root_children.append(
            {
                "slug": "options",
                "node_type": "options",
                "bindings": option_bindings,
                "children": [],
            }
        )

        if not asset_library:
            fallback_slug = "decorative_marker"
            asset_library[fallback_slug] = AssetSpec(
                slug=fallback_slug,
                asset_type=AssetType.CATALOG_COMPONENT,
                description="Fallback marker",
                source_filename="yildiz.png",
                output_filename="decorative_marker.png",
                kind="object",
                transparent_background=True,
                render_shape="free",
            )
            root_children.append(
                {
                    "slug": "critical_markers",
                    "node_type": "foreground",
                    "bindings": [
                        {
                            "asset_slug": fallback_slug,
                            "repeat": 1,
                            "placement_hint": "fallback_marker",
                            "layer": "foreground",
                            "z_index": 50,
                            "must_remain_visible": True,
                            "allow_occlusion": False,
                        }
                    ],
                    "children": [],
                }
            )

        html_layout = {
            "slug": "root",
            "node_type": "container",
            "bindings": [],
            "children": root_children,
        }

        return LayoutPlan(
            question_id=question.question_id,
            asset_library=asset_library,
            html_layout=html_layout,
        )

    def _stub_validate_question_layout(self, question: QuestionSpec, layout: LayoutPlan) -> QuestionLayoutValidationResult:
        issues: list[str] = []

        if layout.question_id and layout.question_id != question.question_id:
            issues.append("layout.question_id ile question.question_id eşleşmiyor")

        visual_labels = [opt.label for opt in question.options if opt.modality == "visual"]
        bindings: list[str] = []

        def walk(node) -> None:
            for binding in node.bindings:
                bindings.append(binding.placement_hint.lower())
            for child in node.children:
                walk(child)

        walk(layout.html_layout)

        for label in visual_labels:
            expected = f"option_{label.lower()}"
            if not any(expected in hint for hint in bindings):
                issues.append(f"Visual option için binding yok: {label}")

        enabled_scene_count = len([scene for scene in (question.scenario.scenes or []) if scene.enabled])
        if enabled_scene_count > 0:
            background_assets = [asset for asset in layout.asset_library.values() if asset.kind in {"background", "scene"}]
            if len(background_assets) < enabled_scene_count:
                issues.append(
                    f"enabled scene sayısı {enabled_scene_count}, background asset sayısı {len(background_assets)}"
                )

        opaque_ai_max_z: int | None = None
        critical_min_z: int | None = None

        def walk_binding_stats(node) -> None:
            nonlocal opaque_ai_max_z, critical_min_z
            for binding in node.bindings:
                asset = layout.asset_library.get(binding.asset_slug)
                if asset and asset.asset_type == AssetType.GENERATED_COMPOSITE and not asset.transparent_background:
                    opaque_ai_max_z = binding.z_index if opaque_ai_max_z is None else max(opaque_ai_max_z, binding.z_index)
                if binding.must_remain_visible:
                    critical_min_z = binding.z_index if critical_min_z is None else min(critical_min_z, binding.z_index)
            for child in node.children:
                walk_binding_stats(child)

        walk_binding_stats(layout.html_layout)
        if opaque_ai_max_z is not None and critical_min_z is not None and opaque_ai_max_z >= critical_min_z:
            issues.append("Kritik ögeler, opak AI assetlerden daha üst katmanda (z-index) olmalı")

        if issues:
            return QuestionLayoutValidationResult(
                overall_status="fail",
                issues=issues,
                feedback=(
                    "Layout plan, QuestionSpec scenes ve visual ihtiyaçlarını karşılamalı. "
                    "Opak AI assetler kritik ögeleri kapatmayacak şekilde katmanlanmalı."
                ),
            )
        return QuestionLayoutValidationResult(overall_status="pass", issues=[], feedback="")

    def _stub_generate_html(self, layout: LayoutPlan, asset_map: dict[str, str], feedback: str | None = None) -> GeneratedHtml:
        _ = feedback
        images = []
        for slug, asset in layout.asset_library.items():
            src = asset_map.get(slug) or asset.output_filename
            images.append(f'<img src="{src}" alt="{slug}" />')

        html = "\n".join(
            [
                "<html><body>",
                "<section data-layout-slug='root'>",
                *images,
                "</section>",
                "</body></html>",
            ]
        )
        return GeneratedHtml(selected_template="stub_template", html_content=html)

    def _stub_validate_layout_html(self, layout: LayoutPlan, html_content: str) -> LayoutHtmlValidationResult:
        missing = []
        low = html_content.lower()
        for asset in layout.asset_library.values():
            if asset.output_filename.lower() not in low and asset.slug.lower() not in low:
                missing.append(asset.output_filename)

        if missing:
            return LayoutHtmlValidationResult(
                overall_status="fail",
                issues=[f"Eksik asset referansı: {name}" for name in missing],
                feedback="Tüm asset dosyaları HTML içinde görünmeli.",
            )
        return LayoutHtmlValidationResult(overall_status="pass", issues=[], feedback="")



def build_agent_service() -> AgentService:
    return AgentService(get_settings())
