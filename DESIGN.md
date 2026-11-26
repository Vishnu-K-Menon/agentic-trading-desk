# Design: Agentic Trading Desk

Recorded from the built dashboard (`frontend/src/styles.css` is the source of truth).

## The idea

A league table printed on paper. The floor is a competition, so the first screen is the
standings, with the S&P 500 placed in the order as one more competitor. Ink on a stone ground;
the chrome carries no colour. Colour is kept for data: one hue per trader on the charts and beside
its name, green or red on a change, and three pale pills for the risk desk's decisions.

Reference studied: live AI-trading leaderboards (TradeRank, Alpha Arena, sandx) and consumer
investing apps. Taken from them: standings first, the benchmark inside the ranking, one colour per
competitor on the equity curves. Deliberately not a trading terminal.

Checked with the taste skill's inspector at 1440, 768 and 390px: 0 failures and 0 warnings on the
floor, trader and controls pages.

Mode: Operate. Style dealt by the taste skill: achromatic ledger, light by default, with a
true-neutral dark theme.

## Tokens

| Role | Light | Dark |
| --- | --- | --- |
| Ground | `#f4f3f1` | `#0c0c0b` |
| Surface (cards) | `#ffffff` | `#151514` |
| Active (nav pill, chips) | `#e7e5e1` | `#262624` |
| Border / rule / control | `#e2e0db` / `#eeece8` / `#cfccc5` | `#262624` / `#1e1e1c` / `#45443f` |
| Text / muted | `#0e0e0c` / `#5c5b56` | `#f2f2f2` / `#a8a8a8` |
| Primary action | `#141412` on white label | `#f2f2f2` with black label |
| Positive / negative | `#1f7a3d` / `#c4242a` | `#4cc27a` / `#f0707a` |
| Warren / George / Ray / Cathie | `#1d5fbf` `#a85a00` `#0b7b78` `#a32d7a` | `#6ea8f7` `#e2a24c` `#43c4bd` `#e581c4` |
| Benchmark line | `#77756f`, dashed | `#8f8d85`, dashed |

Radius: cards 8px, controls 6px, pills full. One gap (12px) in both directions. Card padding 20px.
No shadow on anything at rest; only the chart tooltip and the toast float.

## Type

Geist for everything; Geist Mono only for literal commands. Sizes: title 24, section 16, body 14,
small 12, headline figure 30, other figures 22. Tabular figures everywhere. Sentence case, no
tracked capitals. Bold weight is kept for money and names.

## Layout

- Open-plane shell: a 244px labelled sidebar on the page ground with one hairline, no top bar. The
  sidebar names the product, lists the four traders with their colour, and shows the floor's state
  (market, price basis, next round).
- Floor: title and one finding sentence, then two rows that each end level: standings beside the
  risk desk's three latest decisions, and the growth chart beside the latest appraisals. The chart
  fills the height of its row.
- Trader: a divided strip of five figures with portfolio value leading, underline tabs, then the
  tab's content.
- Controls: settings in two columns, a label and description beside its panel; the destructive
  reset is last and needs a typed confirmation.
- Below 1240px the rail moves under the main column; below 900px the sidebar folds into a 48px top
  bar with a full-screen menu; tables shed their secondary columns at 1080px and 640px.

## Rules that hold

- The benchmark is a row in the standings and a dashed grey line on the chart, never a hue.
- Zero is printed as zero and in grey; a missing figure is a dash.
- Figures are right-aligned with fixed decimals; every change carries its sign.
- Charts: straight 2px lines, four or five faint gridlines with round ticks, no axis lines, a label
  at the end of each line, a cursor that reads every series at once.
- Loading is flat grey bars at the final layout; an empty block keeps its frame and says what will
  appear there; an unreachable backend says so in place and keeps the last figures.
- Motion is feedback only: 140ms press (scale 0.97), 150ms colour changes, a toast that arrives in
  220ms and leaves in 150ms, a phone menu that fades in over 200ms, all on one strong ease-out
  (`cubic-bezier(0.23, 1, 0.32, 1)`). Chart tooltips and tab changes do not animate.
- Hover styles apply only with a real pointer (`hover: hover` and `pointer: fine`); touch gets a
  pressed state instead. Reduced motion keeps colour and opacity changes and drops movement.
- Everything from the API is escaped before it reaches the page.
