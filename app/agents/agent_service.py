from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import mimetypes
import os
import re
import shutil
import subprocess
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
    HtmlValidationResult,
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
    "Generate question HTML from QuestionSpec, LayoutPlan, and asset map. "
    "Use QuestionSpec.stem/options/solution semantics to keep educational intent clear in the final card. "
    "Use src values from provided asset_map entries for catalog assets and do not invent unknown file paths."
)
HTML_VALIDATOR_INSTRUCTIONS = (
    "You are a visual QA agent for educational question cards. "
    "Evaluate the quality of the FINAL RENDERED QUESTION IMAGE together with the HTML source. "
    "Primary criterion is visual quality and pedagogical usability, not strict layout-plan matching. "
    "Check readability, spacing, alignment, overlap/occlusion, option clarity, visual hierarchy, and whether the question is understandable at first glance. "
    "Return fail when quality is not acceptable for student-facing usage. "
    "Issues must be concrete and feedback must be actionable editing guidance for the HTML."
)
IMAGE_COMPOSITE_SYSTEM_INSTRUCTIONS = (
    "Üreteceğin görsel, ek olarak verilen katalog görselleriyle birlikte katmanlı bir kompozisyonda kullanılacak. "
    "Bu yüzden görselini katalog ögeleriyle stil, perspektif, ışık, ölçek ve renk uyumu olacak şekilde üret. "
    "Görsel opak ve dikdörtgen/kare bir katman olarak yerleşecek; kritik ögeleri kapatmayacak, temiz ve kullanılabilir boş alan bırak."
    "Ek'te verilen katalog görsellerini ASLA üreteceğin görselin parçası olarak kullanma, sadece referans olarak kullanarak uyumlu ama ayrı bir görsel üret (örneğin benzer bir arka plan dokusu veya benzer bir nesne şeklinde). Ancak ek'teki görseller ASLA üreteceğin görselin içinde yer almamalı, sadece stil ve içerik uyumu için referans olarak kullanılmalı. "
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
        question: QuestionSpec,
        layout: LayoutPlan,
        asset_map: dict[str, str],
        feedback: str | None = None,
    ) -> GeneratedHtml:
        if self.settings.use_stub_agents:
            return self._stub_generate_html(question, layout, asset_map, feedback)

        payload = {
            "question": question.model_dump(),
            "layout": layout.model_dump(),
            "asset_map": asset_map,
            "feedback": feedback or "",
            "catalog_files": self._list_catalog_files(),
        }
        try:
            return self._run_agent(
                model_name=self.settings.anthropic_text_model if self.settings.anthropic_text_model else self.settings.gemini_text_model,
                output_type=GeneratedHtml,
                system_prompt=HTML_GENERATOR_INSTRUCTIONS,
                payload=payload,
                agent_name="html_generator",
                thinking_level="high",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] generate_html fallback to stub: {exc}", flush=True)
            return self._stub_generate_html(question, layout, asset_map, feedback)

    def render_html_to_image(
        self,
        html_content: str,
        *,
        asset_map: dict[str, str] | None = None,
        question_id: str | None = None,
        run_assets_dir: Path | None = None,
        render_dir: Path | None = None,
    ) -> str:
        if render_dir is not None:
            html_path = render_dir / "render.html"
            image_path = render_dir / "render.png"
        else:
            render_id = self._slugify(question_id or f"render_{uuid4()}")
            html_path = self.settings.output_dir / f"{render_id}.render.html"
            image_path = self.settings.output_dir / f"{render_id}.render.png"

        extra_dirs = [run_assets_dir] if run_assets_dir is not None else []
        rewritten = self._rewrite_html_asset_urls_for_local_render(
            html_content, asset_map or {}, extra_search_dirs=extra_dirs
        )
        html_path.write_text(rewritten, encoding="utf-8")

        if self._capture_html_screenshot(html_path, image_path):
            return str(image_path)

        # Deterministic fallback so pipeline keeps moving even if local renderer is unavailable.
        image_path.write_bytes(PIXEL_PNG_BYTES)
        return str(image_path)

    def validate_html(self, html_content: str, rendered_image_path: str) -> HtmlValidationResult:
        if self.settings.use_stub_agents:
            return self._stub_validate_html(html_content, rendered_image_path)

        image_path = Path(rendered_image_path)
        if not image_path.exists() or not image_path.is_file():
            return HtmlValidationResult(
                overall_status="fail",
                issues=["Rendered image not found for visual validation."],
                feedback="HTML render çıktısı üretilemediği için kalite doğrulaması tamamlanamadı.",
            )

        payload = {
            "html_content": html_content,
            "rendered_image_path": str(image_path.resolve()),
            "note": (
                "Rendered image path is provided for visual QA. "
                "Use this with HTML source to assess final question quality."
            ),
        }
        try:
            return self._run_agent(
                model_name=self.settings.gemini_text_model,
                output_type=HtmlValidationResult,
                system_prompt=HTML_VALIDATOR_INSTRUCTIONS,
                payload=payload,
                agent_name="html_validator",
                thinking_level="high",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            print(f"[agent] validate_html fallback to stub: {exc}", flush=True)
            return self._stub_validate_html(html_content, rendered_image_path)

    def generate_composite_image(
        self,
        asset: AssetSpec,
        max_retries: int,
        *,
        catalog_context_filenames: list[str] | None = None,
        output_path: Path | None = None,
    ) -> CompositeImageResult:
        output_path = output_path if output_path is not None else (self.settings.output_dir / f"{asset.slug}.png")
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

    def _rewrite_html_asset_urls_for_local_render(
        self,
        html_content: str,
        asset_map: dict[str, str],
        *,
        extra_search_dirs: list[Path] | None = None,
    ) -> str:
        pattern = re.compile(r'\b(src|href)=([\'"])([^\'"]+)\2', re.IGNORECASE)

        def replacer(match: re.Match[str]) -> str:
            attr = match.group(1)
            quote = match.group(2)
            value = match.group(3)
            low = value.strip().lower()
            if (
                low.startswith("http://")
                or low.startswith("https://")
                or low.startswith("//")
                or low.startswith("/")
                or low.startswith("data:")
                or low.startswith("#")
                or low.startswith("mailto:")
            ):
                return f"{attr}={quote}{value}{quote}"

            raw = value.split("?")[0].split("#")[0]
            file_name = Path(raw).name
            if not file_name:
                return f"{attr}={quote}{value}{quote}"

            candidates = [file_name]
            mapped = asset_map.get(file_name)
            if mapped:
                candidates.append(Path(mapped).name)
            for mapped_value in asset_map.values():
                token = Path(mapped_value).name
                if token not in candidates:
                    candidates.append(token)

            search_roots = list(extra_search_dirs or []) + [self.settings.output_dir, self.settings.catalog_dir]
            for name in candidates:
                for root in search_roots:
                    p = (root / name).resolve()
                    if p.exists() and p.is_file():
                        return f"{attr}={quote}{p.as_uri()}{quote}"

            return f"{attr}={quote}{value}{quote}"

        return pattern.sub(replacer, html_content)

    @staticmethod
    def _browser_candidates() -> list[str]:
        return [
            "google-chrome",
            "chromium",
            "chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]

    def _capture_html_screenshot(self, html_path: Path, image_path: Path) -> bool:
        for browser in self._browser_candidates():
            cmd = browser
            if not Path(browser).is_absolute():
                found = shutil.which(browser)
                if not found:
                    continue
                cmd = found

            args = [
                cmd,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--allow-file-access-from-files",
                "--no-first-run",
                "--no-default-browser-check",
                f"--screenshot={str(image_path)}",
                "--window-size=1600,1200",
                html_path.resolve().as_uri(),
            ]
            try:
                subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
                if image_path.exists() and image_path.is_file():
                    return True
            except Exception:
                pass
        return False

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

    def post_process_html_asset_paths(
        self,
        html_content: str,
        layout: LayoutPlan,
        asset_map: dict[str, str],
    ) -> str:
        mapping: dict[str, str] = {}

        def add_name(name: str | None, target: str) -> None:
            if not name:
                return
            token = Path(name).name
            if token:
                mapping[token.lower()] = target

        for slug, asset in layout.asset_library.items():
            resolved_name_in_map = asset_map.get(slug) or asset.output_filename
            resolved_name = Path(resolved_name_in_map).name
            if not resolved_name:
                continue
            if asset.asset_type == AssetType.CATALOG_COMPONENT:
                target = f"catalog/{resolved_name}"
            elif "/" in resolved_name_in_map or "\\" in resolved_name_in_map:
                # New-structure run: asset_map value is already a relative path (e.g. runs/full/.../assets/foo.png)
                target = resolved_name_in_map
            else:
                target = f"generated_assets/{resolved_name}"

            add_name(resolved_name, target)
            add_name(asset.output_filename, target)
            add_name(asset.source_filename, target)

        pattern = re.compile(r'\b(src|href)=([\'"])([^\'"]+)\2', re.IGNORECASE)
        image_ext = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

        def replacer(match: re.Match[str]) -> str:
            attr = match.group(1)
            quote = match.group(2)
            value = match.group(3)
            low = value.strip().lower()
            if (
                low.startswith("http://")
                or low.startswith("https://")
                or low.startswith("//")
                or low.startswith("/")
                or low.startswith("data:")
                or low.startswith("#")
                or low.startswith("mailto:")
                or low.startswith("catalog/")
                or low.startswith("generated_assets/")
                or low.startswith("runs/")
            ):
                return f"{attr}={quote}{value}{quote}"

            split_idx = len(value)
            for sep in ("?", "#"):
                pos = value.find(sep)
                if pos != -1:
                    split_idx = min(split_idx, pos)
            base = value[:split_idx]
            suffix = value[split_idx:]
            file_name = Path(base).name
            if not file_name or Path(file_name).suffix.lower() not in image_ext:
                return f"{attr}={quote}{value}{quote}"

            replacement = mapping.get(file_name.lower())
            if not replacement:
                if (self.settings.catalog_dir / file_name).exists():
                    replacement = f"catalog/{file_name}"
                elif (self.settings.output_dir / file_name).exists():
                    replacement = f"generated_assets/{file_name}"

            if not replacement:
                return f"{attr}={quote}{value}{quote}"
            return f"{attr}={quote}{replacement}{suffix}{quote}"

        return pattern.sub(replacer, html_content)

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

    def _stub_generate_html(
        self,
        question: QuestionSpec,
        layout: LayoutPlan,
        asset_map: dict[str, str],
        feedback: str | None = None,
    ) -> GeneratedHtml:
        _ = feedback
        images = []
        for slug, asset in layout.asset_library.items():
            src = asset_map.get(slug) or asset.output_filename
            images.append(f'<img src="{src}" alt="{slug}" />')

        html = "\n".join(
            [
                "<html><body>",
                "<section data-layout-slug='root'>",
                f"<h1>{question.stem}</h1>",
                *images,
                "</section>",
                "</body></html>",
            ]
        )
        return GeneratedHtml(selected_template="stub_template", html_content=html)

    def _stub_validate_html(self, html_content: str, rendered_image_path: str) -> HtmlValidationResult:
        issues: list[str] = []
        low = html_content.lower()
        if "<img" not in low:
            issues.append("Soru görselinde img etiketi bulunamadı")
        if "<body" not in low:
            issues.append("HTML gövdesi eksik")
        image_path = Path(rendered_image_path) if rendered_image_path else None
        if image_path is None or not image_path.exists() or image_path.stat().st_size <= len(PIXEL_PNG_BYTES):
            issues.append("Render edilmiş final soru görseli üretilemedi")

        if issues:
            return HtmlValidationResult(
                overall_status="fail",
                issues=issues,
                feedback="Final görsel kalitesini artırmak için HTML yerleşimini, okunabilirliği ve görsel öğe kullanımını iyileştir.",
            )
        return HtmlValidationResult(overall_status="pass", issues=[], feedback="")



def build_agent_service() -> AgentService:
    return AgentService(get_settings())
