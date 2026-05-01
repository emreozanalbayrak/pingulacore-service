import os
from enum import Enum
from functools import lru_cache

from google import genai
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
load_dotenv()


def _get_api_key() -> str:
    """GOOGLE_API_KEY veya GEMINI_API_KEY'den hangisi varsa onu dondurur."""
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""


# ---------------------------------------------------------------------------
# Model rolleri ve registry
# ---------------------------------------------------------------------------

class ModelRole(str, Enum):
    """Pipeline'daki her LLM asamasi icin rol tanimi."""
    QUESTION_GENERATOR = "question_generator"        # LLM-1: Mega soru uretimi (sahne+soru+siklar+cozum)
    BATCH_VALIDATOR = "batch_validator"               # LLM-2: Batch dogrulama
    QUESTION_SOLVER = "question_solver"               # LLM-3: Bagimsiz soru cozumu
    VISUAL_PROMPT_ENGINEER = "visual_prompt"          # LLM-4a: Gorsel prompt muhendisligi
    IMAGE_GENERATOR = "image_generator"               # LLM-4b: Gorsel uretimi (native genai)
    VISUAL_VALIDATOR = "visual_validator"              # LLM-5: Gorsel dogrulama
    VISUAL_QUESTION_SOLVER = "visual_question_solver"  # LLM-6: Gorsel uzerinden bagimsiz cozum


MODEL_REGISTRY: dict[ModelRole, dict] = {
    ModelRole.QUESTION_GENERATOR:       {"model": "gemini-3.1-pro-preview",      "temperature": 0.7},
    ModelRole.BATCH_VALIDATOR:          {"model": "gemini-3-flash-preview",      "temperature": 0.1},
    ModelRole.QUESTION_SOLVER:          {"model": "gemini-3.1-pro-preview",      "temperature": 0.1},
    ModelRole.VISUAL_PROMPT_ENGINEER:   {"model": "gemini-2.5-flash",            "temperature": 0.5},
    ModelRole.IMAGE_GENERATOR:          {"model": "gemini-3-pro-image-preview",  "temperature": 0.7},
    ModelRole.VISUAL_VALIDATOR:         {"model": "gemini-2.5-flash",            "temperature": 0.1},
    ModelRole.VISUAL_QUESTION_SOLVER:   {"model": "gemini-2.5-flash",            "temperature": 0.1},
}


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def get_model(role: ModelRole) -> ChatGoogleGenerativeAI:
    """Belirtilen role gore LangChain ChatGoogleGenerativeAI modeli dondurur.

    NOT: IMAGE_GENERATOR icin bu fonksiyon degil, get_image_client() kullanilmalidir.
    """
    if role == ModelRole.IMAGE_GENERATOR:
        raise ValueError(
            "IMAGE_GENERATOR icin get_model() degil, get_image_client() kullanin."
        )
    config = MODEL_REGISTRY[role]
    return ChatGoogleGenerativeAI(
        model=config["model"],
        temperature=config["temperature"],
        max_tokens=None,
        timeout=None,
        max_retries=2,
        api_key=_get_api_key(),
    )


@lru_cache(maxsize=4)
def get_image_client() -> genai.Client:
    """Gorsel uretim modeli (gemini-3-pro-image-preview) icin native genai client dondurur."""
    return genai.Client(api_key=_get_api_key())


