import discord
from discord import app_commands
from discord.ext import commands

import universes


class UniverseCog(commands.GroupCog, name="universe"):
    """Manage the curated title pools (e.g. marvel, star_wars) used to start games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="list", description="List all universes that have been set up")
    async def list_universes(self, interaction: discord.Interaction):
        names = universes.list_universes()
        if not names:
            await interaction.response.send_message(
                "No universes yet. Add one with `/universe addtitle`.", ephemeral=True
            )
            return
        lines = []
        for name in names:
            count = len(universes.load_universe(name))
            lines.append(f"- **{name}** ({count} title{'s' if count != 1 else ''})")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="show", description="Show every title currently in a universe")
    @app_commands.describe(universe="Universe name, e.g. marvel")
    async def show_universe(self, interaction: discord.Interaction, universe: str):
        entries = universes.load_universe(universe)
        if not entries:
            await interaction.response.send_message(
                f"No titles found for `{universe}` (or it doesn't exist yet).", ephemeral=True
            )
            return
        movies = [e["title"] for e in entries if e["type"] == "movie"]
        series = [e["title"] for e in entries if e["type"] == "series"]
        embed = discord.Embed(title=f"Universe: {universe}")
        if movies:
            embed.add_field(name=f"Movies ({len(movies)})", value="\n".join(movies), inline=False)
        if series:
            embed.add_field(name=f"TV Shows ({len(series)})", value="\n".join(series), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="addtitle", description="Add a movie or show to a universe pool")
    @app_commands.describe(
        universe="Universe name, e.g. marvel (created automatically if new)",
        title="Exact-ish title, e.g. 'Avengers: Endgame'",
        media_type="Is this a movie or a TV series?",
    )
    @app_commands.choices(
        media_type=[
            app_commands.Choice(name="Movie", value="movie"),
            app_commands.Choice(name="TV Series", value="series"),
        ]
    )
    async def add_title(
        self,
        interaction: discord.Interaction,
        universe: str,
        title: str,
        media_type: app_commands.Choice[str],
    ):
        added = universes.add_title(universe, title, media_type.value)
        if added:
            await interaction.response.send_message(
                f"Added **{title}** ({media_type.name}) to `{universe}`."
            )
        else:
            await interaction.response.send_message(
                f"**{title}** is already in `{universe}`.", ephemeral=True
            )

    @app_commands.command(name="removetitle", description="Remove a title from a universe pool")
    @app_commands.describe(universe="Universe name", title="Title to remove")
    async def remove_title(self, interaction: discord.Interaction, universe: str, title: str):
        removed = universes.remove_title(universe, title)
        if removed:
            await interaction.response.send_message(f"Removed **{title}** from `{universe}`.")
        else:
            await interaction.response.send_message(
                f"Couldn't find **{title}** in `{universe}`.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(UniverseCog(bot))
