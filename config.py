"""
Loads configuration from environment variables (.env file).
"""
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

# Auction tuning knobs (safe to tweak) --------------------------------------
BID_WINDOW_SECONDS = 30          # base time an item stays open for bidding
BID_EXTENSION_SECONDS = 10       # time added when a new bid lands near the end
BID_EXTENSION_TRIGGER_SECONDS = 8  # if a bid comes in with less than this left, extend
MIN_BID_INCREMENT = 1            # smallest amount a new bid must beat the current one by

# Success-score weighting for titles with no box office data (mainly TV).
# proxy_score = imdb_rating * imdb_votes * TV_PROXY_SCALE
# Tuned so a well-voted, well-rated show lands in a comparable range to a
# mid-size box office movie. Adjust freely once you see real results.
TV_PROXY_SCALE = 50

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
if not OMDB_API_KEY:
    raise RuntimeError("OMDB_API_KEY is not set. Copy .env.example to .env and fill it in.")
