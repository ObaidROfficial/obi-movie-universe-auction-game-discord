"""
Turns a pool_item row into a single comparable "success score", and rolls
per-player rosters up into a leaderboard.

Movies: US box office gross from OMDb, when available.
TV shows (and movies OMDb has no box-office figure for): a proxy score of
imdb_rating * imdb_votes * TV_PROXY_SCALE, so a widely-watched, well-rated
show still contributes something comparable to a mid-size box-office movie.
Tune TV_PROXY_SCALE in config.py once you've run a few games and seen how
the numbers feel.
"""
from config import TV_PROXY_SCALE


def item_success_score(item_row) -> float:
    if item_row["box_office"]:
        return float(item_row["box_office"])
    rating = item_row["imdb_rating"] or 0.0
    votes = item_row["imdb_votes"] or 0
    return rating * votes * TV_PROXY_SCALE


def compute_leaderboard(rosters: dict) -> list[tuple]:
    """
    rosters: {user_id: [pool_item rows]}
    Returns a list of (user_id, total_score, items) sorted highest score first.
    """
    board = []
    for user_id, items in rosters.items():
        total = sum(item_success_score(item) for item in items)
        board.append((user_id, total, items))
    board.sort(key=lambda entry: entry[1], reverse=True)
    return board


def format_score(score: float) -> str:
    if score >= 1_000_000:
        return f"${score / 1_000_000:,.1f}M-equiv"
    return f"{score:,.0f}"
