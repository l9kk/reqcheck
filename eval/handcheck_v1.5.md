# H2: strict hand-check of the v1.5-rc1 report on the issued spec

Date: 2026-11-27. Read-only check, only this file written. Checked by a separate reviewer agent, not by a human.
Report: `scratchpad/calib_out/task/report.json` (копия в репозитории: `eval/handcheck_v1.5_input.json`; те же 55 замечаний, что в v1.6, кроме текстов исправлений: `python eval/same_findings.py eval/handcheck_v1.5_input.json report/report.json`) (agent "1.4 (v1.5-rc1)", claude-opus-5-5, 55 findings, 10 questions, 70 guard drops). `report.md` lists the same 55 D-ids and 10 Q-ids.
Document: `input/requirements.md`. Golden: `eval/golden.toml` (40 defects, 13 must-find).
Method as in `eval/manual_check.md` and `handcheck_v1.4.md`: open every finding the scorer matched and decide if one of them really describes the golden defect. Graded on my own, v1.4 verdicts not reused.

## Summary

| Metric | score.py | Strict, by hand |
| :--- | :--- | :--- |
| Recall | 40/40 | **39/40** |
| Must-find | 13/13 | **13/13** |
| Critical found | 6/6 | 6/6 |
| Critical found as «критично» | 6/6 | **6/6** (G03 only through one sentence in D-05; its own finding D-30 is «важно») |
| Precision | 49/55 (89%) | 48/55 real (87%), 0 wrong |
| Quotes exact | | 132/132 (117 in findings, 15 in questions) |

New vs v1.4: G11 (GET for a write) is now «критично» (D-05), G34 (no KPI) and G38 (no named owner) are found. Lost: G33 is still not found. Two "specific items" regressed (late push, BPMN vs crossing).

## 1. Golden defects

Found = at least one finding really describes it. Ids are the findings that do; scorer-only matches are left out.

| Id | Must | Verdict | Findings that really cover it | Severity of main finding |
| :--- | :--- | :--- | :--- | :--- |
| G01 | yes | found | D-04 (also Q-02) | критично, right |
| G02 | yes | found | D-01 (also Q-01), D-33 | критично, right |
| G03 | yes | found | D-30; D-05 one sentence («одновременно указаны сохранение и чтение») | D-30 важно, golden критично: low |
| G04 | yes | found | D-06 (also Q-04) | критично, right |
| G05 | yes | found | D-40 | важно, right |
| G06 | yes | found | D-53; also one line in D-05 and D-47 | мелочь, golden важно: low |
| G07 | yes | found | D-36, D-24 | важно, right |
| G08 | yes | found | D-38 (201 not listed and «200 Successful - Created»), D-06 | важно, right |
| G09 | | found | D-07 (also Q-10) | важно, right |
| G10 | | found | D-41 (учёт/сервис расходов, сервис/хранилище настроек, сервис push/уведомлений) | мелочь, right |
| G11 | yes | found | D-05 (GET, query, cache, logs) (also Q-03) | критично, right |
| G12 | yes | found | D-02 (also Q-05), D-30 | критично, golden важно: high, defensible (UI can't load) |
| G13 | | found | D-47 («Prod URL и Swagger не заполнены») | мелочь, golden важно: low |
| G14 | | found | D-11 (2024 offset change, which time field), D-04 | важно, right |
| G15 | | found | D-12 (hold vs clearing, cancel, reversal, fees, currency, partial return) (also Q-06) | важно, right |
| G16 | | found | D-12 («возврат в прошлый месяц после отправки push»), D-16 | важно, right |
| G17 | | found | D-12 (quasi-cash, service payments, by which attribute) | важно, right |
| G18 | | found | D-16 (new threshold at or below accumulated sum) | важно, right |
| G19 | | found | D-16 (off at crossing then on), D-01 (do spends accrue at enabled=0) | важно, right |
| G20 | | found | D-09, D-31, D-35 (reissue, block, close) | важно, right |
| G21 | | found | D-37, D-08 | важно, right |
| G22 | | found | D-08 (error texts, loading, server error, after success) | важно, right |
| G23 | | found | D-18 (which sum), D-16 («Не задан текст push») | важно, right |
| G24 | | found | D-23 (which point, share, load), D-07 | важно, right |
| G25 | yes | found | D-25 (units, enabled, refund link, retention 13 months) | важно, right |
| G26 | | found | D-27 (key, window) (also Q-08), D-10 (order) | важно, right |
| G27 | | found | D-32 (state in store or in response, which HTTP code) | важно, right |
| G28 | | found | D-50 | мелочь, right |
| G29 | | found | D-37 | важно, golden мелочь: high, fine |
| G30 | | found | D-35 (PAN, token or internal id, no charset) | важно, golden мелочь: high, fine (main point is reissue) |
| G31 | yes | found | D-03 | критично, right |
| G32 | | found | D-29 (full rule-by-rule coverage list) | важно, right |
| G33 | | no | Nothing asks where «Итог 50 000 ₸» of criterion 1 is observed. D-28 is about its preconditions. Scorer matched D-29 by coincidence |  |
| G34 | | found | D-07 («нет измеримого показателя... доля клиентов, включивших уведомление, доля доставленных push») | важно (merged), golden мелочь |
| G35 | yes | found | D-47 (version/date, checklist, approvers, no tracker task) | мелочь, golden важно: low |
| G36 | | found | D-48 (feature flag, rollback, empty checklist row) | мелочь, golden важно: low |
| G37 | | found | D-49 (lock screen, log masking, IS checklist row empty), D-05 (params in logs) | мелочь, golden важно: low |
| G38 | | found | D-47, one sentence: «В паспорте не указаны конкретные владельцы» (quotes line 17). Authors at 113-114 not named | мелочь, right |
| G39 | | found | D-42 (BPMN one branch), D-19, D-22 (failures, retry) | мелочь, right |
| G40 | | found | D-13 (Ф-3 month vs Ф-2 Almaty month, UTC example) | важно, golden мелочь: high, fine |

Strict recall: 39/40. Must-find strict: 13/13.
Severity of the main finding vs golden: 28 same, 6 lower (G03, G06, G13, G35, G36, G37), 5 higher (G12, G29, G30, G34, G40).

## 2. Precision

### The 6 findings the scorer did not match

| Id | Class | Note |
| :--- | :--- | :--- |
| D-15 | real, overlaps G20 | counter and threshold per card or per account (main and supplementary cards) |
| D-21 | real, not in golden | wallet and e-commerce tokens not mapped to card_id |
| D-34 | real, not in golden | API schema has no source for card owner, status and currency |
| D-51 | low value | rule 2 repeats step 4 |
| D-54 | low value | generic "list the 401 cases" API checklist item |
| D-55 | real, not in golden | state after 500 and whether retry is safe |

Split: 4 real, 0 duplicates, 2 low value, 0 wrong.

### Whole report, 55 findings

| Class | Count | Ids |
| :--- | :--- | :--- |
| Main point is a golden defect | 36 | D-01..D-13, D-16, D-18, D-19, D-22, D-23, D-25, D-27, D-29..D-32, D-35..D-38, D-40..D-42, D-47..D-50, D-53 |
| Real, not in golden (or extends one) | 12 | D-14, D-15, D-17, D-20, D-21, D-26, D-28, D-33, D-34, D-39, D-46, D-55 |
| Duplicate | 1 | D-24 (units are in D-25, types in D-36, month total in D-25) |
| Low value (style, generic checklist) | 6 | D-43, D-44, D-45, D-51, D-52, D-54 |
| Wrong | 0 | |

Strict precision: 48/55 = 87%.

Real, not in golden, one line each: D-14 race between two events of one card (two push, lost update); D-17 mid-month launch, no backfill; D-20 no source for the last four digits; D-26 no type for tiyn sums, 32-bit overflow; D-28 criteria 1 and 3 lack enabled=1, "no push yet", and "no push" as result; D-33 does saving the same threshold reset the push flag, concurrent saves; D-39 no catalog of `message` texts; D-46 no delete, default state unreachable.

Scorer matches that are only a coincidence of line and keyword (the finding is real, but about something else): D-29 for G33, D-05 for G13, D-20 for G37, D-09 for G11, D-43/D-44 for G16, D-44/D-45 for G26, D-52 for G28, D-39 for G07.

Internal contradictions between findings (not counted as wrong, but a reader gets two answers):
- D-06 fix: amount out of range returns 200 + ERROR. D-32 fix: same case returns 400 + ERROR.
- D-12 fix: count by clearing. Q-06 default: count at hold.
- D-27 fix: dedup window 13 months. Q-08 options: 35 days.

## 3. Severity

The report has 6 «критично»: D-01, D-02, D-03, D-04, D-05, D-06. All 6 are real blockers. The verdict text says 6, matches.

Rated higher than golden: D-02 «критично» for G12 (golden «важно»). Defensible: without a read method the screen can't be filled. Not counted as an error.

Rated too low:

| Finding | Report | Should be | Why |
| :--- | :--- | :--- | :--- |
| D-30 Description save + read | важно | критично | Golden G03 is critical and must-find. Crit-as-crit holds only because D-05 repeats it in one sentence |
| D-53 Content-Type with empty body | мелочь | важно | Golden G06 is must-find «важно». Same miss as D-63 in v1.4 |
| D-47 version, checklist, approvers, Prod URL, Swagger | мелочь | важно | Golden G35 (must-find) and G13 are «важно». Same miss as D-61 in v1.4 |
| D-48 no rollback / feature flag | мелочь | важно | Golden G36 «важно» |
| D-49 IS: lock screen, logs | мелочь | важно | Golden G37 «важно» |

The G11 miss of v1.4 is fixed: D-05 is «критично». The two must-find under-ratings (G06, G35) are unchanged.

## 4. Quotes

All 117 finding quotes and 15 question quotes are exact substrings of the cited lines (script check, whitespace normalised). Hand spot-check of 15 random ones (seed 20261127): 15/15 exact.

D-05:109, D-34:130, D-38:162, D-19:43, D-22:46, D-36:157, D-47:110, D-31:189, D-35:39, D-09:105, D-22:43, Q-01:40, D-05:108, D-29:63, D-05:103.

## 5. Specific items

| Item | Result | Where |
| :--- | :--- | :--- |
| Monthly reset of the "push sent" flag (lines 39, 49) | found | D-13: flag per card+month or one flag reset, and when the month starts for Ф-3 |
| Push later than 1 minute: drop or send late (46) | no | Nothing. D-48 only adds an alert above 60 s. v1.4 had it in D-30 |
| BPMN «при достижении» vs Ф-3 crossing from below (34, 39) | partly | D-42 fix writes the crossing condition («до операции < порога и после ≥ порога»), but no problem text names the mismatch. v1.4 had it in D-10 |
| Spend service never learns about threshold change or disable | partly | D-41 asks whether the spend service gets a new threshold at once or from another copy. D-33 asks whether saving resets the flag. No finding links the two: Ф-4 needs a signal to the spend service |
| Retention of history and dedup keys (49, 52) | found | D-25: retention 13 months. D-27: dedup window 13 months. Q-08 says 35 days (conflict) |
| Card holder in Ф-1 vs owner in the API | found | D-09: «держатель» vs «владелец» (105) vs «клиент» (118), supplementary card. D-15 adds the account view |
| GET for a write: severity | found, right | D-05 «критично». Q-03 asks the architect |

## 6. Questions

All 10 tie to a real gap: 8 to golden defects, 2 to real non-golden ones. Each has 2-3 concrete options with a test and a default with a reason. Five have a problem.

| Id | Ties to | Options / default | Problem |
| :--- | :--- | :--- | :--- |
| Q-01 | G02 (D-01) | 3 options, default 2 (reset only on a different value) | ok |
| Q-02 | G01, G14, G40 | 2 options, default by purchase date, UTC+5 | ok |
| Q-03 | G11, G03 | PUT /alerts/limit or POST; default PUT | O1 test «GET на этот URL возвращает 405» clashes with Q-05 default `GET /alerts/limit` (read method) |
| Q-04 | G04, G27 | all errors 400, or 400 + 200/ERROR; default all 400 | default contradicts D-06 fix (200/ERROR for out of range) |
| Q-05 | G12 | one GET read method or two; default one | see Q-03 |
| Q-06 | G15 | hold or clearing; default hold | default contradicts D-12 fix (clearing) and changes an explicit Ф-2 word («проведённые») |
| Q-07 | D-15 (real, not golden) | per card or per account; default per card | ok |
| Q-08 | G26 | key = operation id, or operation id + event type; default 2 | reason says «вопрос 3», means Q-06. 35-day key retention conflicts with D-27 (13 months) |
| Q-09 | D-14 (real, not golden) | serial per card or atomic update; default serial | ok |
| Q-10 | G09, G24 | p95 service-to-service or p99 from authorization; default p95 | minor: load 200 events/s vs 100 events/s in D-23 fix |

Sense: 10/10. Clean (no conflict with other questions or findings): 5/10 (Q-01, Q-02, Q-07, Q-09, Q-10 minor).

## 7. v1.4 vs v1.5

| Metric | v1.4-rc1 | v1.5-rc1 |
| :--- | :--- | :--- |
| Findings / questions | 65 / 10 | 55 / 10 |
| Recall, score.py | 38/40 | 40/40 |
| Recall, strict | 37/40 | **39/40** |
| Must-find, strict | 13/13 | 13/13 |
| Crit as «критично» | 5/6 (G11 важно) | 6/6 (G03 via D-05 sentence) |
| Must-find under-rated | 3 (G11, G35, G06) | 2 (G35, G06) + G03 main finding |
| Precision, score.py | 56/65 (86%) | 49/55 (89%) |
| Precision, strict | 60/65 (92%) | 48/55 (87%) |
| Golden / real / dup / low / wrong | 38 / 22 / 1 / 4 / 0 | 36 / 12 / 1 / 6 / 0 |
| Quotes exact | 149/149 | 132/132 |
| Not found (strict) | G33 partly, G34 partly, G38 no | G33 no |
| Specific items (7) | 6 found (GET under-rated), 1 partly | 4 found, 2 partly, 1 no |
| Questions with a conflict | not checked | 5/10 |

Net: recall and critical severity up; fewer real non-golden extras (22 to 12) and more low-value items (4 to 6), so strict precision down 5 points. Merging produces cross-finding contradictions (D-06/D-32, D-12/Q-06, D-27/Q-08, Q-03/Q-05) that v1.4 did not show.
