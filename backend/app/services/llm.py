"""Client for LM Studio's native chat endpoint (POST /api/v1/chat)."""
from __future__ import annotations

import json
import re

import httpx
from json_repair import repair_json

from app.config import get_settings


class LLMError(RuntimeError):
    pass


def extract_message(payload: dict) -> str:
    """Return only the final `message` text. `reasoning` items are never shown or stored."""
    output = payload.get("output")
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        parts = [
            item["content"]
            for item in output
            if isinstance(item, dict) and item.get("type") == "message" and isinstance(item.get("content"), str)
        ]
        if parts:
            return "\n".join(parts).strip()
        if any(isinstance(i, dict) and i.get("type") == "reasoning" for i in output):
            raise LLMError("The model was still reasoning when it stopped. Try a shorter question.")
    raise LLMError("The model returned an unrecognised response.")


def chat(system_prompt: str, user_input: str, *, timeout: float | None = None) -> str:
    cfg = get_settings()
    body = {
        "model": cfg.lm_model,
        "system_prompt": system_prompt,
        "input": user_input,
        "temperature": cfg.lm_temperature,
    }
    try:
        resp = httpx.post(cfg.lm_endpoint, json=body, timeout=timeout or cfg.lm_timeout_s)
        resp.raise_for_status()
        return extract_message(resp.json())
    except httpx.ConnectError as exc:
        raise LLMError("Can't reach LM Studio. Start its local server and load the model.") from exc
    except httpx.TimeoutException as exc:
        raise LLMError("The model took too long to answer.") from exc
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text[:200]}") from exc
    except ValueError as exc:
        raise LLMError("LM Studio returned invalid JSON.") from exc


def chat_json(system_prompt: str, user_input: str, *, timeout: float | None = None) -> dict:
    """Ask for a JSON object; tolerate code fences and minor syntax damage."""
    raw = chat(system_prompt, user_input, timeout=timeout)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = repair_json(raw, return_objects=True)
    if not isinstance(data, dict):
        raise LLMError("The model did not return a JSON object.")
    return data


def vision(prompt: str, jpeg_b64: str, *, max_tokens: int = 5000, model: str = "") -> str:
    """Send one page image to a vision-capable model (OpenAI-compatible endpoint) and return its text.

    Raises LLMError if the model produced no answer (e.g. it spent its whole budget reasoning), so the page is
    retried later instead of being recorded as unreadable."""
    cfg = get_settings()
    body = {
        "model": model or cfg.ocr_model or cfg.lm_model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}},
        ]}],
    }
    try:
        resp = httpx.post(cfg.lm_openai_endpoint, json=body, timeout=cfg.ocr_timeout_s)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except httpx.ConnectError as exc:
        raise LLMError("Can't reach LM Studio. Start its local server and load the model.") from exc
    except httpx.TimeoutException as exc:
        raise LLMError("The model took too long to read the page.") from exc
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text[:200]}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError("LM Studio returned an unrecognised vision response.") from exc
    if not content:
        raise LLMError(f"The model returned no transcription for this page (finish reason: {choice.get('finish_reason')}). Retry to read it again.")
    return content


def status() -> dict:
    cfg = get_settings()
    try:
        resp = httpx.get(cfg.lm_models_endpoint, timeout=3)
        resp.raise_for_status()
        ids = [m.get("id") for m in resp.json().get("data", [])]
        return {"reachable": True, "model": cfg.lm_model, "model_available": cfg.lm_model in ids}
    except Exception:
        return {"reachable": False, "model": cfg.lm_model, "model_available": False}
