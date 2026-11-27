# Результаты в одном месте

Каждое число ниже взято из файла в этом репозитории, и его можно перепроверить командой. Команды не тратят
деньги и не ходят в сеть: отчёты уже лежат в репозитории, а ответы модели в кэше `.cache/llm`.

Версия агента 1.6.3 (тег `v1.6.3`; замечания те же, что в 1.6, поменялся только вид HTML-отчёта), модель `claude-opus-5-5`, если не сказано другое.

## Выданное ТЗ

| Что | Число | Откуда | Как проверить |
| :--- | :--- | :--- | :--- |
| Найдено дефектов из нашего списка, строгая проверка (каждое совпадение прочитал отдельный агент, не человек) | **39 из 40** | [`eval/handcheck_v1.5.md`](eval/handcheck_v1.5.md) | читать таблицу G01-G40 |
| То же, автоматическая сверка | 40 из 40 | [`eval/golden.toml`](eval/golden.toml) | `python eval/score.py report/report.json` |
| Критичные распознаны как критичные | 6 из 6 | то же | то же, строка `Critical found as critical` |
| Замечания агента, оказавшиеся реальными дефектами | 48 из 55 (87%), ложных 0 | [`eval/handcheck_v1.5.md`](eval/handcheck_v1.5.md) | раздел Precision |
| Ручная проверка v1.5 относится к v1.6 | 55 замечаний те же, кроме текстов исправлений | [`eval/handcheck_v1.5_input.json`](eval/handcheck_v1.5_input.json) | `python eval/same_findings.py eval/handcheck_v1.5_input.json report/report.json` |
| Вопросы к автору | 10, у каждого адресат, варианты и рекомендация; у 7 из 10 к вариантам приложен тест | [`report/report.md`](report/report.md) | раздел «Вопросы» |
| Один промпт на той же модели, 2 прогона | 36 и 34 из 40 | [`eval/baseline/README.md`](eval/baseline/README.md) | таблица Strict recall |
| Разброс: ещё 2 прогона без кэша (v1.6.2) | 39 и 38 из 40 (закоммиченный 40), критичные 6 из 6, обязательные 13 из 13, точность 86% и 90%, около 11 мин на прогон | [`eval/variance.md`](eval/variance.md) | `python eval/score.py eval/variance/run2.json` |
| Вклад каждого шага пайплайна | от 11 из 40 (только правила) до 40 из 40 | [`eval/ablation.md`](eval/ablation.md) | `python -m eval.ablation` |
| Противоречия между замечанием и исправлением после Reconciler | было 4-8 из 10, стало 2 из 10 (два слепых проверяющих) | [`eval/reconciler_check.md`](eval/reconciler_check.md) | читать вердикты |

## Другие документы

| Что | Число | Откуда | Как проверить |
| :--- | :--- | :--- | :--- |
| autotopup, автоматическая сверка | 18 из 18, критичные 4 из 4 | [`examples/autotopup/report.json`](examples/autotopup/report.json) | `python eval/score.py examples/autotopup/report.json --golden eval/golden_autotopup.toml` |
| cashback, разметка написана до первого прогона | первый прогон (v1.3): 20 из 20 при строгой проверке агентом | [`eval/manual_check.md`](eval/manual_check.md) | разметка: коммит 0fe31eb (26.11 02:10), первый отчёт: 80e6f66 (27.11 03:29) |
| cashback на v1.6, автоматическая сверка | 20 из 20, критичные 4 из 5 (B04 понижен до «важно») | [`examples/cashback/report.json`](examples/cashback/report.json) | `python eval/score.py examples/cashback/report.json --golden eval/golden_cashback.toml` |
| Бесплатный Gemini (`gemini-3.5-flash`, v1.5) | 29 из 40, критичные 6 из 6 | [`examples/gemini/report.json`](examples/gemini/report.json) | `python eval/score.py examples/gemini/report.json` |
| Ответы автора закрывают дефекты | закрыто 8 из 21, критичных 5 → 3 | [`examples/answers/requirements.report.answers.md`](examples/answers/requirements.report.answers.md) | раздел «Дельта после ответов» |
| Скан, пустой, обрезанный, зашифрованный файл | отчёт с понятной ошибкой и советом, что сделать | [`examples/broken/`](examples/broken/) | читать файлы |
| Инструкции для ИИ внутри ТЗ («игнорируй предыдущие инструкции») | не выполняются, агент сам отмечает их как дефект (D-12) | [`examples/injection/report.md`](examples/injection/report.md) | читать отчёт |

## Стоимость и время прогона

| Что | Число | Откуда |
| :--- | :--- | :--- |
| Запросов к модели на выданном ТЗ | 9 | паспорт в [`report/report.md`](report/report.md) |
| Токены, вход / выход | 130 339 / 94 982 | то же |
| Цена | $2.42, около 1 110 ₸ (курс НБ РК 458.85 на 27.11.2026, счёта нет) | [`docs/details.md`](docs/details.md#ценность-в-тенге) |
| Время модели | 843.8 с, около 14 минут | паспорт |
| Gemini, бесплатный ключ | 7 запросов, 0 ₸, 315.3 с, около 5 минут | [`examples/gemini/report.md`](examples/gemini/report.md) |

## Повторить весь прогон без ключа

```bash
git clone https://github.com/l9kk/reqcheck && cd reqcheck
python -m venv .venv && .venv/bin/pip install -r requirements.txt
LLM_PROVIDER=anthropic LLM_MODEL=claude-opus-5-5 .venv/bin/python -m reqcheck input/requirements.md -o out/report.md
```

Все 9 ответов берутся из кэша, отчёт совпадает с [`report/report.json`](report/report.json) (кроме даты, версии и времени прогона).
Тесты (164): `.venv/bin/python -m unittest tests.test_reader tests.test_pipeline tests.test_report_md eval.test_score tests.test_loop eval.test_ablation tests.test_no_overfit tests.test_report_html tests.test_reconciler tests.test_report_html_polish`

## Чего здесь нет

- Списки дефектов (`eval/golden*.toml`) составили мы сами. Независимой разметки нет.
- Время живых ревьюеров мы не засекали; нормы ревью в [`docs/qa.md`](docs/qa.md) взяты из литературы.
