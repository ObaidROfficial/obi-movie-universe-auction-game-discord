"""
Async SQLite persistence layer. One file (movie_auction.db) holds everything,
so stopping/restarting the bot never loses an in-progress game.
"""
from pathlib import Path
from typing import Optional

import aiosqlite

DB_PATH = Path(__file__).parent / "data" / "movie_auction.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    universe TEXT NOT NULL,
    budget INTEGER NOT NULL,
    max_titles INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'joining',  -- joining | active | finished
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS players (
    game_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    budget_remaining INTEGER NOT NULL,
    titles_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, user_id),
    FOREIGN KEY (game_id) REFERENCES games(id)
);

CREATE TABLE IF NOT EXISTS pool_items (
    game_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    media_type TEXT NOT NULL,           -- movie | series
    imdb_id TEXT,
    imdb_rating REAL,
    rotten_tomatoes REAL,
    box_office INTEGER,
    imdb_votes INTEGER,
    status TEXT NOT NULL DEFAULT 'available',  -- available | in_auction | sold | unsold
    winner_user_id INTEGER,
    sold_price INTEGER,
    PRIMARY KEY (game_id, title)
);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


# --- Games -------------------------------------------------------------

async def create_game(guild_id: int, channel_id: int, universe: str, budget: int, max_titles: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO games (guild_id, channel_id, universe, budget, max_titles) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, universe, budget, max_titles),
        )
        await db.commit()
        return cursor.lastrowid


async def get_open_game(channel_id: int) -> Optional[aiosqlite.Row]:
    """Returns the most recent non-finished game in this channel, if any."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM games WHERE channel_id = ? AND status != 'finished' ORDER BY id DESC LIMIT 1",
            (channel_id,),
        )
        return await cursor.fetchone()


async def get_game(game_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        return await cursor.fetchone()


async def set_game_status(game_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE games SET status = ? WHERE id = ?", (status, game_id))
        await db.commit()


# --- Players -------------------------------------------------------------

async def add_player(game_id: int, user_id: int, display_name: str, budget: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO players (game_id, user_id, display_name, budget_remaining) VALUES (?, ?, ?, ?)",
            (game_id, user_id, display_name, budget),
        )
        await db.commit()


async def get_players(game_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM players WHERE game_id = ?", (game_id,))
        return await cursor.fetchall()


async def get_player(game_id: int, user_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM players WHERE game_id = ? AND user_id = ?", (game_id, user_id)
        )
        return await cursor.fetchone()


async def apply_win(game_id: int, user_id: int, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE players SET budget_remaining = budget_remaining - ?, titles_count = titles_count + 1 "
            "WHERE game_id = ? AND user_id = ?",
            (price, game_id, user_id),
        )
        await db.commit()


# --- Pool items ------------------------------------------------------------

async def add_pool_item(game_id: int, title_data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO pool_items
               (game_id, title, media_type, imdb_id, imdb_rating, rotten_tomatoes, box_office, imdb_votes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                game_id,
                title_data["title"],
                title_data["type"],
                title_data.get("imdb_id"),
                title_data.get("imdb_rating"),
                title_data.get("rotten_tomatoes"),
                title_data.get("box_office"),
                title_data.get("imdb_votes"),
            ),
        )
        await db.commit()


async def get_available_items(game_id: int) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM pool_items WHERE game_id = ? AND status = 'available'", (game_id,)
        )
        return await cursor.fetchall()


async def mark_item_status(game_id: int, title: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pool_items SET status = ? WHERE game_id = ? AND title = ?",
            (status, game_id, title),
        )
        await db.commit()


async def record_sale(game_id: int, title: str, winner_user_id: int, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pool_items SET status = 'sold', winner_user_id = ?, sold_price = ? "
            "WHERE game_id = ? AND title = ?",
            (winner_user_id, price, game_id, title),
        )
        await db.commit()


async def get_rosters(game_id: int) -> dict[int, list[aiosqlite.Row]]:
    """Returns {user_id: [pool_item rows they won]}."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM pool_items WHERE game_id = ? AND status = 'sold'", (game_id,)
        )
        rows = await cursor.fetchall()
    rosters: dict[int, list[aiosqlite.Row]] = {}
    for row in rows:
        rosters.setdefault(row["winner_user_id"], []).append(row)
    return rosters
