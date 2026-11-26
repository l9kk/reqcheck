from pathlib import Path

from . import roles
from .llm import LLMError
from .model import Report

TOP = 5


def ask(rep: Report, read=input, say=print) -> list[dict]:
    answers = []
    qs = rep.questions[:TOP]
    if not qs:
        say("Уточняющих вопросов нет.")
        return answers
    say(f"\nУточняющие вопросы ({len(qs)}). Номер варианта, свой ответ, Enter = по умолчанию, s = пропустить, q = закончить.")
    for q in qs:
        say(f"\n{q.id}. {q.text}")
        for qt in q.quotes[:2]:
            say(f"   > «{qt.text[:160]}» ({qt.loc})")
        if q.blocks:
            say(f"   Блокирует: {q.blocks}")
        for i, o in enumerate(q.options, start=1):
            say(f"   {i}) {o}")
        if q.default:
            say(f"   По умолчанию: {q.default}")
        try:
            a = read("   Ответ: ").strip()
        except EOFError:
            break
        if a.lower() == "q":
            break
        if a.lower() == "s":
            continue
        if not a:
            a = q.default
        elif a.isdigit() and 1 <= int(a) <= len(q.options):
            a = q.options[int(a) - 1]
        if a:
            answers.append({"q": q, "answer": a})
    return answers


def rewrite(answers: list[dict], rep: Report, llm, say=print) -> list[dict]:
    by_id = {f.id: f for f in rep.findings}
    out = {a["q"].id: {"q": a["q"], "answer": a["answer"], "requirement": "", "acceptance": []} for a in answers}
    if llm is not None and answers:
        lines = []
        for a in answers:
            q = a["q"]
            quotes = "; ".join(f"«{x.text}» ({x.loc})" for x in q.quotes[:2])
            probs = "; ".join(by_id[i].problem for i in q.finding_ids if i in by_id)
            lines.append(f"{q.id}. Вопрос: {q.text}\n  Цитаты: {quotes}\n  Замечания: {probs or '-'}\n  Ответ: {a['answer']}")
        system, user = roles.rewriter_prompt("\n".join(lines))
        try:
            data = llm.json("Rewriter", system, user)
            err = roles.shape_error("Rewriter", data)
            if err:
                data = llm.json("Rewriter", system, user + roles.shape_note(err))
        except LLMError as e:
            say(f"Модель не ответила ({e.code}): показываю ответы без новых формулировок.")
            data = None
        if isinstance(data, dict):
            for it in data.get("items", []) or []:
                if isinstance(it, dict) and it.get("q_id") in out:
                    out[it["q_id"]]["requirement"] = str(it.get("requirement", "")).strip()
                    out[it["q_id"]]["acceptance"] = [str(x) for x in it.get("acceptance", []) or []][:3]
    for v in out.values():
        if not v["requirement"]:
            v["requirement"] = f"{v['answer']} (формулировку нужно внести в требование вручную)"
    return list(out.values())


def render(items: list[dict], doc_name: str) -> str:
    md = [f"# Ответы на уточняющие вопросы: {doc_name}", "",
          "Демо-режим `--interactive`. Официальный отчёт этот файл не меняет.", ""]
    for v in items:
        q = v["q"]
        md += [f"## {q.id}. {q.text}", "", f"Ответ: {v['answer']}", ""]
        for qt in q.quotes[:2]:
            md.append(f"> «{qt.text}» ({qt.loc})")
        md += ["", f"Новая формулировка: {v['requirement']}", ""]
        if v["acceptance"]:
            md.append("Критерии приёмки:")
            md += [f"- {x}" for x in v["acceptance"]]
            md.append("")
    return "\n".join(md)


def run(rep: Report, llm, out_md: Path, read=input, say=print) -> Path | None:
    answers = ask(rep, read, say)
    if not answers:
        say("Ответов нет, формулировки не меняются.")
        return None
    items = rewrite(answers, rep, llm, say)
    for v in items:
        say(f"\n{v['q'].id}: {v['requirement']}")
        for x in v["acceptance"]:
            say(f"   - {x}")
    path = Path(out_md).with_name(Path(out_md).stem + ".answers.md")
    path.write_text(render(items, rep.passport.get("document", "")), encoding="utf-8")
    say(f"\nОтветы и новые формулировки: {path}")
    return path
