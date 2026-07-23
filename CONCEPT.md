# Artist Exchange — Concept

**Product truth: what we're building and why.** For how it gets built — schema, formulas, phases — see [`PLAN.md`](./PLAN.md).

## One-liner

A play-money market where users buy and sell "shares" of musical artists, betting on whether their popularity will rise. Part Robinhood, part fantasy sports — but the underlying fundamental is a real, public popularity index rather than a balance sheet or a one-time event.

## The insight

Music fans already predict breakouts informally — "I knew them before they blew up" — but there's nowhere to turn that instinct into a trackable, competitive record. Existing options are either pure gambling (no skill signal) or pure stats-following (no stakes). Nothing lets you bet on *trajectory*.

## The core bet

Price is anchored to a real popularity index computed from public data, and drifts toward that index over time. So buying an artist *before* the real-world data catches up is provably rewarded.

That single property is what separates this from a meme-stock app (pure vibes, no skill) and from a leaderboard (stats with no stakes). It's what makes "I called it" mean something — and everything else in the product exists to serve it.

Four reasons this should be sticky:

1. **Skill is real and provable** — being early pays, and the record shows it.
2. **Discovery becomes a cheap lottery ticket** — "fastest growing, under $10" turns finding an artist into a game with stakes, which is inherently shareable.
3. **Layered reasons to return** — price moves continuously, the index updates nightly, breakouts play out over months.
4. **New users can still win** — see Tournaments, below.

## V1 scope

**Artist universe** — a curated list in the low hundreds, in two tiers:

- **Growth tier** — emerging artists plausibly about to break out. This is where the talent-scout mechanic lives, and it's the actual product.
- **Blue-chip tier** — a smaller set of household names. They won't move much, but they let a new user immediately understand what the app is, and they widen the top of the funnel beyond music-discovery obsessives.

The contrast is itself a feature: "biggest movers" will almost always be growth tier, which teaches the product's identity without a tutorial. Curation starts editorial; user submission with approval can come later.

**Trading** — buy and sell long positions in play money. No margin, no leverage, no order book; an AMM means there's always a counterparty. Every new user starts with a fixed play-money balance.

**Discovery** — feed views that double as marketing hooks: "fastest growing under $10," "biggest movers," "new listings." Plus the per-artist chart showing market price against the index fair-value line — the fair-value overlay is off by default and user-toggled, so it doesn't overstate its own authority or spoil the discovery moment of watching a pick's line pull ahead, but revealing it is the product's signature visual and is worth investing in early.

**Leaderboards** — two, deliberately:

- *Portfolio return* — straightforward, but structurally favors whoever started earliest.
- *Talent Scout* — ranks users on gains from positions opened while an artist was still small. This is the one that matters. It measures discovery skill rather than capital or timing luck, and it's the leaderboard the whole product is arguing for.

## Deferred

Not "cut" — sequenced. Engineering seams for each already exist (see `PLAN.md`).

| | Why it waits |
|---|---|
| **Short selling** | Roughly doubles position accounting and is where a play-money economy breaks. Few users short in their first session. |
| **Tournaments** | Time-boxed contests with fresh equal balances — the fix for "the leaderboard is permanently owned by day-one users." Cheap to build on existing infrastructure, but it's a *retention* feature: build it once there's retention worth protecting. |
| **Daily streaks / balance safety net** | Engagement machinery. Premature before the core loop is proven. |
| **Richer data** | Licensed aggregators (Chartmetric, Soundcharts) combine TikTok, YouTube, and playlist signals into one hard-to-game score. The natural upgrade once revenue supports it. |
| **Mobile app** | Web ships faster and iterates faster. Revisit after the loop is validated. |
| **Deep social** | Following, comments. A shareable portfolio card is a cheap virality lever worth doing first. |

## Risks to watch

- **Curation quality is the whole product.** If the growth tier doesn't contain real breakouts, nothing else matters. This is an editorial problem, not an engineering one — and it's the closest thing to a moat early on.
- **Data quality.** Last.fm skews older, more indie, more Western, which makes it weakest exactly where the product needs it most: emerging artists. It's also gameable — see `PLAN.md` Phase 3 for the manipulation defense. A second signal is the real fix.
- **Economy inflation.** With no real money, balances drift upward over time and leaderboards lose meaning. Trading fees, starting balances, and any future top-ups have to be tuned against each other.
- **Right of publicity.** Real artists' names in a trading product, even play-money, warrants a clear "not affiliated with or endorsed by" disclaimer. V1 uses generated avatars rather than artist photography.

## Path to real money (future, not v1)

Worth naming because it shaped the play-money-first decision. A literal "shares of a person" model is a securities and right-of-publicity problem — artists aren't consenting, reporting entities the way companies are. The realistic path is closer to Kalshi's: CFTC-regulated **event contracts** on public data thresholds ("will Artist X's index exceed Y by date Z"), not open-ended equity-style shares.

That's a legal undertaking separate from the engineering, which is exactly why play-money v1 is the right sequencing: prove the engagement loop first, then scope the compliance path deliberately.
