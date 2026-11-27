# Результаты в одном месте

Каждое число ниже взято из файла в этом репозитории, и его можно перепроверить командой. Команды не тратят
деньги и не ходят в сеть: отчёты уже лежат в репозитории, а ответы модели в кэше `.cache/llm`.

Версия агента 1.6.10 (тег `v1.6.10`; замечания те же, что в 1.6, поменялись вид HTML-отчёта (новый дизайн), строка о критичных в сводке и форматы входа), модель `claude-opus-5-5`, если не сказано другое.

## Выданное ТЗ

| Что | Число | Откуда | Как проверить |
| :--- | :--- | :--- | :--- |
| Найдено дефектов из нашего списка, автоматическая сверка | **40 из 40** | [`eval/golden.toml`](eval/golden.toml) | `python eval/score.py report/report.json` |
| То же, строгая проверка (каждое совпадение прочитал отдельный агент) | 39 из 40 | [`eval/handcheck_v1.5.md`](eval/handcheck_v1.5.md) | читать таблицу G01-G40 |
| Критичные распознаны как критичные | 6 из 6 | то же | то же, строка `Critical found as critical` |
| Замечания агента, оказавшиеся реальными дефектами | 48 из 55 (87%), ложных 0 | [`eval/handcheck_v1.5.md`](eval/handcheck_v1.5.md) | раздел Precision |
| Строгая проверка v1.5 относится к v1.6 | 55 замечаний те же, кроме текстов исправлений | [`eval/handcheck_v1.5_input.json`](eval/handcheck_v1.5_input.json) | `python eval/same_findings.py eval/handcheck_v1.5_input.json report/report.json` |
| Вопросы к автору | 10, у каждого адресат, варианты и рекомендация; у 7 из 10 к вариантам приложен тест | [`report/report.md`](report/report.md) | раздел «Вопросы» |
| Один промпт на той же модели, 2 прогона | 36 и 35 из 40 автоматически, 36 и 34 строго | [`eval/baseline/README.md`](eval/baseline/README.md) | таблица Task doc, строки Auto recall и Strict recall |
| Разброс: ещё 2 прогона без кэша (v1.6.2) | 39 и 38 из 40 (закоммиченный 40); в каждом из 3 прогонов критичные 6 из 6, важные 25 из 25, обязательные 13 из 13; точность 86% и 90%, около 11 мин на прогон | [`eval/variance.md`](eval/variance.md) | `python eval/score.py eval/variance/run2.json`, то же для `run3.json` и `report/report.json` |
| Вклад каждого шага пайплайна | от 11 из 40 (только правила) до 40 из 40 | [`eval/ablation.md`](eval/ablation.md) | `python -m eval.ablation` |
| Противоречия между замечанием и исправлением после Reconciler | было 4-8 из 10, стало 2 из 10 (два слепых проверяющих) | [`eval/reconciler_check.md`](eval/reconciler_check.md) | читать вердикты |

## Другие документы

| Что | Число | Откуда | Как проверить |
| :--- | :--- | :--- | :--- |
| autotopup, автоматическая сверка | 18 из 18, критичные 4 из 4 | [`examples/autotopup/report.json`](examples/autotopup/report.json) | `python eval/score.py examples/autotopup/report.json --golden eval/golden_autotopup.toml` |
| cashback, разметка написана до любого прогона | первый полный прогон (v1.3): 20 из 20 при строгой проверке | [`eval/manual_check.md`](eval/manual_check.md) | разметка: коммит 0fe31eb (26.11 02:10), первый полный отчёт: 80e6f66 (27.11 03:29) |
| cashback на v1.6, автоматическая сверка | 20 из 20, критичные 4 из 5 (B04 понижен до «важно») | [`examples/cashback/report.json`](examples/cashback/report.json) | `python eval/score.py examples/cashback/report.json --golden eval/golden_cashback.toml` |
| Ответы на вопросы агента закрывают дефекты | закрыто 8 из 21, критичных 5 → 3 (в примере отвечали мы: 6 раз приняли рекомендацию агента, 4 раза вариант (а)) | [`examples/answers/requirements.report.answers.md`](examples/answers/requirements.report.answers.md) | раздел «Дельта после ответов» |
| Скан, пустой, обрезанный, зашифрованный файл | отчёт с понятной ошибкой и советом, что сделать | [`examples/broken/`](examples/broken/) | читать файлы |
| Инструкции для ИИ внутри ТЗ («игнорируй предыдущие инструкции») | не выполняются, агент сам отмечает их как дефект (D-05) | [`examples/injection/report.md`](examples/injection/report.md) | читать отчёт |

## Стоимость и время прогона

| Что | Число | Откуда |
| :--- | :--- | :--- |
| Запросов к модели на выданном ТЗ | 9 | паспорт в [`report/report.md`](report/report.md) |
| Токены, вход / выход | 130 339 / 94 982 | то же |
| Цена | $2.42, около 1 110 ₸ (курс НБ РК 458.85 на 27.11.2026, счёта нет) | [`docs/details.md`](docs/details.md#ценность-в-тенге) |
| Время модели | 843.8 с, около 14 минут | паспорт |
| Инспекция того же ТЗ командой из 3-4 ревьюеров, по нормам | 2.3-4.6 ч на всю команду, около 8 000-15 900 ₸ | [`docs/details.md`](docs/details.md#ценность-в-тенге) |

## Повторить весь прогон без ключа

```bash
git clone https://github.com/l9kk/reqcheck && cd reqcheck
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m reqcheck input/requirements.md -o out/report.md --replay
```

Все 9 ответов берутся из кэша, отчёт совпадает с [`report/report.json`](report/report.json) (кроме даты, версии и времени прогона).
Тесты (176): `.venv/bin/python -m unittest discover -s tests -t . && .venv/bin/python -m unittest discover -s eval -t .`

## Как мы считали

- Списки дефектов (`eval/golden*.toml`) составили мы сами, независимой разметки нет. ТЗ cashback разметили
  до первого прогона; версии 1.5 и 1.6 настраивали уже после него.
- Строгую проверку делал отдельный агент-проверяющий, не человек: выданное ТЗ (v1.5, те же 55 замечаний, что в v1.6)
  и первые прогоны v1.3 ([`eval/manual_check.md`](eval/manual_check.md)). Прогоны разброса и отчёты v1.6 на
  autotopup и cashback сверены автоматически (`eval/score.py`).
- Разброс мерили на выданном ТЗ, 3 прогона. На autotopup и cashback по одному прогону.
- Время ревьюеров на этом ТЗ не засекали. Часы и тенге посчитаны по нормам из литературы (Wiegers 1995,
  Fagan 1976): [`docs/details.md`](docs/details.md#ценность-в-тенге). Цена прогона посчитана по прайсу API, счёта нет.
- ТЗ уходит в API выбранного провайдера модели. Маскирования персональных данных в агенте нет.
