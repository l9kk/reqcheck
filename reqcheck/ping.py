import sys
import time
from pathlib import Path


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except Exception:
        pass
    from .llm import LLM, LLMError

    llm = LLM(use_cache=False)
    try:
        llm.check()
    except LLMError as e:
        print(f"{e.message} {e.hint}")
        return 2
    names = sys.argv[1:]
    if not names:
        try:
            models = [m.id for m in llm.client().models.list()]
        except Exception as e:
            print(f"Не удалось получить список моделей: {type(e).__name__}: {str(e)[:200]}")
            return 2
        flash = [m for m in models if "flash" in m or "gemma" in m]
        print("Доступные модели (flash/gemma):")
        for m in flash or models:
            print(" ", m)
        names = [llm.model]
    for name in names:
        llm.model = name.removeprefix("models/")
        t0 = time.time()
        try:
            r = llm.json("ping", "Верни JSON.", 'Верни {"ok": true}')
            print(f"{llm.model}: ok {r} за {time.time() - t0:.1f} с")
        except LLMError as e:
            print(f"{llm.model}: {e.code} {e.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
