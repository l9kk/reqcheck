# Design: reqcheck HTML report

## Direction
A reviewed spec with margin notes. Graphite ink on paper, quiet chrome, one red pen for what blocks work.
The document's own words, pulled out as quote bubbles next to each defect, are the one rich moment.

- Product: reviews a requirements document and shows each defect next to the exact lines it quotes, for QA leads, analysts and developers.
- Character: exact, calm, a little editorial.
- World: a printed spec with a reviewer's margin notes.
- Moment: quote bubbles (the document's words, with a line tab) and the verdict line.
- Signature: the line tab, a small mono number like `39`, used the same way in the document gutter and in every quote bubble. Clicking it shows that line.

## Constraints
One self-contained HTML file. No web fonts, no CDN, no images: it must open offline on Windows and macOS.

## Color (tokens)
Light: --bg #f6f6f4, --surface #fff, --raise #f0f0ec, --ink #1b1d1f, --ink-2 #42474d, --muted #6b7178,
--line #e2e2dd, --accent #2a55c4 (links, selection), --accent-soft #ecf0fb.
Dark: --bg #121315, --surface #1a1b1e, --raise #24262a, --ink #e6e7e8, --ink-2 #c3c6ca, --muted #979ca3,
--line #2d2f33, --accent #8fb0ff, --accent-soft #1d2537.
Severity (text color, never a filled pill): критично --crit #b3261e / #ff9e95, важно --major #8a5a00 / #e8bd62,
мелочь --minor = --muted. Verdict: ok #1e6b3a / #86d19e.
Only критично gets a colored bar in the document gutter; other noted lines get a neutral bar.

## Type
System UI stack for everything, mono stack (ui-monospace, Consolas) for IDs and line tabs.
Sizes 12 / 13 / 14 / 15 / 18 / 22. Weights 400, 500, 600. Sentence case, no tracked caps, tabular numbers.

## Layout
Max width 1600. Spacing on a 4px grid: 4 / 8 / 12 / 16 / 20 / 24 / 32.
Two panes on desktop (findings, document), stacked on phones (< 768px). Text measure about 75ch.
Radius: controls 6, bubbles 10 (top-left 2, it points at the source), cards 10.
Cards only where an item stands alone (questions). Findings are rows separated by hairlines.

## Motion
None besides scroll to the quoted line. Smooth scroll is off with prefers-reduced-motion.

## Components
- Finding row: mono ID, severity as colored text with a dot, title, quote bubbles, "Подробнее" disclosure.
  Selected row: --accent-soft background and a 2px accent edge. No underline, no bold change.
- Quote bubble: --raise background, line tab first, then the quoted text in «».
- Question card: one width for the whole card (860px). Options are a plain list; the recommended one has an
  --accent-soft background and a "рекомендуем" tag on its first line.
- Document line: highlighted lines use --accent-soft with an accent number, not yellow.
- Focus: 2px accent outline on every interactive element.

## Don'ts
Filled severity pills in lists, underlined links in quotes, " · " separators between tags, yellow highlights,
teal fills, borders around every option, repeated "Также:" bullets.
