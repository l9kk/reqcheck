import tomllib
from pathlib import Path

from . import roles
from .llm import LLMError
from .model import Report

TOP = 5


def pick(q, a: str) -> str:
    a = a.strip()
    if not a or a.lower() == "default":
        return q.default
    low = a.lower()
    if len(low) == 1 and "a" <= low <= "d" and ord(low) - 96 <= len(q.options):
        return q.options[ord(low) - 97]
    if a.isdigit() and 1 <= int(a) <= len(q.options):
        return q.options[int(a) - 1]
    return a


def load_answers(path, rep: Report) -> list[dict]:
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"не удалось прочитать файл ответов {path}: {e}")
    by_id = {q.id: q for q in rep.questions}
    out = []
    for qid, val in raw.items():
        if qid not in by_id:
            raise ValueError(f"в файле ответов вопрос {qid}, а в отчёте есть только {', '.join(by_id) or 'ничего'}")
        a = pick(by_id[qid], str(val))
        if a:
            out.append({"q": by_id[qid], "answer": a})
    return sorted(out, key=lambda x: x["q"].id)


def ask(rep: Report, read=input, say=print) -> list[dict]:
    answers = []
    qs = rep.questions[:TOP]
    if not qs:
        say("Уточняющих вопросов нет.")
        return answers
    say(f"\nУточняющие вопросы ({len(qs)}). Буква варианта, свой ответ, Enter = по умолчанию, s = пропустить, q = закончить.")
    for q in qs:
        say(f"\n{q.id}. {q.text}")
        for qt in q.quotes[:2]:
            say(f"   > «{qt.text[:160]}» ({qt.loc})")
        if q.blocks:
            say(f"   Блокирует: {q.blocks}")
        for i, o in enumerate(q.options):
            say(f"   {chr(97 + i)}) {o}")
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
        a = pick(q, a)
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


def run(rep: Report, llm, out_md: Path, read=input, say=print, answers: list[dict] | None = None, pipe=None) -> Path | None:
    if answers is None:
        answers = ask(rep, read, say)
    else:
        say(f"\nОтветы из файла: {len(answers)}")
    if not answers:
        say("Ответов нет, формулировки не меняются.")
        return None
    items = rewrite(answers, rep, llm, say)
    for v in items:
        say(f"\n{v['q'].id}: {v['requirement']}")
        for x in v["acceptance"]:
            say(f"   - {x}")
    text = render(items, rep.passport.get("document", ""))
    if pipe is not None and llm is not None:
        from .loop import recheck, render_delta
        delta = recheck(pipe, rep, items, say)
        if delta:
            block = render_delta(delta)
            say("\n" + block)
            text += "\n" + block
    path = Path(out_md).with_name(Path(out_md).stem + ".answers.md")
    path.write_text(text, encoding="utf-8")
    say(f"\nОтветы, новые формулировки и дельта: {path}")
    return path
