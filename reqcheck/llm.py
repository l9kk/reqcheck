import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def parse_json(text: str):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
        end = max(t.rfind("}"), t.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise


def unwrap(data):
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        out = {}
        for x in data:
            for k, v in x.items():
                if isinstance(v, list) and isinstance(out.get(k), list):
                    out[k] = out[k] + v
                else:
                    out.setdefault(k, v)
        return out
    return data


def error_text(e: Exception) -> str:
    parts = [str(e)]
    try:
        parts.append(str(getattr(e, "response", None).text))
    except Exception:
        pass
    body = getattr(e, "body", None)
    if body:
        parts.append(json.dumps(body, ensure_ascii=False))
    return " ".join(parts)


FIX_JSON = "Ответ не является валидным JSON. Верни только валидный JSON по схеме, без пояснений."

TEXTS = {
    "anthropic": {
        "no_key": ("Не задан ключ Anthropic (ANTHROPIC_API_KEY в файле .env).",
                   "Создайте ключ на platform.claude.com/settings/keys и вставьте его в .env."),
        "auth": ("Ключ Anthropic отклонён (401/403).", "Проверьте ANTHROPIC_API_KEY в .env."),
        "billing": ("Anthropic отклонил запрос: на балансе нет кредитов.",
                    "Пополните баланс в platform.claude.com (Billing)."),
        "bad_request": "Проверьте LLM_MODEL в .env.",
    },
    "openai_compat": {
        "no_key": ("Не задан ключ LLM (LLM_API_KEY в файле .env).",
                   "Скопируйте .env.example в .env и вставьте ключ из aistudio.google.com."),
        "auth": ("Ключ LLM отклонён провайдером (401/403).", "Проверьте LLM_API_KEY в .env."),
        "billing": ("Провайдер отклонил запрос: закончились оплаченные кредиты проекта (402).",
                    "Пополните баланс проекта в AI Studio или укажите ключ бесплатного проекта."),
        "bad_request": "Проверьте LLM_MODEL и LLM_BASE_URL в .env.",
    },
}

DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "openai_compat": "gemini-3.5-flash"}


def pick_provider() -> str:
    name = os.getenv("LLM_PROVIDER", "").strip().lower()
    if name:
        return name
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.getenv("LLM_API_KEY", "").strip():
        return "openai_compat"
    return "anthropic"


class LLM:
    def __init__(self, use_cache: bool = True, cache_dir: str = ".cache/llm"):
        self.provider = pick_provider()
        self.model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL.get(self.provider, "")
        if self.provider == "anthropic":
            self.api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            self.base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip() or "https://api.anthropic.com"
        else:
            self.api_key = os.getenv("LLM_API_KEY", "").strip()
            self.base_url = os.getenv("LLM_BASE_URL", "").strip() or GEMINI_URL
        self.texts = TEXTS["anthropic" if self.provider == "anthropic" else "openai_compat"]
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "64000"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "600"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "4"))
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir)
        self.trace: list[dict] = []
        self._client = None
        self._lock = threading.Lock()

    def check(self) -> None:
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise LLMError("no_key", *self.texts["no_key"])
        if not self.model:
            raise LLMError("no_model", "Не задана модель (LLM_MODEL в файле .env).",
                           "Укажите модель, например из .env.example.")

    def client(self):
        with self._lock:
            if self._client is None:
                if self.provider == "anthropic":
                    from anthropic import Anthropic as Client
                else:
                    from openai import OpenAI as Client
                self._client = Client(api_key=self.api_key or "local", base_url=self.base_url,
                                      timeout=self.timeout, max_retries=0)
            return self._client

    def json(self, role: str, system: str, user: str):
        key = hashlib.sha256(f"{self.provider}|{self.model}|{system}|{user}".encode()).hexdigest()[:32]
        path = self.cache_dir / f"{role}-{key}.json"
        t0 = time.time()
        if self.use_cache and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self.trace.append({"role": role, "cached": True, "seconds": 0.0, "in_tokens": data.get("in_tokens", 0),
                                   "out_tokens": data.get("out_tokens", 0), "orig_seconds": data.get("seconds")})
            return unwrap(data["result"])
        self.check()
        result, usage = self._call(role, system, user)
        secs = round(time.time() - t0, 1)
        with self._lock:
            self.trace.append({"role": role, "cached": False, "seconds": secs, "in_tokens": usage[0], "out_tokens": usage[1]})
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"result": result, "in_tokens": usage[0], "out_tokens": usage[1], "seconds": secs},
                                      ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        return unwrap(result)

    def _call(self, role: str, system: str, user: str):
        if self.provider == "anthropic":
            import anthropic as sdk
            send = self._send_anthropic
        else:
            import openai as sdk
            send = self._send_openai
        delay = 8.0
        last = ""
        bad = None
        for attempt in range(self.max_retries + 1):
            try:
                text, usage = send(role, system, user, bad)
                try:
                    return parse_json(text), usage
                except (json.JSONDecodeError, ValueError):
                    last = "invalid_json"
                    bad = text[:2000] or "-"
                    continue
            except Exception as e:
                last = self._retryable(sdk, e)
                if last is None:
                    raise
            if attempt < self.max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 60)
        self._fail(last, role)

    def _send_anthropic(self, role: str, system: str, user: str, bad: str | None):
        messages = [{"role": "user", "content": user}]
        if bad is not None:
            messages += [{"role": "assistant", "content": bad}, {"role": "user", "content": FIX_JSON}]
        with self.client().messages.stream(model=self.model, max_tokens=self.max_tokens, system=system,
                                           messages=messages) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise LLMError("refusal", f"Модель отказалась отвечать (роль {role}).",
                           "Проверьте документ или выберите другую модель.")
        text = "".join(b.text for b in msg.content if b.type == "text")
        return text, (getattr(msg.usage, "input_tokens", 0) or 0, getattr(msg.usage, "output_tokens", 0) or 0)

    def _send_openai(self, role: str, system: str, user: str, bad: str | None):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if bad is not None:
            messages += [{"role": "assistant", "content": bad}, {"role": "user", "content": FIX_JSON}]
        resp = self.client().chat.completions.create(model=self.model, messages=messages, temperature=0,
                                                     response_format={"type": "json_object"})
        text = resp.choices[0].message.content or ""
        return text, (getattr(resp.usage, "prompt_tokens", 0) or 0, getattr(resp.usage, "completion_tokens", 0) or 0)

    def _retryable(self, sdk, e: Exception) -> str | None:
        """Raise LLMError for errors a retry cannot fix, return a retry reason, or None for unknown errors."""
        if isinstance(e, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
            raise LLMError("auth", *self.texts["auth"])
        if isinstance(e, sdk.RateLimitError):
            msg = error_text(e)
            if "per day" in msg.lower() or "perday" in msg.lower() or "daily" in msg.lower():
                wait = re.search(r"retry in (\d+h)?(\d+m)?", msg)
                when = f" Провайдер просит повторить через {wait.group(0)[9:]}." if wait and wait.group(0)[9:] else ""
                raise LLMError("quota_day", "Исчерпана дневная квота бесплатного тарифа LLM.",
                               "Повторите после сброса квоты или укажите модель с большим лимитом." + when)
            return "rate_limit"
        if isinstance(e, (sdk.APITimeoutError, sdk.APIConnectionError)):
            return "network"
        if isinstance(e, sdk.APIStatusError):
            if e.status_code == 402 or "credit balance" in error_text(e).lower():
                raise LLMError("billing", *self.texts["billing"])
            if e.status_code in (400, 404):
                raise LLMError("bad_request", f"Провайдер отклонил запрос ({e.status_code}): {str(e)[:200]}",
                               self.texts["bad_request"])
            return f"http_{e.status_code}"
        return None

    def _fail(self, last: str, role: str):
        if last == "invalid_json":
            raise LLMError("invalid_json", f"Модель вернула невалидный JSON (роль {role}).", "Повторите запуск.")
        if last == "rate_limit":
            raise LLMError("rate_limit", "Превышен лимит запросов к LLM, повторы не помогли.",
                           "Подождите минуту и повторите; повторный запуск возьмёт готовые ответы из кэша.")
        if last.startswith("http_5"):
            raise LLMError("overloaded", f"Сервер модели перегружен или недоступен ({last}).",
                           "Это сбой на стороне провайдера: повторите позже или укажите другую модель в LLM_MODEL.")
        raise LLMError("network", f"LLM недоступна ({last}).", "Проверьте интернет и LLM_BASE_URL.")
