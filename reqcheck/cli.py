import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .llm import LLM, ReplayLLM
from .pipeline import Pipeline, all_criteria, load_criteria
from .report_md import render


def model_used(passport: dict) -> bool:
    return (passport.get("llm_calls") or 0) + (passport.get("llm_cached") or 0) > 0


def old_passport(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    passport = data.get("passport") if isinstance(data, dict) else None
    return passport if isinstance(passport, dict) else {}


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m reqcheck",
                                 description="Агент проверки качества требований (ISO/IEC/IEEE 29148, IEEE 830).")
    ap.add_argument("input", help="путь к документу требований (.md, .txt, .pdf, .docx)")
    ap.add_argument("-o", "--output", default="out/report.md", help="путь к отчёту (.md); рядом пишутся .json, .html, .pdf")
    ap.add_argument("--no-cache", action="store_true", help="не использовать кэш ответов модели")
    ap.add_argument("--replay", action="store_true",
                    help="только повторить сохранённый прогон из .cache/llm: без ключа, без запросов к модели")
    ap.add_argument("--quiet", action="store_true", help="не печатать ход работы")
    ap.add_argument("--no-pdf", action="store_true", help="не создавать report.pdf")
    ap.add_argument("--no-html", action="store_true", help="не создавать report.html")
    ap.add_argument("--interactive", action="store_true",
                    help="демо: задать главные вопросы в терминале и показать новые формулировки")
    ap.add_argument("--answers", metavar="FILE",
                    help="ответы на вопросы из TOML (Q-01 = \"a\" | \"свой текст\" | \"default\"), без терминала")
    ap.add_argument("--no-wholedoc", action="store_true",
                    help="без роли WholeDoc (ревью всего документа одним запросом), для сравнения")
    ap.add_argument("--workers", type=int, metavar="N",
                    help="сколько запросов к модели слать одновременно (по умолчанию REQCHECK_WORKERS или 3; 1 = по очереди)")
    args = ap.parse_args(argv)

    load_dotenv(Path.cwd() / ".env")

    if args.replay and args.no_cache:
        ap.error("--replay и --no-cache вместе не имеют смысла")
    outs = {Path(args.output).with_suffix(x).resolve() for x in (".md", ".json", ".html", ".pdf")}
    if Path(args.input).resolve() in outs:
        ap.error("отчёт записался бы поверх документа: укажите другой путь в -o")
    llm = ReplayLLM() if args.replay else LLM(use_cache=not args.no_cache)
    log = (lambda m: None) if args.quiet else (lambda m: print(m, flush=True))
    pipe = Pipeline(llm, log=log, wholedoc=not args.no_wholedoc, workers=args.workers)
    crashed = False
    try:
        rep = pipe.run(args.input)
    except Exception as e:
        from .model import Diagnostic, Report
        crashed = True
        rep = Report(passport={"document": Path(args.input).name, "model": llm.model, "provider": llm.provider})
        rep.diagnostics.append(Diagnostic("error", "internal", f"Внутренняя ошибка агента: {type(e).__name__}: {e}",
                                          "Сообщите разработчикам, приложив входной файл."))
        rep.verdict = {"status": "Не проверено", "text": "Проверка прервана внутренней ошибкой.", "fix_first": []}
        if os.getenv("REQCHECK_DEBUG"):
            raise

    out = Path(args.output)
    if out.suffix.lower() not in (".md", ".pdf", ".json"):
        out = out.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not model_used(rep.passport) and model_used(old_passport(out.with_suffix(".json"))):
        kept = out.with_suffix(".json")
        out = out.with_name(f"{out.stem}.rules-only{out.suffix}")
        if crashed:
            print(f"Проверка прервана внутренней ошибкой: отчёт модели {kept} не перезаписан, "
                  f"отчёт об ошибке: {out.with_suffix('.md')}")
        else:
            print(f"Модель не использовалась: отчёт модели {kept} не перезаписан, отчёт по правилам: {out.with_suffix('.md')}")
    md_path = out.with_suffix(".md")
    md_path.write_text(render(rep, all_criteria(load_criteria())), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    written = [md_path, out.with_suffix(".json")]
    if not args.no_html:
        try:
            from .report_html import write_html
            doc = getattr(pipe, "doc", None)
            write_html(rep, [l.text for l in doc.lines] if doc else [], out.with_suffix(".html"))
            written.append(out.with_suffix(".html"))
        except Exception as e:
            print(f"HTML не создан: {type(e).__name__}: {e}", file=sys.stderr)
    if out.suffix.lower() == ".pdf" or not args.no_pdf:
        try:
            from .report_pdf import write_pdf
            write_pdf(md_path, out.with_suffix(".pdf"))
            written.append(out.with_suffix(".pdf"))
        except Exception as e:
            print(f"PDF не создан: {type(e).__name__}: {e}", file=sys.stderr)

    errors = [d for d in rep.diagnostics if d.level == "error"]
    crit = sum(1 for f in rep.findings if f.severity == "критично")
    print(f"Отчёт: {', '.join(str(p) for p in written)}")
    print(f"Требований: {len(rep.requirements)}, нарушений: {len(rep.findings)} (критичных: {crit}), "
          f"вопросов: {len(rep.questions)}. Вердикт: {rep.verdict.get('status')}.")
    for d in errors:
        print(f"Диагностика [{d.code}]: {d.message} {d.hint}")
    if (args.interactive or args.answers) and rep.requirements:
        from .interactive import load_answers, run as interactive_run
        preset = None
        if args.answers:
            try:
                preset = load_answers(args.answers, rep)
            except ValueError as e:
                print(f"Ответы: {e}", file=sys.stderr)
                return 2
        interactive_run(rep, pipe.llm if pipe.use_model else None, md_path, answers=preset, pipe=pipe)
    if errors and (not rep.requirements or any(d.code == "not_requirements" for d in errors)):
        return 2
    return 1 if crit else 0
