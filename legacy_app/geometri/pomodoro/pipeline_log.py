"""Basit pipeline log yardimcisi — adim ilerlemesini anlik yazdirir."""


def pipeline_log(tag: str, message: str) -> None:
    print(f"[{tag}] {message}", flush=True)
