from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote as url_quote
from uuid import uuid4

from pydantic_ai import Agent, BinaryContent, BinaryImage
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import CachePoint

from app.agents.config import AgentConfig, AgentSettings, get_agent_settings
from app.core.config import Settings, get_settings
from app.services import log_stream_service
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
from app.utils.usage import extract_token_usage, make_usage_event
PIXEL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axw0D0AAAAASUVORK5CYII="
)


class AgentService:
    def __init__(self, settings: Settings | None = None, agent_settings: AgentSettings | None = None):
        self.settings = settings or get_settings()
        self.agent_settings = agent_settings or get_agent_settings()
        self.log_path: Path | None = None
        self.stream_key: str | None = None

    def _emit(self, line: str) -> None:
        """Print a line and mirror it to log_path / stream_key when set."""
        print(line, flush=True)
        if self.log_path is not None:
            try:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:
                pass
        if self.stream_key:
            log_stream_service.publish(self.stream_key, line)

    def _emit_usage_event(self, agent_name: str, model_name: str, result: Any) -> None:
        """Extract and emit usage event from agent result."""
        try:
            usage = extract_token_usage(result)
            event = make_usage_event(
                agent_name=agent_name,
                model_name=model_name,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                cache_write_tokens=usage["cache_write_tokens"],
            )
            event_str = json.dumps(event)
            self._emit(f"[usage] {event_str}")
        except Exception as e:
            self._emit(f"[usage] error capturing usage: {e}")

    def _run_agent(
        self,
        *,
        config: AgentConfig,
        output_type: type[Any],
        payload: Any,
        agent_name: str,
    ) -> Any:
        if isinstance(payload, str):
            user_prompt: Any = payload
        elif isinstance(payload, (list, tuple)):
            user_prompt = payload
        else:
            user_prompt = str(payload)
        models = [config.primary_model]
        if config.on_fail == "fallback" and config.fallback_model:
            models.append(config.fallback_model)

        last_error: Exception | None = None
        self._emit(f'{agent_name} agent, "{config.thinking_level}" düşünme seviyesiyle çalışmaya başladı.')

        for idx, candidate_model in enumerate(models):
            if idx > 0:
                self._emit(f"[agent] fallback model aktif: {candidate_model}")

            for attempt in range(1, config.primary_max_retry + 1):
                agent = Agent(
                    model=candidate_model,
                    model_settings={"thinking": config.thinking_level},
                    output_type=output_type,
                    system_prompt=config.instructions,
                    retries=1,
                )

                def invoke_sync() -> Any:
                    result = agent.run_sync(user_prompt=user_prompt)
                    return result

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
                            result = executor.submit(invoke_sync).result()
                    else:
                        result = invoke_sync()

                    # Capture and emit usage
                    self._emit_usage_event(agent_name, candidate_model, result)
                    return result.output
                except Exception as exc:  # pragma: no cover - live provider instability path
                    last_error = exc
                    status_code = getattr(exc, "status_code", None)
                    retryable = self._is_retryable_model_error(exc, status_code)
                    if retryable and attempt < config.primary_max_retry:
                        sleep_sec = min(1.5 * attempt, 5.0)
                        self._emit(
                            f"[agent] transient model error (model={candidate_model}, attempt={attempt}/{config.primary_max_retry}, "
                            f"status={status_code}) -> retry in {sleep_sec:.1f}s: {exc}"
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

    def generate_question(self, yaml_content: dict[str, Any], feedback: str | None = None) -> QuestionSpec:
        if self.settings.use_stub_agents:
            return self._stub_generate_question(yaml_content, feedback)

        payload = {"yaml": yaml_content, "feedback": feedback or ""}
        try:
            return self._run_agent(
                config=self.agent_settings.generate_question,
                output_type=QuestionSpec,
                payload=payload,
                agent_name="question_generator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] generate_question fallback to stub: {exc}")
            return self._stub_generate_question(yaml_content, feedback)

    def extract_rules(self, yaml_content: dict[str, Any]) -> RuleExtractionResult:
        if self.settings.use_stub_agents:
            return self._stub_extract_rules(yaml_content)

        try:
            return self._run_agent(
                config=self.agent_settings.extract_rules,
                output_type=RuleExtractionResult,
                payload={"yaml": yaml_content},
                agent_name="rule_extractor",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] extract_rules fallback to stub: {exc}")
            return self._stub_extract_rules(yaml_content)

    def evaluate_rule(self, rule: ValidationRule, question: QuestionSpec) -> RuleEvaluation:
        if self.settings.use_stub_agents:
            return self._stub_evaluate_rule(rule, question)

        try:
            return self._run_agent(
                config=self.agent_settings.evaluate_rule,
                output_type=RuleEvaluation,
                payload={"rule": rule.model_dump(), "question": question.model_dump()},
                agent_name="rule_evaluator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] evaluate_rule fallback to stub: {exc}")
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
                config=self.agent_settings.generate_layout,
                output_type=LayoutPlan,
                payload=payload,
                agent_name="layout_generator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] generate_layout fallback to stub: {exc}")
            return self._stub_generate_layout(question, feedback)

    def validate_question_layout(self, question: QuestionSpec, layout: LayoutPlan) -> QuestionLayoutValidationResult:
        if self.settings.use_stub_agents:
            return self._stub_validate_question_layout(question, layout)

        payload = {"question": question.model_dump(), "layout": layout.model_dump()}
        try:
            return self._run_agent(
                config=self.agent_settings.validate_question_layout,
                output_type=QuestionLayoutValidationResult,
                payload=payload,
                agent_name="question_layout_validator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] validate_question_layout fallback to stub: {exc}")
            return self._stub_validate_question_layout(question, layout)

    def generate_html(
        self,
        question: QuestionSpec,
        layout: LayoutPlan,
        asset_map: dict[str, str],
        feedback: str | None = None,
        previous_raw_html: str | None = None,
    ) -> GeneratedHtml:
        if self.settings.use_stub_agents:
            return self._stub_generate_html(
                question,
                layout,
                asset_map,
                feedback,
                previous_raw_html=previous_raw_html,
            )

        safe_question = self.question_payload_for_generate_html(question)
        if previous_raw_html and previous_raw_html.strip():
            payload = [
                json.dumps(
                    {
                        "cached_context": {
                            "instructions": self.agent_settings.generate_html.instructions,
                            "question": safe_question,
                            "layout": layout.model_dump(),
                        }
                    },
                    ensure_ascii=False,
                ),
                CachePoint(ttl="5m"),
                json.dumps(
                    {
                        "input": {
                            "previous_raw_html": previous_raw_html,
                            "feedback": feedback or "",
                        }
                    },
                    ensure_ascii=False,
                ),
            ]
        else:
            payload = {
                "question": safe_question,
                "layout": layout.model_dump(),
                "asset_map": asset_map,
                "feedback": feedback or "",
                "previous_raw_html": "",
                "catalog_files": self._list_catalog_files(),
            }
        try:
            return self._run_agent(
                config=self.agent_settings.generate_html,
                output_type=GeneratedHtml,
                payload=payload,
                agent_name="html_generator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] generate_html fallback to stub: {exc}")
            return self._stub_generate_html(
                question,
                layout,
                asset_map,
                feedback,
                previous_raw_html=previous_raw_html,
            )

    @staticmethod
    def question_payload_for_generate_html(question: QuestionSpec) -> dict[str, Any]:
        """Generate-HTML agent input should never include solution content."""
        return question.model_dump(exclude={"solution"})

    def render_html_to_image(
        self,
        html_content: str,
        *,
        asset_map: dict[str, str] | None = None,
        question_id: str | None = None,
        attempt: int | None = None,
        run_assets_dir: Path | None = None,
        render_dir: Path | None = None,
    ) -> str:
        if render_dir is not None:
            suffix = f"_{max(1, attempt)}" if attempt is not None else ""
            html_path = render_dir / f"render{suffix}.html"
            image_path = render_dir / f"render{suffix}.png"
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

    def validate_html(
        self,
        html_content: str,
        rendered_image_path: str,
        prior_feedback_history: list[dict[str, Any]] | None = None,
    ) -> HtmlValidationResult:
        if self.settings.use_stub_agents:
            return self._stub_validate_html(html_content, rendered_image_path, prior_feedback_history)

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
            "prior_feedback_history": prior_feedback_history or [],
            "note": (
                "Rendered image path is provided for visual QA. "
                "Use this with HTML source to assess final question quality. "
                "When prior_feedback_history is present, shape current feedback considering previous rounds."
            ),
        }
        try:
            return self._run_agent(
                config=self.agent_settings.validate_html,
                output_type=HtmlValidationResult,
                payload=payload,
                agent_name="html_validator",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[agent] validate_html fallback to stub: {exc}")
            return self._stub_validate_html(html_content, rendered_image_path, prior_feedback_history)

    def _run_image_agent(
        self,
        *,
        config: AgentConfig,
        prompt: str,
        agent_name: str,
    ) -> bytes:
        models = [config.primary_model]
        if config.on_fail == "fallback" and config.fallback_model:
            models.append(config.fallback_model)

        last_error: Exception | None = None
        self._emit(f"{agent_name} image agent başladı.")

        for idx, candidate_model in enumerate(models):
            if idx > 0:
                self._emit(f"[image-agent] fallback model aktif: {candidate_model}")

            for attempt in range(1, config.primary_max_retry + 1):
                agent = Agent(
                    model=candidate_model,
                    output_type=BinaryImage,
                    system_prompt=config.instructions,
                )

                def invoke_sync() -> Any:
                    result = agent.run_sync(user_prompt=prompt)
                    return result

                try:
                    loop = asyncio.get_running_loop()
                    running = loop.is_running()
                except RuntimeError:
                    running = False

                try:
                    if running:
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            result = executor.submit(invoke_sync).result()
                    else:
                        result = invoke_sync()

                    # Capture and emit usage
                    self._emit_usage_event(agent_name, candidate_model, result)
                    return result.output.data
                except Exception as exc:  # pragma: no cover - live provider instability path
                    last_error = exc
                    status_code = getattr(exc, "status_code", None)
                    retryable = self._is_retryable_model_error(exc, status_code)
                    if retryable and attempt < config.primary_max_retry:
                        sleep_sec = min(1.0 * attempt, 4.0)
                        self._emit(
                            f"[image-agent] transient error (model={candidate_model}, attempt={attempt}/{config.primary_max_retry}, "
                            f"status={status_code}) -> retry in {sleep_sec:.1f}s: {exc}"
                        )
                        time.sleep(sleep_sec)
                        continue
                    break

        if last_error is not None:
            raise last_error
        raise RuntimeError("Image agent failed without a concrete error.")

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

        if self.settings.use_stub_agents:
            output_path.write_bytes(PIXEL_PNG_BYTES)
            return CompositeImageResult(asset_slug=asset.slug, image_path=str(output_path), note="stub-image")

        prompt = (
            f"Generate PNG for asset={asset.slug}. "
            f"description={asset.description}. "
            f"prompt={asset.prompt}."
        )
        config = self.agent_settings.generate_image
        # Override primary_max_retry with caller-supplied max_retries when provided.
        if max_retries != config.primary_max_retry:
            from dataclasses import replace
            config = replace(config, primary_max_retry=max(1, max_retries))

        try:
            image_bytes = self._run_image_agent(
                config=config,
                prompt=prompt,
                agent_name="image_generator",
            )
            output_path.write_bytes(image_bytes)
            return CompositeImageResult(
                asset_slug=asset.slug,
                image_path=str(output_path),
                note=f"generated-by-pydantic-agent({config.primary_model})",
            )
        except Exception as exc:  # pragma: no cover - live provider instability path
            self._emit(f"[image-agent] failed, using stub: {exc}")
            output_path.write_bytes(PIXEL_PNG_BYTES)
            return CompositeImageResult(
                asset_slug=asset.slug,
                image_path=str(output_path),
                note=f"fallback-stub-image(error={exc})",
            )

    def _rewrite_html_asset_urls_for_local_render(
        self,
        html_content: str,
        asset_map: dict[str, str],
        *,
        extra_search_dirs: list[Path] | None = None,
    ) -> str:
        attr_pattern = re.compile(r'\b(src|href)=([\'"])([^\'"]+)\2', re.IGNORECASE)
        css_url_pattern = re.compile(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)', re.IGNORECASE)

        def resolve_local_uri(value: str) -> str | None:
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
                return None

            split_idx = len(value)
            for sep in ("?", "#"):
                pos = value.find(sep)
                if pos != -1:
                    split_idx = min(split_idx, pos)
            base = value[:split_idx].replace("\\", "/").strip()
            suffix = value[split_idx:]
            if not base:
                return None

            runs_match = re.search(r"(?:^|/)(runs/.+)$", base, flags=re.IGNORECASE)
            if runs_match:
                runs_path = runs_match.group(1).strip("/")
                runs_root = self.settings.runs_dir.parent.resolve()
                candidate = (runs_root / runs_path).resolve()
                if (candidate == runs_root or runs_root in candidate.parents) and candidate.exists() and candidate.is_file():
                    return f"{candidate.as_uri()}{suffix}"

            file_name = Path(base).name
            if not file_name:
                return None

            candidates = [file_name]
            for key in (file_name, base):
                mapped = asset_map.get(key)
                if mapped:
                    token = Path(str(mapped)).name
                    if token and token not in candidates:
                        candidates.append(token)

            for mapped_value in asset_map.values():
                token = Path(str(mapped_value)).name
                if token and token not in candidates:
                    candidates.append(token)

            search_roots = list(extra_search_dirs or []) + [self.settings.output_dir, self.settings.catalog_dir]
            for name in candidates:
                for root in search_roots:
                    p = (root / name).resolve()
                    if p.exists() and p.is_file():
                        return f"{p.as_uri()}{suffix}"
            return None

        def attr_replacer(match: re.Match[str]) -> str:
            attr = match.group(1)
            quote_char = match.group(2)
            value = match.group(3)
            resolved = resolve_local_uri(value)
            if not resolved:
                return f"{attr}={quote_char}{value}{quote_char}"
            return f"{attr}={quote_char}{resolved}{quote_char}"

        def css_url_replacer(match: re.Match[str]) -> str:
            quote_char = match.group(1)
            value = match.group(2).strip()
            resolved = resolve_local_uri(value)
            if not resolved:
                return f"url({quote_char}{value}{quote_char})"
            return f"url({quote_char}{resolved}{quote_char})"

        rewritten = attr_pattern.sub(attr_replacer, html_content)
        return css_url_pattern.sub(css_url_replacer, rewritten)

    @staticmethod
    def normalize_html_asset_urls_for_server(html_content: str) -> str:
        """
        Normalize relative asset refs for server-side delivery via /v1/assets.
        - runs/... refs keep their full relative path: /v1/assets/runs/...
        - other relative refs are flattened to filename: /v1/assets/<file>
        """
        attr_pattern = re.compile(r'\b(src|href)=([\'"])([^\'"]+)\2', re.IGNORECASE)
        css_url_pattern = re.compile(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)', re.IGNORECASE)

        def to_server_asset_url(value: str) -> str | None:
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
                return None

            split_idx = len(value)
            for sep in ("?", "#"):
                pos = value.find(sep)
                if pos != -1:
                    split_idx = min(split_idx, pos)
            base = value[:split_idx].replace("\\", "/").strip()
            suffix = value[split_idx:]
            if not base:
                return None

            runs_match = re.search(r"(?:^|/)(runs/.+)$", base, flags=re.IGNORECASE)
            if runs_match:
                runs_path = runs_match.group(1).strip("/")
                encoded_runs = "/".join(url_quote(item, safe="") for item in runs_path.split("/"))
                return f"/v1/assets/{encoded_runs}{suffix}"

            file_name = Path(base).name
            if not file_name:
                return None
            return f"/v1/assets/{url_quote(file_name, safe='')}{suffix}"

        def attr_replacer(match: re.Match[str]) -> str:
            attr = match.group(1)
            quote_char = match.group(2)
            value = match.group(3)
            replaced = to_server_asset_url(value)
            if not replaced:
                return f"{attr}={quote_char}{value}{quote_char}"
            return f"{attr}={quote_char}{replaced}{quote_char}"

        def css_url_replacer(match: re.Match[str]) -> str:
            quote_char = match.group(1)
            value = match.group(2).strip()
            replaced = to_server_asset_url(value)
            if not replaced:
                return f"url({quote_char}{value}{quote_char})"
            return f"url({quote_char}{replaced}{quote_char})"

        rewritten = attr_pattern.sub(attr_replacer, html_content)
        return css_url_pattern.sub(css_url_replacer, rewritten)

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
        previous_raw_html: str | None = None,
    ) -> GeneratedHtml:
        _ = feedback
        _ = previous_raw_html
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

    def _stub_validate_html(
        self,
        html_content: str,
        rendered_image_path: str,
        prior_feedback_history: list[dict[str, Any]] | None = None,
    ) -> HtmlValidationResult:
        _ = prior_feedback_history
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
