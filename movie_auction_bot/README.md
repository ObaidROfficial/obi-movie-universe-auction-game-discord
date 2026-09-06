# Movie/TV Universe Draft Auction — Discord Bot

A Discord bot for a group game: pick a "universe" (Marvel, Star Wars, Harry
Potter, etc.), everyone gets a budget, and you take turns bidding on random
titles from that universe until every player has a full roster. The winner
is whoever's roster has the highest combined "success" — box office gross
for movies, and an IMDb rating/vote-based score for TV shows (which don't
have box office numbers).

Runs entirely on your own machine — start it before game night, stop it
with Ctrl+C when you're done. No hosting required.

## 1. One-time setup

### Get a Discord bot token
1. Go to https://discord.com/developers/applications and click **New Application**.
2. Go to the **Bot** tab, click **Reset Token**, and copy it somewhere safe.
3. Under **Privileged Gateway Intents**, you don't need to enable anything extra —
   this bot only uses slash commands and buttons.
4. Go to **OAuth2 → URL Generator**. Under **Scopes**, check `bot` and
   `applications.commands`. Under **Bot Permissions**, check `Send Messages`,
   `Embed Links`, and `Use Slash Commands`.
5. Copy the generated URL, open it in a browser, and invite the bot to your server.

### Get a free OMDb API key
1. Go to https://www.omdbapi.com/apikey.aspx, select the **FREE** tier, and
   submit your email.
2. Check your email for the key (it's usually instant). Free tier = 1,000
   requests/day, which the bot's caching keeps you well under.

### Install and configure
```bash
cd movie_auction_bot
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
Open `.env` and fill in:
```
DISCORD_TOKEN=your_bot_token_here
OMDB_API_KEY=your_omdb_key_here
```

## 2. Running it
```bash
python bot.py
```
Leave it running while you play; `Ctrl+C` to stop. All game state lives in
`data/movie_auction.db` (SQLite) and survives restarts — if you stop the bot
mid-auction, restarting it won't lose scores, but you will need to re-run
`/game start` for a fresh auction round since the live bidding session itself
is in-memory.

> Note: the very first time you run the bot, Discord can take up to ~1 hour
> to show newly-added slash commands everywhere. If you want them to show up
> instantly while you're testing, see "Faster command syncing" below.

## 3. Setting up a universe (one-time per universe)

Two starter universes are already included as examples: `marvel` and
`star_wars` (small seed lists — add more titles as you like). To build your
own or expand these:

```
/universe addtitle universe:harry_potter title:"Harry Potter and the Sorcerer's Stone" media_type:Movie
/universe addtitle universe:harry_potter title:"Harry Potter and the Chamber of Secrets" media_type:Movie
/universe show universe:harry_potter
```
`/universe list` shows every universe you've built and how many titles are in each.

Titles just need to be close enough to their real name for OMDb to match them —
the bot resolves and caches the real data (ratings, box office, etc.) the
first time a game uses that universe.

## 4. Playing a game

1. `/game start universe:marvel budget:30 max_titles:5` — budget and
   max_titles are set fresh every time, so tune them to the group and universe size.
2. Everyone clicks **Join** on the bot's message.
3. Whoever's hosting clicks **Begin Auction**. The bot resolves all the
   universe's titles against OMDb (a few seconds), then starts auctioning
   one at a time in random order.
4. For each title: bid with the quick **Bid $X** buttons or **Custom Bid**
   for a specific number. Bidding stays open ~30s, extending by ~10s if
   someone bids in the closing seconds (soft-close, so it doesn't come down
   to keyboard speed).
5. The bot won't let you bid more than you can afford while still leaving
   at least $1 for each remaining slot you still need to fill.
6. Once everyone has their `max_titles` titles (or the pool runs out), the
   bot posts final results and declares a winner.
7. `/game results` any time to check current standings; `/game cancel` to scrap a game.

## How scoring works

- **Movies:** US box office gross, from OMDb.
- **TV shows** (and any movie OMDb has no box-office figure for): a proxy
  score of `imdb_rating × imdb_votes × TV_PROXY_SCALE`, so a widely-watched
  well-rated show still contributes a comparable amount to a mid-size
  box-office movie. `TV_PROXY_SCALE` lives in `config.py` — tune it after a
  game or two if TV titles feel over/under-valued relative to movies.
- A player's total is just the sum across their 5 (or however many) titles.

## Faster command syncing while developing (optional)

Global slash command sync can take up to an hour to propagate. For instant
updates to a single test server while you're tweaking commands, add your
server's ID and sync to it directly — ask me and I can wire this in if you
want it (it's a small change to `bot.py`).

## Known limitations worth knowing about

- OMDb's box office figure is **US theatrical only** — older, foreign, or
  streaming-first titles often won't have one, which is why the TV-style
  proxy score also silently covers those movies.
- Title matching is by name — if OMDb matches the wrong movie/show (rare,
  but happens with very generic titles or remakes), delete the bad entry
  from `data/omdb_cache.json` and re-add the title with a more specific name
  (e.g. include the year: "Dune (2021)").
- Only one game can be active per channel at a time — start games in
  different channels if you want to run two at once.
