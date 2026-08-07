# Bellwether — Brand Guidelines

_The brand system for Bellwether, a fictional retail-technology company. Separate
from any personal brand. v1._

## The name

**Bellwether** — a bellwether is the leading indicator, the one that moves first
and the flock follows. It says exactly what the product does: read the early signal
in a store's data and act before it becomes a problem.

**Tagline:** _The leading indicator for every store._

## Positioning

Bellwether is an **AI operating system for retail operations**. It unifies data
scattered across POS, Microsoft 365, inventory, and vendor systems (via MCPs and
APIs), detects what's off, forecasts what's coming, and tells a busy store or
district manager what to do next. Not a dashboard that reports the past, a copilot
that acts on the present.

## Personality

Calm, foresighted, dependable, quietly intelligent. Bellwether is the composed voice
in a busy store, never loud, never alarmist, always one step ahead. Five principles
settle anything a rule below doesn't:

1. **Prescriptive, not passive** — every element answers "what do I do next?"
2. **Calm over crowded** — show what matters now, hide the rest behind a tap.
3. **One signal at a time** — amber marks the single thing that needs a look.
4. **Honest about certainty** — always show how sure the AI is.
5. **Accessible always** — real contrast, never color alone, works on a phone.

## Color

Deep indigo-slate for trust and calm, warm parchment for a human ground, and a
single harvest-amber "signal" used sparingly for the one thing that needs attention.

| Token | Light | Dark | Use |
|---|---|---|---|
| Brand (Indigo Slate) | `#243B53` | `#7FA8D9` | Primary marks, bars, links, headings accent |
| Signal (Harvest Amber) | `#E0872A` | `#E9A24E` | The one accent: logo dot, key highlight, sample chip |
| Signal text | `#9A5B12` | `#E9A24E` | Amber used as *text* (deeper for contrast) |
| Paper (Parchment) | `#F6F4EE` | `#0F141A` | Page ground |
| Card | `#FFFFFF` | `#171F29` | Surfaces |
| Ink | `#1A2430` | `#E8EBEF` | Primary text |
| Muted | `#667085` | `#94A0AE` | Secondary text, captions |
| Hairline | `#E6E1D6` | `#263140` | Borders, dividers |

**Status (reserved, never used as decoration):** good `#2E7D5B`, warning `#B7791F`,
serious `#C2410C`, critical `#B42318`. Always paired with an icon or arrow and a
label, never color alone. Body text and status pairings clear WCAG AA.

## Type

- **Headings & wordmark:** a serif (`ui-serif, Georgia`). The editorial serif gives
  Bellwether the feel of a trusted publication of record, the "almanac" of the store.
- **Interface & body:** a clean sans (`Inter, system-ui`).
- **Numbers, labels, code:** a monospace (`ui-monospace, JetBrains Mono`), with
  tabular figures so KPIs line up. Labels are uppercase with wide tracking.

## Logo & mark

- **Wordmark:** _Bellwether_ set in the serif, tight tracking.
- **Mark:** a rounded indigo tile with a single amber dot in the upper-right, the
  "leading signal." Works as an app icon or favicon at small sizes.
- **Don't:** recolor outside the palette, add gradients or shadows to the mark,
  stretch it, or set the wordmark in the UI sans.

## Iconography & imagery

- Category and product tiles use a simple glyph on a soft indigo tile (calm,
  instantly readable across tech-literacy levels). In production, real product
  photography flows in from the product API and sits in the same tile.
- No stock-photo clutter. Imagery earns its place or it's left out.

## UI principles (how the product feels)

Grounded in current retail-ops and AI-copilot UX research:

- **Lead with the headline.** The top of the screen is one prescriptive sentence:
  the single most important thing to do right now.
- **Progressive disclosure.** Summary first, detail on tap, raw data last. Three
  alerts show by default; the rest are one tap away.
- **Ambient copilot.** The assistant suggests in context and answers in plain
  language, with its reasoning available but folded away.
- **Confidence affordances.** Every AI output shows a confidence signal; low
  confidence is visibly muted.
- **Glanceable and calm.** Generous whitespace, four KPIs above the fold, one
  primary action per card.

## Data visualization

- One measure per axis, never dual-axis. Sales-vs-plan uses a **diverging** encoding
  (green over plan, red under, neutral center), with the sign and value always
  labeled so it never relies on color.
- Thin marks, recessive gridlines, tabular numbers, hover for detail. Sparklines
  carry trend on KPI tiles.
- Status colors are reserved for state, never reused as chart series colors.

## Voice

Plain, direct, composed. Point first, then the number, then the next step. Never
hype, never alarmist, never corporate filler. "Lawn & Garden is 28% under plan,
about $14,900. Check seasonal sell-through and consider a markdown," not "Sales are
trending negatively this period."
