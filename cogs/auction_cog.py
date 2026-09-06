import asyncio
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import db
import universes
import scoring
from config import (
    BID_WINDOW_SECONDS,
    BID_EXTENSION_SECONDS,
    BID_EXTENSION_TRIGGER_SECONDS,
    MIN_BID_INCREMENT,
)
from omdb_client import OMDbClient, TitleNotFound


class AuctionSession:
    """In-memory state for the item currently up for bidding in one channel."""

    def __init__(self, game_id: int, max_titles: int):
        self.game_id = game_id
        self.max_titles = max_titles
        self.lock = asyncio.Lock()
        self.reset_item()

    def reset_item(self):
        self.item_row = None
        self.current_bid = 0
        self.current_bidder_id = None
        self.deadline = None
        self.message: discord.Message | None = None


def max_affordable_bid(budget_remaining: int, titles_count: int, max_titles: int) -> int:
    """A player must always leave at least $1 per remaining slot after this win."""
    slots_remaining_after_this = max_titles - titles_count - 1
    if slots_remaining_after_this < 0:
        return 0  # already full
    return budget_remaining - slots_remaining_after_this


class AuctionCog(commands.GroupCog, name="game"):
    """The movie/TV universe draft-auction game."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.omdb = OMDbClient()
        self.sessions: dict[int, AuctionSession] = {}  # channel_id -> session

    # ---------------------------------------------------------------- start

    @app_commands.command(name="start", description="Set up a new draft-auction game in this channel")
    @app_commands.describe(
        universe="Which title pool to draft from, e.g. marvel",
        budget="How much play-money each player starts with (set fresh each game)",
        max_titles="How many titles each player must end up with",
    )
    async def start(
        self, interaction: discord.Interaction, universe: str, budget: app_commands.Range[int, 1, 100000],
        max_titles: app_commands.Range[int, 1, 20],
    ):
        existing = await db.get_open_game(interaction.channel_id)
        if existing:
            await interaction.response.send_message(
                "There's already a game running or waiting to start in this channel. "
                "Use `/game cancel` first if you want to scrap it.",
                ephemeral=True,
            )
            return

        pool = universes.load_universe(universe)
        if not pool:
            available = ", ".join(universes.list_universes()) or "(none yet)"
            await interaction.response.send_message(
                f"Universe `{universe}` has no titles yet. Available universes: {available}\n"
                f"Add titles with `/universe addtitle`.",
                ephemeral=True,
            )
            return

        if max_titles * 1 > budget:
            await interaction.response.send_message(
                f"With a ${budget} budget you can't realistically fill {max_titles} slots "
                f"(each slot needs at least $1). Raise the budget or lower max_titles.",
                ephemeral=True,
            )
            return

        game_id = await db.create_game(interaction.guild_id, interaction.channel_id, universe, budget, max_titles)
        self.sessions[interaction.channel_id] = AuctionSession(game_id, max_titles)

        view = JoinView(self, game_id, budget, max_titles)
        embed = discord.Embed(
            title="🎬 Draft Auction: forming a game",
            description=(
                f"**Universe:** {universe} ({len(pool)} titles)\n"
                f"**Budget per player:** ${budget}\n"
                f"**Titles per player:** {max_titles}\n\n"
                f"Click **Join** below. Once everyone's in, whoever's hosting clicks **Begin Auction**."
            ),
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    # --------------------------------------------------------------- cancel

    @app_commands.command(name="cancel", description="Cancel the current game in this channel")
    async def cancel(self, interaction: discord.Interaction):
        game = await db.get_open_game(interaction.channel_id)
        if not game:
            await interaction.response.send_message("No active game here.", ephemeral=True)
            return
        await db.set_game_status(game["id"], "finished")
        self.sessions.pop(interaction.channel_id, None)
        await interaction.response.send_message("Game cancelled.")

    # -------------------------------------------------------------- results

    @app_commands.command(name="results", description="Show the current standings/leaderboard")
    async def results(self, interaction: discord.Interaction):
        game = await db.get_open_game(interaction.channel_id)
        if not game:
            await interaction.response.send_message("No game found in this channel.", ephemeral=True)
            return
        await interaction.response.defer()
        await self._post_leaderboard(interaction.channel, game["id"], final=(game["status"] == "finished"))

    # ---------------------------------------------------------- begin logic

    async def begin_auction(self, channel: discord.abc.Messageable, game_id: int, universe: str, max_titles: int):
        await channel.send(f"📚 Resolving `{universe}` titles against OMDb (ratings, RT scores, box office)...")
        pool = universes.load_universe(universe)
        skipped = []
        for entry in pool:
            try:
                data = await self.omdb.fetch_title(entry["title"], entry["type"])
                await db.add_pool_item(game_id, {**data, "title": entry["title"], "type": entry["type"]})
            except TitleNotFound:
                skipped.append(entry["title"])
        if skipped:
            await channel.send(f"⚠️ Couldn't find on OMDb, skipped: {', '.join(skipped)}")

        await db.set_game_status(game_id, "active")
        await channel.send("🔨 Auction starting!")
        self.bot.loop.create_task(self._run_auction_loop(channel, game_id, max_titles))

    async def _run_auction_loop(self, channel, game_id: int, max_titles: int):
        session = self.sessions.get(channel.id)
        if session is None:
            session = AuctionSession(game_id, max_titles)
            self.sessions[channel.id] = session

        while True:
            available = await db.get_available_items(game_id)
            players = await db.get_players(game_id)
            active_players = [p for p in players if p["titles_count"] < max_titles]

            if not available or not active_players:
                break

            item = random.choice(available)
            await db.mark_item_status(game_id, item["title"], "in_auction")

            session.reset_item()
            session.item_row = item
            session.deadline = time.time() + BID_WINDOW_SECONDS

            embed = build_item_embed(item, session, players_by_id(players))
            view = BidView(self, session, game_id, max_titles)
            session.message = await channel.send(embed=embed, view=view)

            # Wait out the (extendable) bidding window.
            while time.time() < session.deadline:
                await asyncio.sleep(min(1.0, session.deadline - time.time()))

            await self._finalize_item(channel, game_id, session)

        await db.set_game_status(game_id, "finished")
        self.sessions.pop(channel.id, None)
        await channel.send("🏁 All done! Final results:")
        await self._post_leaderboard(channel, game_id, final=True)

    async def _finalize_item(self, channel, game_id: int, session: AuctionSession):
        item = session.item_row
        # Disable the view on the old message.
        if session.message:
            try:
                await session.message.edit(view=None)
            except discord.HTTPException:
                pass

        if session.current_bidder_id is not None:
            await db.apply_win(game_id, session.current_bidder_id, session.current_bid)
            await db.record_sale(game_id, item["title"], session.current_bidder_id, session.current_bid)
            await channel.send(
                f"✅ **{item['title']}** sold to <@{session.current_bidder_id}> for **${session.current_bid}**."
            )
        else:
            await db.mark_item_status(game_id, item["title"], "unsold")
            await channel.send(f"➖ **{item['title']}** got no bids and stays out of the game.")

    async def _post_leaderboard(self, channel, game_id: int, final: bool):
        rosters = await db.get_rosters(game_id)
        if not rosters:
            await channel.send("No titles have been won yet.")
            return
        board = scoring.compute_leaderboard(rosters)

        embed = discord.Embed(title="🏆 Final Results" if final else "📊 Current Standings")
        for rank, (user_id, total, items) in enumerate(board, start=1):
            titles_list = "\n".join(f"• {i['title']} (${i['sold_price']})" for i in items)
            medal = ["🥇", "🥈", "🥉"][rank - 1] if rank <= 3 else f"#{rank}"
            embed.add_field(
                name=f"{medal} <@{user_id}> — {scoring.format_score(total)}",
                value=titles_list or "(no titles)",
                inline=False,
            )
        await channel.send(embed=embed)

    # ------------------------------------------------------------ bidding

    async def process_bid(self, interaction: discord.Interaction, session: AuctionSession, game_id: int,
                           max_titles: int, amount: int):
        async with session.lock:
            player = await db.get_player(game_id, interaction.user.id)
            if player is None:
                await interaction.response.send_message("You're not in this game.", ephemeral=True)
                return

            if player["titles_count"] >= max_titles:
                await interaction.response.send_message("You already have your full roster.", ephemeral=True)
                return

            if amount <= session.current_bid:
                await interaction.response.send_message(
                    f"Bid must be higher than the current top bid (${session.current_bid}).", ephemeral=True
                )
                return

            if amount < session.current_bid + MIN_BID_INCREMENT:
                await interaction.response.send_message(
                    f"Minimum increment is ${MIN_BID_INCREMENT}.", ephemeral=True
                )
                return

            cap = max_affordable_bid(player["budget_remaining"], player["titles_count"], max_titles)
            if amount > cap:
                await interaction.response.send_message(
                    f"You can bid at most ${cap} right now — you need to keep at least $1 per "
                    f"remaining title slot.",
                    ephemeral=True,
                )
                return

            session.current_bid = amount
            session.current_bidder_id = interaction.user.id
            if session.deadline - time.time() < BID_EXTENSION_TRIGGER_SECONDS:
                session.deadline = time.time() + BID_EXTENSION_SECONDS

            players = await db.get_players(game_id)
            embed = build_item_embed(session.item_row, session, players_by_id(players))
            new_view = BidView(self, session, game_id, max_titles)
            await interaction.response.edit_message(embed=embed, view=new_view)


# ------------------------------------------------------------------ helpers

def players_by_id(players) -> dict:
    return {p["user_id"]: p for p in players}


def build_item_embed(item, session: AuctionSession, players_map: dict) -> discord.Embed:
    embed = discord.Embed(title=f"🎟️ Now auctioning: {item['title']}")
    embed.add_field(name="Type", value="Movie" if item["media_type"] == "movie" else "TV Series")
    if item["imdb_rating"] is not None:
        embed.add_field(name="IMDb", value=f"{item['imdb_rating']} / 10")
    if item["rotten_tomatoes"] is not None:
        embed.add_field(name="Rotten Tomatoes", value=f"{item['rotten_tomatoes']:.0f}%")
    if item["box_office"]:
        embed.add_field(name="Box Office", value=f"${item['box_office']:,}")

    if session.current_bidder_id:
        embed.add_field(
            name="Current bid",
            value=f"${session.current_bid} by <@{session.current_bidder_id}>",
            inline=False,
        )
    else:
        embed.add_field(name="Current bid", value="No bids yet", inline=False)

    embed.add_field(name="Closes", value=f"<t:{int(session.deadline)}:R>", inline=False)
    return embed


class JoinView(discord.ui.View):
    def __init__(self, cog: AuctionCog, game_id: int, budget: int, max_titles: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.budget = budget
        self.max_titles = max_titles
        self.message: discord.Message | None = None

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.add_player(self.game_id, interaction.user.id, str(interaction.user.display_name), self.budget)
        await interaction.response.send_message(f"You're in with ${self.budget}.", ephemeral=True)

    @discord.ui.button(label="Begin Auction", style=discord.ButtonStyle.primary)
    async def begin(self, interaction: discord.Interaction, button: discord.ui.Button):
        players = await db.get_players(self.game_id)
        if len(players) < 2:
            await interaction.response.send_message(
                "Need at least 2 players joined before starting.", ephemeral=True
            )
            return
        game = await db.get_game(self.game_id)
        if game["status"] != "joining":
            await interaction.response.send_message("This game has already started.", ephemeral=True)
            return
        await interaction.response.send_message("Starting the auction...")
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass
        await self.cog.begin_auction(interaction.channel, self.game_id, game["universe"], self.max_titles)


class BidModal(discord.ui.Modal, title="Place a custom bid"):
    amount = discord.ui.TextInput(label="Bid amount ($)", placeholder="e.g. 12")

    def __init__(self, cog: AuctionCog, session: AuctionSession, game_id: int, max_titles: int):
        super().__init__()
        self.cog = cog
        self.session = session
        self.game_id = game_id
        self.max_titles = max_titles

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(str(self.amount.value).strip())
        except ValueError:
            await interaction.response.send_message("Enter a whole number.", ephemeral=True)
            return
        await self.cog.process_bid(interaction, self.session, self.game_id, self.max_titles, amount)


class BidView(discord.ui.View):
    def __init__(self, cog: AuctionCog, session: AuctionSession, game_id: int, max_titles: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.session = session
        self.game_id = game_id
        self.max_titles = max_titles

        next_min = session.current_bid + MIN_BID_INCREMENT
        next_five = session.current_bid + 5

        self.add_item(self._make_bid_button(f"Bid ${next_min}", next_min, discord.ButtonStyle.success))
        self.add_item(self._make_bid_button(f"Bid ${next_five}", next_five, discord.ButtonStyle.primary))
        self.add_item(self._make_custom_button())

    def _make_bid_button(self, label: str, amount: int, style: discord.ButtonStyle):
        button = discord.ui.Button(label=label, style=style)

        async def callback(interaction: discord.Interaction):
            await self.cog.process_bid(interaction, self.session, self.game_id, self.max_titles, amount)

        button.callback = callback
        return button

    def _make_custom_button(self):
        button = discord.ui.Button(label="Custom Bid", style=discord.ButtonStyle.secondary)

        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(
                BidModal(self.cog, self.session, self.game_id, self.max_titles)
            )

        button.callback = callback
        return button


async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionCog(bot))
