"""Server-only adapters. Never expose keys or upstream response bodies."""

import json
import os
import socket
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .schema import ValidationError, validate

ROOT = Path(__file__).resolve().parent.parent
MAX_RESPONSE = 2_000_000
SETTING_FIELDS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_MODEL", "CLAUDE_MODEL",
                  "OLLAMA_MODEL", "OLLAMA_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_MODE",
                  "OPENAI_OUTPUT_MODE"}
KEY_FIELDS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
SETTINGS_LOCK = threading.Lock()
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"


class OutputValidationError(ValidationError):
    """Parsed, invalid model data; held in memory for bounded caller-owned repair."""

    def __init__(self, message, output):
        super().__init__(message)
        self.output = output


def openai_url(value):
    value = value.strip().rstrip("/") or DEFAULT_OPENAI_BASE
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValidationError("OpenAI 호환 Base URL 형식이 잘못되었습니다.") from None
    local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if (not parsed.hostname or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() or ord(c) < 32 for c in value) or not value.isascii()
            or (port is not None and not 1 <= port <= 65535)
            or parsed.path.endswith(("/responses", "/chat/completions"))):
        raise ValidationError("Base URL에는 HTTPS 기본 주소를 입력해주세요. 키·쿼리·전체 API 경로는 넣지 마세요. HTTP는 로컬 주소만 허용합니다.")
    return value


def openai_options(settings):
    base = openai_url(settings.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE))
    mode = settings.get("OPENAI_API_MODE", "responses")
    output = settings.get("OPENAI_OUTPUT_MODE", "json_schema")
    if mode not in ("responses", "chat_completions"):
        raise ValidationError("OpenAI API 방식이 올바르지 않습니다.")
    if output not in ("json_schema", "json_object", "prompt"):
        raise ValidationError("OpenAI JSON 출력 방식이 올바르지 않습니다.")
    return base, mode, output


def local_settings():
    path = ROOT / ".local-secrets" / "ui-settings.json"
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - SETTING_FIELDS or any(not isinstance(v, str) for v in value.values()):
        raise ValidationError("로컬 API 설정 파일 형식이 잘못되었습니다.")
    return value


def ollama_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValidationError("Ollama 포트가 올바르지 않습니다.") from None
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.path.strip("/") or parsed.query or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)):
        raise ValidationError("Ollama 주소는 경로 없는 로컬 HTTP 주소여야 합니다.")
    return value.rstrip("/")


def save_settings(payload):
    if set(payload) != {"values", "clear_keys"} or not isinstance(payload["values"], dict):
        raise ValidationError("설정 요청 형식이 잘못되었습니다.")
    values, clear = payload["values"], payload["clear_keys"]
    if (set(values) - SETTING_FIELDS or not isinstance(clear, list)
            or any(not isinstance(k, str) or k not in KEY_FIELDS for k in clear)):
        raise ValidationError("허용되지 않은 설정 항목입니다.")
    changes = {}
    for key, value in values.items():
        limit = 4096 if key in KEY_FIELDS else 2048 if key == "OPENAI_BASE_URL" else 200
        if not isinstance(value, str) or len(value) > limit:
            raise ValidationError("설정 값의 형식 또는 길이가 잘못되었습니다.")
        value = value.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValidationError("설정에 줄바꿈이나 제어문자를 사용할 수 없습니다.")
        if key in KEY_FIELDS:
            if value and (not value.isascii() or any(c.isspace() for c in value)):
                raise ValidationError("API 키에는 공백이나 비 ASCII 문자를 사용할 수 없습니다.")
            if not value:
                continue  # A blank password field preserves the saved key.
        if key == "OLLAMA_BASE_URL":
            if not value:
                continue  # Other providers do not require an Ollama address.
            value = ollama_url(value)
        if key == "OPENAI_BASE_URL":
            value = openai_url(value)
        if key == "OPENAI_API_MODE" and value not in ("responses", "chat_completions"):
            raise ValidationError("OpenAI API 방식을 선택해주세요.")
        if key == "OPENAI_OUTPUT_MODE" and value not in ("json_schema", "json_object", "prompt"):
            raise ValidationError("JSON 출력 방식을 선택해주세요.")
        changes[key] = value
    if set(clear) & set(changes):
        raise ValidationError("같은 키를 교체하면서 삭제할 수 없습니다.")
    changes.update({key: "" for key in clear})
    if set(changes) & set(os.environ):
        raise ValidationError("환경변수로 관리되는 항목은 웹에서 변경할 수 없습니다.")
    if "OPENAI_BASE_URL" in changes:
        current = load_settings()
        old_base = openai_url(current.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE))
        if (urlsplit(old_base).netloc.lower() != urlsplit(changes["OPENAI_BASE_URL"]).netloc.lower()
                and current.get("OPENAI_API_KEY") and "OPENAI_API_KEY" not in changes):
            raise ValidationError("API 대상 주소를 변경할 때는 해당 서비스의 키를 새로 입력하거나 기존 키를 삭제해주세요.")
    with SETTINGS_LOCK:
        saved = local_settings()
        saved.update(changes)
        directory = ROOT / ".local-secrets"
        directory.mkdir(mode=0o700, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="ui-settings-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                json.dump(saved, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(name, directory / "ui-settings.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return configuration()


class ProviderError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_settings():
    """Environment > UI settings > this app's .env; no shell expansion."""
    allowed = SETTING_FIELDS
    settings = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in allowed:
                settings[key] = value.strip().strip('"\'')
    settings.update(local_settings())
    for key in allowed:
        if key in os.environ:
            settings[key] = os.environ[key]
    return settings


def configuration():
    settings = load_settings()
    base, mode, output = openai_options(settings)
    endpoint = base + ("/responses" if mode == "responses" else "/chat/completions")
    return {"ollama_base_url": ollama_url(settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")),
            "openai_base_url": base, "openai_api_mode": mode, "openai_output_mode": output,
            "environment_fields": sorted(SETTING_FIELDS & set(os.environ)), "providers": [
        {"id": "demo", "name": "예시 모드", "configured": True, "model": "",
         "destination": "전송 없음 · 고정 템플릿 체험"},
        {"id": "ollama", "name": "Ollama", "configured": True,
         "model": settings.get("OLLAMA_MODEL", ""),
         "destination": "로컬 Ollama · 클라우드 모델 사용 시 외부 전송 가능"},
        {"id": "openai", "name": "OpenAI", "configured": bool(settings.get("OPENAI_API_KEY")),
         "model": settings.get("OPENAI_MODEL", ""),
         "destination": f"{endpoint} · 입력과 콘티 전송 · API 요금 발생"},
        {"id": "claude", "name": "Claude", "configured": bool(settings.get("ANTHROPIC_API_KEY")),
         "model": settings.get("CLAUDE_MODEL", ""),
         "destination": "api.anthropic.com · 입력과 콘티 전송 · API 요금 발생"},
    ]}


def request_json(url, payload, headers, timeout=180):
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    # Do not inherit proxy settings or follow redirects with credentials.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProviderError("AI 응답이 너무 큽니다. 컷 수를 줄여주세요.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProviderError("AI 제공자의 응답 형식이 잘못되었습니다.")
        return value
    except HTTPError as exc:
        # Upstream errors may echo user input or credentials. Do not relay them.
        raise ProviderError(f"AI 요청 실패 (HTTP {exc.code}). 키·모델·사용 한도를 확인해주세요.") from None
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise ProviderError("AI 서버에 연결할 수 없거나 응답 시간이 초과되었습니다. 자동 재시도하지 않았습니다.") from None
    except (ValueError, UnicodeError):
        raise ProviderError("AI 서버가 올바른 JSON 응답을 반환하지 않았습니다.") from None


def generate_json(provider, model, system, user, schema):
    if provider not in ("ollama", "openai", "claude"):
        raise ValidationError("지원하지 않는 AI 제공자입니다.")
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValidationError("사용할 모델 ID를 입력해주세요.")
    settings = load_settings()
    schema_text = json.dumps(schema, ensure_ascii=False)
    instruction = system + "\n다음 JSON Schema에 맞는 JSON 객체만 반환하세요:\n" + schema_text
    if provider == "ollama":
        base = settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        base = ollama_url(base)
        result = request_json(base + "/api/chat", {
            "model": model, "messages": [{"role": "system", "content": instruction},
                                           {"role": "user", "content": user}],
            "stream": False, "format": schema, "options": {"num_predict": 16000}}, {})
        if result.get("done") is not True or result.get("done_reason") == "length":
            raise ProviderError("Ollama 응답이 완료되지 않았습니다. 컷 수를 줄여주세요.")
        content = result.get("message", {}).get("content")
    elif provider == "openai":
        key = settings.get("OPENAI_API_KEY")
        if not key:
            raise ValidationError("API 설정에서 OpenAI 키를 등록해주세요.")
        base, mode, output = openai_options(settings)
        headers = {"Authorization": f"Bearer {key}"}
        if mode == "chat_completions":
            payload = {"model": model, "stream": False, "messages": [
                {"role": "system", "content": instruction}, {"role": "user", "content": user}]}
            token_field = "max_completion_tokens" if urlsplit(base).hostname == "api.openai.com" else "max_tokens"
            payload[token_field] = 16000
            if output == "json_schema":
                payload["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "storyboard", "strict": True, "schema": schema}}
            elif output == "json_object":
                payload["response_format"] = {"type": "json_object"}
            result = request_json(base + "/chat/completions", payload, headers)
            choices = result.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ProviderError("OpenAI 호환 API의 choices 응답 형식이 잘못되었습니다.")
            choice = choices[0]
            message = choice.get("message")
            if not isinstance(message, dict) or choice.get("finish_reason") != "stop":
                raise ProviderError("응답이 완료되지 않았습니다. 출력 잘림·거절·도구 호출 여부를 확인해주세요.")
            if message.get("refusal") or message.get("tool_calls"):
                raise ProviderError("모델이 요청을 거절했거나 지원하지 않는 도구 호출을 반환했습니다.")
            content = message.get("content")
        else:
            payload = {"model": model, "instructions": instruction, "input": user,
                       "store": False, "max_output_tokens": 16000}
            if output == "json_schema":
                payload["text"] = {"format": {"type": "json_schema", "name": "storyboard", "strict": True, "schema": schema}}
            elif output == "json_object":
                payload["text"] = {"format": {"type": "json_object"}}
            result = request_json(base + "/responses", payload, headers)
            if result.get("status") != "completed":
                raise ProviderError("OpenAI 응답이 완료되지 않았습니다. 모델 설정과 출력 한도를 확인해주세요.")
            chunks = [part for item in result.get("output", []) if item.get("type") == "message"
                      for part in item.get("content", [])]
            if any(p.get("type") == "refusal" for p in chunks):
                raise ProviderError("OpenAI가 요청에 대한 생성을 거절했습니다.")
            content = "".join(p.get("text", "") for p in chunks if p.get("type") == "output_text")
    else:
        key = settings.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValidationError("API 설정에서 Claude 키를 등록해주세요.")
        result = request_json("https://api.anthropic.com/v1/messages", {
            "model": model, "max_tokens": 16000, "system": instruction,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}}},
            {"x-api-key": key, "anthropic-version": "2023-06-01"})
        if result.get("stop_reason") != "end_turn":
            raise ProviderError("Claude 응답이 완료되지 않았거나 거절되었습니다. 모델과 출력 한도를 확인해주세요.")
        content = "".join(p.get("text", "") for p in result.get("content", []) if p.get("type") == "text")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("AI가 사용할 수 있는 텍스트를 반환하지 않았습니다.")
    try:
        # Some compatible models wrap JSON in one Markdown fence. Accept only that
        # exact wrapper; never extract JSON from arbitrary prose or reasoning.
        clean = content.strip()
        lines = clean.splitlines()
        if len(lines) >= 3 and lines[0].lower() in ("```json", "```") and lines[-1] == "```":
            clean = "\n".join(lines[1:-1])
        value = json.loads(clean)
    except ValueError:
        raise ProviderError("AI 출력이 JSON이 아닙니다. 기존 콘티는 유지됩니다.") from None
    try:
        validate(value, schema, "AI 응답")
    except ValidationError as error:
        raise OutputValidationError(str(error), value) from None
    return value
