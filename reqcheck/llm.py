import hashlib
import json
import os
import re
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


class LLM:
    def __init__(self, use_cache: bool = True, cache_dir: str = ".cache/llm", mock=None):
        self.provider = os.getenv("LLM_PROVIDER", "openai_compat").strip().lower()
        self.model = os.getenv("LLM_MODEL", "").strip()
        self.base_url = os.getenv("LLM_BASE_URL", GEMINI_URL).strip() or GEMINI_URL
        self.api_key = os.getenv("LLM_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        self.timeout = float(os.getenv("LLM_TIMEOUT", "180"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "4"))
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir)
        self.mock = mock
        self.trace: list[dict] = []
        self.calls = 0
        self._client = None
        if self.provider == "mock":
            self.model = "mock"
        elif not self.model:
            self.model = os.getenv("GEMINI_MODEL", "").strip()

    def check(self) -> None:
        if self.provider == "mock":
            return
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise LLMError("no_key", "Не задан ключ LLM (LLM_API_KEY в файле .env).",
                           "Скопируйте .env.example в .env и вставьте ключ из aistudio.google.com.")
        if not self.model:
            raise LLMError("no_model", "Не задана модель (LLM_MODEL в файле .env).",
                           "Укажите модель, например из .env.example.")

    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key or "local", base_url=self.base_url,
                                  timeout=self.timeout, max_retries=0)
        return self._client

    def json(self, role: str, system: str, user: str):
        key = hashlib.sha256(f"{self.provider}|{self.model}|{system}|{user}".encode()).hexdigest()[:32]
        path = self.cache_dir / f"{role}-{key}.json"
        t0 = time.time()
        if self.use_cache and self.provider != "mock" and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.trace.append({"role": role, "cached": True, "seconds": 0.0, "in_tokens": data.get("in_tokens", 0),
                               "out_tokens": data.get("out_tokens", 0), "orig_seconds": data.get("seconds")})
            return unwrap(data["result"])
        if self.provider == "mock":
            result = self.mock(role, system, user) if self.mock else {}
            usage = (len(system + user) // 4, 0)
        else:
            result, usage = self._call(role, system, user)
        secs = round(time.time() - t0, 1)
        self.trace.append({"role": role, "cached": False, "seconds": secs, "in_tokens": usage[0], "out_tokens": usage[1]})
        if self.use_cache and self.provider != "mock":
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"result": result, "in_tokens": usage[0], "out_tokens": usage[1], "seconds": secs},
                                       ensure_ascii=False), encoding="utf-8")
        return unwrap(result)

    def _call(self, role: str, system: str, user: str):
        from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        delay = 8.0
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                self.calls += 1
                resp = self.client().chat.completions.create(
                    model=self.model, messages=messages, temperature=0,
                    response_format={"type": "json_object"})
                text = resp.choices[0].message.content or ""
                usage = (getattr(resp.usage, "prompt_tokens", 0) or 0, getattr(resp.usage, "completion_tokens", 0) or 0)
                try:
                    return parse_json(text), usage
                except (json.JSONDecodeError, ValueError):
                    last = "invalid_json"
                    messages = messages[:2] + [{"role": "assistant", "content": text[:2000]},
                                               {"role": "user", "content": "Ответ не является валидным JSON. Верни только валидный JSON по схеме, без пояснений."}]
                    continue
            except AuthenticationError:
                raise LLMError("auth", "Ключ LLM отклонён провайдером (401/403).", "Проверьте LLM_API_KEY в .env.")
            except RateLimitError as e:
                last = "rate_limit"
                msg = error_text(e)
                if "per day" in msg.lower() or "perday" in msg.lower() or "daily" in msg.lower():
                    wait = re.search(r"retry in (\d+h)?(\d+m)?", msg)
                    when = f" Провайдер просит повторить через {wait.group(0)[9:]}." if wait and wait.group(0)[9:] else ""
                    raise LLMError("quota_day", "Исчерпана дневная квота бесплатного тарифа LLM.",
                                   "Повторите после сброса квоты или укажите модель с большим лимитом." + when)
            except (APITimeoutError, APIConnectionError):
                last = "network"
            except APIStatusError as e:
                if e.status_code == 402:
                    raise LLMError("billing", "Провайдер отклонил запрос: закончились оплаченные кредиты проекта (402).",
                                   "Пополните баланс проекта в AI Studio или укажите ключ бесплатного проекта.")
                if e.status_code in (400, 404):
                    raise LLMError("bad_request", f"Провайдер отклонил запрос ({e.status_code}): {str(e)[:200]}",
                                   "Проверьте LLM_MODEL и LLM_BASE_URL в .env.")
                last = f"http_{e.status_code}"
            if attempt < self.max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 60)
        if last == "invalid_json":
            raise LLMError("invalid_json", f"Модель вернула невалидный JSON (роль {role}).", "Повторите запуск.")
        if last == "rate_limit":
            raise LLMError("rate_limit", "Превышен лимит запросов к LLM, повторы не помогли.",
                           "Подождите минуту и повторите; повторный запуск возьмёт готовые ответы из кэша.")
        if last.startswith("http_5"):
            raise LLMError("overloaded", f"Сервер модели перегружен или недоступен ({last}).",
                           "Это сбой на стороне провайдера: повторите позже или укажите другую модель в LLM_MODEL.")
        raise LLMError("network", f"LLM недоступна ({last}).", "Проверьте интернет и LLM_BASE_URL.")
