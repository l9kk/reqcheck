# Reconciler: слепая проверка согласованности вопросов и исправлений (27.11.2026)

Метод: проверяющий (отдельный агент, не видел версий) получил по два отчёта на каждый из 3 ТЗ под именами A и B: отчёт v1.5 (`git show v1.5:...`) и отчёт v1.6. Строка «Версия агента» и имя роли скрыты. Для каждого вопроса: C1 - рекомендация согласуется с исправлением каждого закрываемого замечания; C2 - рекомендация не спорит с другими вопросами. Ключ: doc1 = выданное ТЗ, doc2 = autotopup, doc3 = cashback; A = v1.5, B = v1.6.

Итог этого проверяющего: v1.5 - 4, 5, 5 из 10 спорных вопросов (14 из 30); v1.6 - 2, 2, 0 из 10 (4 из 30). Первый слепой проверяющий (при разработке роли, те же пары) на выданном ТЗ насчитал 8 из 10 в v1.5 и 2 из 10 в v1.6. Оставшиеся 4 спорных в v1.6 - пары вопросов, которые спорят между собой (C2); у них в отчёте пометка «Внимание».

Проверка качества исправлений в v1.6 (выборка 15): 7 слабых - заглушки, только примеры, нет конечного состояния. Это о текстах исправлений вообще, до v1.6 их так не проверяли.

Ниже - вывод проверяющего без правок.

---

# Verdict: question/fix consistency, 6 reports

Method: for every Q in section 3 I took its recommendation and the «Как исправить» text of every D it closes (section 5/6 blocks). C1 = rec vs those fixes. C2 = rec vs the other recs in the same report. "borderline" = counted as inconsistent under strict grading, see the lenient count.
Cross-notes = a fix closed by one Q that contradicts another Q's rec. They are listed but not counted.

## doc1_A (inconsistent: 4 of 10)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | ok | ok | Rec auth date, Jan. D-01 «январский счётчик вырос», D-18/D-40 neutral |
| Q-02 | FAIL | ok | Rec (б) "смена порога сбрасывает признак". D-15: «лимит ... имеет приоритет ... в том числе после изменения порога». Cross-note: D-19 push text «содержит ... сумму расходов» vs Q-07 rec "без сумм" |
| Q-03 | FAIL | ok | Rec HTTP 400, "в ответе нет amount и enabled". D-05: «вернуть HTTP 200 с result=ERROR ... amount и enabled». D-46 returns prior amount/enabled. D-51: «result ... ERROR» only in 200. D-52: 400 only for missing/type |
| Q-04 | ok | ok | D-04 GET /alerts/limit (spentMonth vs monthSpent naming only) |
| Q-05 | ok | ok | Rec clearing + rephrase goal. D-06 variant (а) same. D-30 neutral |
| Q-06 | ok | ok | Rec PUT. D-43 «POST или PUT с телом». D-63/D-47 neutral |
| Q-07 | FAIL | ok | Rec push without sums. D-29: «Текст push: „... достигли порога 50 000 ₸“» |
| Q-08 | ok | ok | D-13 «для всех активных карт KZT». D-16 migration, neutral |
| Q-09 | FAIL | ok | Rec «До 3 повторов с интервалом 10 с». D-07: «до 5 раз ... с интервалом 30 с» |
| Q-10 | ok | ok | D-17 type+MCC table. D-14 neutral |

## doc1_B (inconsistent: 2 of 10)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | ok | ok | Rec (б). D-01/D-16/D-33 all match (reset only on a different value) |
| Q-02 | ok | ok | Rec auth date UTC+5. D-04/D-11/D-13 match |
| Q-03 | ok | FAIL | Rec PUT /alerts/limit, «GET на этот URL возвращает 405» (D-05 same). Q-05 rec: «GET /alerts/limit?cardId=… возвращает {amount, enabled ...}». Same URL |
| Q-04 | ok | ok | Rec all 400. D-06/D-32/D-39 match |
| Q-05 | ok | FAIL | Reverse side of the Q-03 conflict (D-02 reads via GET /alerts/limit) |
| Q-06 | ok | ok | Rec hold counted. D-12 matches |
| Q-07 | ok | ok | D-15 per card_id |
| Q-08 | ok | ok | D-27 matches (б). Minor: rec cites «вопрос 3» for the hold model, which is Q-06 |
| Q-09 | ok | ok | D-14 partition by card_id |
| Q-10 | ok | ok | D-07/D-23 p95, 200 ev/s, both match |

## doc2_A (inconsistent: 5 of 10, lenient 3)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | FAIL | ok | Rec hourly, "не ответил → через 60 минут". D-14: «3 попытки с интервалом 15 минут». D-02 also keeps «Ежедневная проверка в 09:00» next to «каждые 60 минут» |
| Q-02 | FAIL | ok | Rec hold, "отмена холда при FAIL или таймауте в течение 1 минуты". D-03: «При таймауте статус ... до 3 раз, без ответа ... ручную сверку». D-12: «при неопределённом результате ... ручную сверку» (that is option в) |
| Q-03 | FAIL (borderline) | ok | Rec (а). D-21 «не более трёх успешных ... Неуспешные ... не входят» = option (в), offered as an alternative |
| Q-04 | ok | ok | D-01 500 min, 499/500 bounds |
| Q-05 | ok | ok | Rec token only. D-09 «Данные карт в логи не записываются» |
| Q-06 | FAIL | ok | Rec (б) no separate retry. D-06: «повторяет списание не более 3 раз ... интервалом 2 часа». D-05: «новая проверка ТР-02 не запускается, пока не завершён повтор ТР-04». D-23: «перед каждым повтором» |
| Q-07 | ok | ok | D-07/D-35/D-26 match. Cross-note: D-07 «(платёж агрегатору или возврат)» vs Q-02 rec «банк не делает возвратов» |
| Q-08 | ok | ok | D-11/D-17/D-20/D-24 tiyn, signed (ts vs updated_at naming only) |
| Q-09 | FAIL (borderline) | ok | Rec «заголовком Idempotency-Key». D-10: «тело: {"request_id": UUID (ключ идемпотентности)...}» (body field, not header) |
| Q-10 | ok | ok | D-08 tariff_type in /v1/balance |

## doc2_B (inconsistent: 2 of 10)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | ok | FAIL | Rec check every 60 min. With Q-07 rec (retry after 2 h, «Повтор отменяется, если ... уже прошла плановая проверка») every retry gets cancelled by an hourly check, so the retry policy never runs |
| Q-02 | ok | ok | Rec hold/capture, 30 s, status query. D-03/D-07/D-33 match. D-19 neutral |
| Q-03 | ok | ok | Rec OTP to the number. D-01 matches |
| Q-04 | ok | ok | Rec masked 6+4. D-05/D-32 match |
| Q-05 | ok | ok | D-04/D-27/D-15 match |
| Q-06 | ok | ok | D-09 matches |
| Q-07 | ok | FAIL | Fixes D-22/D-23/D-18 match the rec. Rationale «шанс успеть до блокировки выше» does not hold with Q-01's hourly check (see Q-01) |
| Q-08 | ok | ok | D-34 bank pays |
| Q-09 | ok | ok | D-21 one client per number |
| Q-10 | ok | ok | D-16/D-14 sum ≥ threshold, threshold 0–5 000 |

## doc3_A (inconsistent: 5 of 10, lenient 3)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | FAIL (borderline) | ok | Rec (а) idempotency «надёжнее, чем сверка статусов». D-13 adds option (б): «перед повтором после таймаута CBS проверяет статус поручения в АБС» |
| Q-02 | FAIL | ok | Rec (а) separate methods, «у клиента нет параметра». D-15: «если он передан и не совпадает с ИИН из токена, возвращается 403» (option б's check). D-14 masks IIN «первые 6», while (а) says IIN is not in logs at all |
| Q-03 | FAIL (borderline) | ok | Rec token + «маскированный номер (первые 6 + последние 4)». D-17: «card_mask (char(4)) — последние 4 цифры» |
| Q-04 | ok | ok | D-16/D-33 auth date in UTC+5 |
| Q-05 | ok | ok | Rec picks no option («Значение выбирает бизнес»). D-08 sets 15 000 ₸ «согласовать», not a conflict. Weak rec |
| Q-06 | ok | ok | D-09 remainder 200 ₸ |
| Q-07 | ok | ok | D-04 netting next month |
| Q-08 | FAIL | ok | Rec «5-го календарного числа с 00:00», "фиксированная дата". D-11: «в 09:00 ... Если 5-е — нерабочий день ... ближайший следующий рабочий день» |
| Q-09 | ok | ok | D-07 round down, 269 ₸ |
| Q-10 | FAIL | ok | Rec (а) excludes additional cards. D-06: «по основным и дополнительным ... картам». D-32: «покупки по дополнительной карте относятся к владельцу счёта ... входят в его лимит» = option (б) |

## doc3_B (inconsistent: 0 of 10)

| Q | C1 | C2 | Evidence |
|---|---|---|---|
| Q-01 | ok | ok | D-04 15 000 ₸ via parameter |
| Q-02 | ok | ok | D-12 remainder 200 ₸ |
| Q-03 | ok | ok | D-07/D-54 Almaty, auth date |
| Q-04 | ok | ok | D-06/D-55 PENDING/FAILED only, key + status query (both in rec) |
| Q-05 | ok | ok | Rec itself is two-way («игнорируется или даёт 403»). D-09 «не принимается ... При несовпадении 403» fits it but is self-contradictory |
| Q-06 | ok | ok | Rec (б) no card in the CRM export. D-10 matches |
| Q-07 | ok | ok | D-01/D-46 reject 4 categories |
| Q-08 | ok | ok | D-03 ≥ 1 000 ₸ |
| Q-09 | ok | ok | D-05 5th working day |
| Q-10 | ok | ok | D-24/D-25 clearing amount, auth-date month. Matches Q-03 |

## Summary

| Report | Inconsistent (strict) | Lenient (no borderline) |
|---|---|---|
| doc1_A | 4 of 10 | 4 |
| doc1_B | 2 of 10 | 2 |
| doc2_A | 5 of 10 | 3 |
| doc2_B | 2 of 10 | 2 |
| doc3_A | 5 of 10 | 3 |
| doc3_B | 0 of 10 | 0 |

A total 14/30, B total 4/30. Every A failure is C1 (a fix written for a different option). Every B failure is C2 (two recs that clash with each other).

## Fix-quality spot check (B reports, 5 questions each)

| Report | Q | Verdict | Why |
|---|---|---|---|
| doc1_B | Q-01 | concrete | Reset rule, same-value case and on/off case all defined |
| doc1_B | Q-03 | weak (incorrect) | D-05 «GET на этот URL возвращает 405» breaks the read method D-02 defines on the same URL |
| doc1_B | Q-04 | concrete | Closed list of messages per code (D-39) |
| doc1_B | Q-06 | weak | D-12 leaves placeholders «<поле>», «<список>» for the classification |
| doc1_B | Q-10 | concrete | p95, 60 s, points, 200 ev/s, logs |
| doc2_B | Q-01 | concrete | Interval, day boundary, success-only count |
| doc2_B | Q-02 | weak (drops state) | «до решения холд не снимается»: no end state or deadline for «неизвестен» (no manual reconciliation, no max status queries, hold expiry ignored) |
| doc2_B | Q-05 | weak (examples only) | D-15 «Добавить таблицу сообщений ... Например: ...» |
| doc2_B | Q-07 | weak (incorrect) | 2 h retry cancelled by any planned check; with the hourly check it never fires |
| doc2_B | Q-10 | concrete | Ranges, step, default, validation text |
| doc3_B | Q-03 | concrete | Period bounds, ready time, window close |
| doc3_B | Q-04 | concrete | Status set + allowed transitions + retry scope (D-55) |
| doc3_B | Q-05 | weak | D-09 «не принимается ... При несовпадении 403» contradicts itself. D-08 «маскируются» with no format |
| doc3_B | Q-07 | weak | D-46 errors «см. метод 3, коды ошибок» is circular. No code for >3 categories, and 200 is both "replace OK" and (per R-35) the validation-error code |
| doc3_B | Q-10 | concrete | Clearing sum, multiple clearings summed, late postings, RRN dedup |

Spot check: 7 of 15 weak (doc1_B 2/5, doc2_B 3/5, doc3_B 2/5).
