# Artist Exchange — Concept Doc

## One-liner

A play-money market where users buy, sell, and short "shares" of musical artists, betting on whether their popularity will rise or fall — part Robinhood, part Kalshi, but the underlying "fundamental" is a real, public popularity index rather than a company balance sheet or a one-time event.

## Problem / insight

Music fans already predict breakout artists informally ("I knew them before they blew up"). There's no venue that turns that instinct into a trackable, competitive, social record — and no lightweight way to bet on _trajectory_ (an artist trending up or down) the way sports betting lets you bet on outcomes. Existing options are either pure gambling (no skill signal) or pure stats-following (no market, no stakes).

## Core mechanic: index-anchored hybrid pricing

This is the crux of the product, so it's worth stating precisely:

- Every listed artist has an **Index Score**: a composite of real, public data (starting with Last.fm listener/scrobble counts and their week-over-week growth rate — see Data Sources below).
- Every artist also has a **Market Price**, set by user trading via a simple AMM (bonding curve): buys push price up, sells and shorts push it down.
- On a regular cadence (e.g. nightly), Market Price is nudged some percentage toward the current Index-derived "fair value."

Why this matters: it means price is _not_ pure vibes (like a meme stock) and _not_ just a mirrored stat (which would be a leaderboard, not a market). Users who buy an artist before the real-world data catches up are rewarded when the price reverts toward the new, higher fair value. That's the "talent scout" skill the whole product is built around, and it's what makes the leaderboards in this doc meaningful rather than arbitrary.

## Data sources (v1)

- **Spotify is not viable**: Spotify has locked down the developer platform (app approval is now required and largely restricted to established use cases, and several previously-public fields — including the `popularity` score — have been pulled back or made unreliable for new apps). Not a foundation we can build on for v1.
- **Last.fm API** (free, no approval gate — see [`artist.getInfo`](https://www.last.fm/api/show/artist.getInfo)): pulls `listeners` (unique listener count) and `playcount` (total scrobbles) per artist. Last.fm doesn't expose historical trend data itself, so we snapshot these values on our own cadence (e.g. nightly) and derive week-over-week growth rate ourselves — that growth rate plus the absolute listener count are the two inputs to the Index Score.
- **Future**: once the core loop is validated and revenue can support a paid data subscription, upgrade to a licensed aggregator like **Chartmetric** or **Soundcharts** — these combine cross-platform signals (TikTok, Instagram, YouTube, playlist adds) into a single resistant-to-gaming popularity score, and are the natural v2 data upgrade.

## V1 scope

### Artist universe

- Curated list (low hundreds), split across two tiers:
  - **Growth tier** (the core bet): emerging/mid-tier artists plausibly about to break out — this is where the talent-scout mechanic and "under $10" discovery framing do their work.
  - **Blue-chip tier**: a smaller set of mega-stars (mainstream, universally recognized names). These won't move as dramatically, but they give new users something familiar to trade on day one, lower the barrier to "I get what this app is" on first open, and drive top-of-funnel appeal beyond the music-discovery niche.
  - This mirrors large-cap vs. small-cap framing in real markets, and gives the discovery feed a natural contrast: "movers" will almost always be growth-tier, which itself reinforces the product's identity once a new user notices the pattern.
  - Curation can start manual/editorial and later be opened to user submission + admin approval.

### Trading

- Buy/sell long positions in play money.
- **Short-selling, simplified**: user stakes an amount betting "this artist falls." Payout scales inversely with price change; loss is capped at the stake (no margin, no liquidation). Gain should also be capped at some multiple (e.g. 3x stake) to keep the play-money economy bounded and avoid one runaway short draining the system.
- No margin, no leverage, no order book in v1 — the AMM handles pricing so there's always a counterparty.

### Play-money economy

- Starting balance for every new user (e.g. $10,000 play dollars).
- Daily login bonus / streak mechanic — classic stickiness lever, gives users a reason to open the app even when not actively trading.
- A balance safety net (small weekly top-up if a user's balance falls near zero) so a bad run doesn't just end the relationship — churn risk if going broke means the app is over for them.

### Discovery

- Feed views that double as marketing hooks: "Fastest growing, under $10," "Biggest movers today," "Most shorted" (contrarian signal), "New listings."
- Per-artist price chart, showing Market Price vs. the Index-derived fair value line — this chart _is_ the product's unique visual, worth investing in early.

### Leaderboards

- **Portfolio leaderboard** (all-time / weekly / monthly % return) — straightforward, but naturally favors early/whale users.
- **Talent Scout leaderboard**: ranks users by realized gains on positions opened _while the artist was still small_ (e.g. bought under a price/index threshold, or before a defined breakout crossing). This is the leaderboard that actually matters for the product's identity — it rewards discovery skill, not just capital or luck.

### Tournaments (lightweight, included in v1)

- Time-boxed contests (e.g. monthly) where entrants get a **fresh, equal play-money balance** for the contest window and are ranked by % return over that period.
- Reuses all existing trading infrastructure — it's a filtered leaderboard with a fair starting condition, not a new system. Low build cost, strong reason to come back on a recurring cadence, and it's the fairness mechanism the open-ended portfolio leaderboard lacks (new users can never catch up to portfolio value built up over months, but they can win a tournament).

## Explicitly out of scope for v1

- Mobile app (start web — faster to ship and iterate; revisit once the core loop is validated).
- Real-money trading.
- Deep social features (following traders, comments) — a simple shareable "portfolio/leaderboard card" (screenshot-friendly) is worth considering as a cheap virality lever, but full social graph can wait.
- Paid multi-provider data aggregation (Chartmetric/Soundcharts) — start with Last.fm's free API only.

## Why this should be sticky (the actual bet of this product)

1. **Skill signal, not just vibes** — the index-anchoring means being early is provably rewarded, which is a stronger hook than a pure prediction market or pure meme-stock app.
2. **Cheap lottery-ticket discovery** — "under $10, fastest growing" framing turns music discovery into a game with stakes, which is inherently shareable ("I called it").
3. **Recurring reasons to return** — daily login streaks, nightly index-reversion (did my pick move?), and monthly tournaments layer short, medium, and long re-engagement loops.
4. **Fair on-ramp for new users** — tournaments prevent the "leaderboard is permanently dominated by day-one users" problem that kills a lot of portfolio-style competitive apps.

## Open questions / risks to watch

- **Economy balancing**: with no real money, inflation of play-money balances over time can make leaderboards meaningless — daily bonuses, safety nets, and short payout caps all need tuning against each other.
- **Right of publicity**: using real artists' names/likenesses in a trading product, even with play money, warrants a clear "not affiliated with or endorsed by" disclaimer per artist.
- **Artist curation quality**: the product lives or dies on whether the emerging-artist list actually contains plausible breakouts — this is closer to an editorial/curation problem than an engineering one early on.

## Path to real money (future, not v1)

Worth naming now since it shaped the "play money first" decision: a literal "shares of a person" model is a securities/right-of-publicity problem, since artists aren't consenting, reporting entities the way companies are. The realistic real-money path looks more like Kalshi's — CFTC-regulated **event contracts** on public data thresholds ("will Artist X's index score exceed Y by date Z") rather than open-ended equity-style shares. That's a legal/licensing undertaking on its own, separate from the engineering work, and is the reason play-money v1 is the right sequencing: prove the engagement loop first, then scope the compliance path deliberately.

## Future development (beyond v1)

- Mobile app once web usage validates the loop.
- Richer data sources (Chartmetric/Soundcharts subscription) for a more resistant-to-gaming, cross-platform index.
- Full margin shorting for power users.
- Social layer: follow traders, comment threads on artists, shareable portfolio cards.
- Real-money event contracts, pursued as a distinct regulatory track.
