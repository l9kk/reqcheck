# H1: strict hand-check of the rc1 report on the issued spec

Date: 2026-11-27. Read-only check, only this file written.
Report: `report/report.json` (agent 1.4, v1.4-rc1, claude-opus-5-5, 65 findings, 10 questions).
Document: `input/requirements.md`. Golden: `eval/golden.toml` (40 defects, 13 must-find).
Method as in `eval/manual_check.md`: open every finding the scorer matched and decide if one of them really describes the golden defect.

## Summary

| Metric | score.py | Strict, by hand |
| :--- | :--- | :--- |
| Recall | 38/40 | **37/40** |
| Must-find | 13/13 | **13/13** |
| Critical found | 6/6 | 6/6 |
| Critical found as «критично» | 6/6 | **5/6** (G11 is «важно») |
| Precision | 56/65 (86%) | 60/65 real (92%), 0 wrong |
| Quotes exact | | 149/149 (133 in findings, 16 in questions) |

For comparison, v1.3 on the same document: 37 auto, 36 strict. rc1 adds G10 (component names).

## 1. Golden defects

Found = at least one finding really describes it. Ids are the findings that do; scorer-only matches are left out.

| Id | Must | Verdict | Findings that really cover it |
| :--- | :--- | :--- | :--- |
| G01 | yes | found | D-01 (also Q-01) |
| G02 | yes | found | D-02, D-15 |
| G03 | yes | found | D-04 (first sentence), D-43 |
| G04 | yes | found | D-05 |
| G05 | yes | found | D-54, D-50 |
| G06 | yes | found | D-63 |
| G07 | yes | found | D-49 |
| G08 | yes | found | D-05, D-50, D-44 |
| G09 | | found | D-06, D-30 |
| G10 | | found | D-56 (учёт/сервис расходов, push/уведомлений), D-12 (сервис/хранилище настроек) |
| G11 | yes | found | D-43 only. D-04 matched just because its fix proposes a new `GET /alerts/limit` |
| G12 | yes | found | D-04 |
| G13 | | found | D-61 |
| G14 | | found | D-18, D-01 |
| G15 | | found | D-14, D-17 |
| G16 | | found | D-14, D-15, D-21 |
| G17 | | found | D-14, D-17 |
| G18 | | found | D-25, D-19 |
| G19 | | found | D-19, D-25, D-13 |
| G20 | | found | D-11, D-12, D-24 |
| G21 | | found | D-48 |
| G22 | | found | D-08 (texts, initial and success state, 401/404/500). Loading state not named |
| G23 | | found | D-29, D-19 |
| G24 | | found | D-30, D-31 |
| G25 | yes | found | D-33, D-34 |
| G26 | | found | D-37, D-35 |
| G27 | | found | D-46, D-05 |
| G28 | | found | D-62 |
| G29 | | found | D-48 |
| G30 | | found | D-24 (PAN, token or internal id, no charset) |
| G31 | yes | found | D-03 |
| G32 | | found | D-39 |
| G33 | | partly | D-41 asks where the counter is checked, but for criterion 3 (line 65). Nothing asks where «Итог 50 000 ₸» of criterion 1 is seen |
| G34 | | partly | D-30 says «Цель не измерима», but about the NFR target. No business KPI is asked for |
| G35 | yes | found | D-61, D-59 (no Jira) |
| G36 | | found | D-42 |
| G37 | | found | D-27, D-43, D-47 |
| G38 | | no | Nothing on placeholder roles and authors (lines 17, 113, 114) |
| G39 | | found | D-10, D-07, D-26 |
| G40 | | found | D-19 (push limit by month of purchase or of sending), D-21 |

Scorer misses that a finding really covers: none new. G40 is found by D-19, which the scorer did not list, and G33 is closer to D-41 than to the scorer's empty match.

Strict recall: 37/40 (partly does not count). Must-find strict: 13/13.

## 2. Precision

### The 9 findings the scorer did not match

| Id | Class | Note |
| :--- | :--- | :--- |
| D-16 | real, not in golden | launch mid-month, no backfill of the current month |
| D-20 | real, not in golden | «клиент получает push» is not testable, only hand-off to the push service is |
| D-23 | real, overlaps G20 | main and supplementary cards on one account, several devices |
| D-28 | real, not in golden | wallet tokens (DPAN) not mapped to the card |
| D-38 | real, not in golden | criterion 1 lacks enabled=1 and "no push yet this month" |
| D-41 | real, not in golden | criterion 3 does not state "no push" as the expected result |
| D-53 | real, not in golden | state after 500 and whether retry is safe |
| D-57 | low value | generic "no priority" checklist item |
| D-65 | real, not in golden | what step 1 checks in the session and what it returns |

Split: 8 real, 0 duplicates, 1 low value, 0 wrong.

### Whole report, 65 findings

| Class | Count | Ids |
| :--- | :--- | :--- |
| Main point is a golden defect | 38 | |
| Real, not in golden (or extends one) | 22 | D-09, D-12, D-16, D-20, D-22, D-23, D-26, D-28, D-32, D-35, D-36, D-38, D-40, D-41, D-44, D-45, D-47, D-51, D-52, D-53, D-55, D-65 |
| Duplicate | 1 | D-34 (its whole content is also in D-33) |
| Low value (style, generic checklist) | 4 | D-57, D-58, D-60, D-64 |
| Wrong | 0 | |

Scorer matches that are only a coincidence of line and keyword (the finding is real, but about something else): D-22, D-32, D-36, D-45, D-55, D-58, D-60, D-64.

## 3. Severity

The report has 5 «критично»: D-01, D-02, D-03, D-04, D-05. All 5 are real blockers. None is over-rated.

Rated too low:

| Finding | Report | Should be | Why |
| :--- | :--- | :--- | :--- |
| D-43 GET for a write | важно | критично | Golden G11 is critical and must-find. Same miss as A04 in v1.3 |
| D-61 version, checklist, approvers empty | мелочь | важно | Golden G35 is must-find «важно» |
| D-63 Content-Type with empty body | мелочь | важно | Golden G06 is must-find «важно» |

The scorer line "Critical found as critical 6/6" is inflated: it counts G11 through D-04 («критично»), whose only GET is in its proposed fix.

## 4. Quotes

All 133 finding quotes and 16 question quotes are exact substrings of the cited lines (script check). Hand spot-check of 15 random ones (seed 20261127): 15/15 exact.

D-04:29, D-36:43, D-42:19, D-17:38, D-21:39, D-39:65, D-52:121, D-32:46, D-37:38, D-09:29, D-20:39, D-61:68, D-04:26, D-26:43, D-04:130.

## 5. Specific items

| Item | Result | Where |
| :--- | :--- | :--- |
| Monthly reset of the "push sent" flag (lines 39, 49) | found | D-21: when and by which time the counter and flag reset, new record or reset. D-02 covers reset on threshold change |
| Push later than 1 minute: drop or send late (46) | found | D-30, one sentence: «Не описано, что делать при превышении: отправлять с опозданием или нет» |
| BPMN «при достижении» vs Ф-3 crossing from below (34, 39) | found | D-10, one sentence in the problem |
| Spend service never learns about threshold change or disable | partly | D-26 and D-29 say the sequence does not fetch enabled or check the switch. No finding says the spend service gets no signal that the threshold changed, which Ф-4 needs to reset the flag |
| Retention of history and dedup keys (49, 52) | found | D-33: no retention period (fix proposes 13 months). D-37: dedup window not set, idempotency key not named |
| Card holder in Ф-1 vs owner in the API | found | D-11: «держатель» vs «сессия владельца карты» (line 105), differ for a supplementary card. D-23 adds the account view |
| GET for a write: severity | found, under-rated | D-43 «важно», golden «критично». Q-06 asks the author about it |
