import argparse
import json
import os
import sys
from pathlib import Path

from .llm import LLM
from .pipeline import Pipeline, all_criteria, load_criteria
from .report_md import render


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m reqcheck",
                                 description="Агент проверки качества требований (ISO/IEC/IEEE 29148, IEEE 830).")
    ap.add_argument("input", help="путь к документу требований (.md, .txt, .pdf, .docx)")
    ap.add_argument("-o", "--output", default="report/report.md", help="путь к отчёту (.md); рядом пишутся .json")
    ap.add_argument("--no-cache", action="store_true", help="не использовать кэш ответов модели")
    ap.add_argument("--quiet", action="store_true", help="не печатать ход работы")
    ap.add_argument("--interactive", action="store_true",
                    help="демо: задать главные вопросы в терминале и показать новые формулировки")
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except Exception:
        pass

    llm = LLM(use_cache=not args.no_cache)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, flush=True))
    pipe = Pipeline(llm, log=log)
    try:
        rep = pipe.run(args.input)
    except Exception as e:
        from .model import Diagnostic, Report
        rep = Report(passport={"document": Path(args.input).name, "model": llm.model, "provider": llm.provider})
        rep.diagnostics.append(Diagnostic("error", "internal", f"Внутренняя ошибка агента: {type(e).__name__}: {e}",
                                          "Сообщите разработчикам, приложив входной файл."))
        rep.verdict = {"status": "Нет", "text": "Проверка прервана внутренней ошибкой.", "fix_first": []}
        if os.getenv("REQCHECK_DEBUG"):
            raise

    out = Path(args.output)
    if out.suffix.lower() not in (".md", ".pdf", ".json"):
        out = out.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    md_path = out.with_suffix(".md")
    md_path.write_text(render(rep, all_criteria(load_criteria())), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    written = [md_path, out.with_suffix(".json")]
    if out.suffix.lower() == ".pdf" or os.getenv("REQCHECK_PDF", "1") == "1":
        try:
            from .report_pdf import write_pdf
            write_pdf(md_path, out.with_suffix(".pdf"))
            written.append(out.with_suffix(".pdf"))
        except ImportError:
            pass
        except Exception as e:
            print(f"PDF не создан: {type(e).__name__}: {e}", file=sys.stderr)

    errors = [d for d in rep.diagnostics if d.level == "error"]
    crit = sum(1 for f in rep.findings if f.severity == "критично")
    print(f"Отчёт: {', '.join(str(p) for p in written)}")
    print(f"Требований: {len(rep.requirements)}, нарушений: {len(rep.findings)} (критичных: {crit}), "
          f"вопросов: {len(rep.questions)}. Вердикт: {rep.verdict.get('status')}.")
    for d in errors:
        print(f"Диагностика [{d.code}]: {d.message} {d.hint}")
    if args.interactive and rep.requirements:
        from .interactive import run as interactive_run
        interactive_run(rep, pipe.llm, md_path)
    if errors and (not rep.requirements or any(d.code == "not_requirements" for d in errors)):
        return 2
    return 1 if crit else 0
