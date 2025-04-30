import discord
from discord.ext import commands, tasks
import os
import random
from datetime import datetime, timedelta, time as dtime
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

teams = {}
teams_backup = {}
team_rosters = {}
match_reports = []
tournament_matches = []
tournament_started = False
players_per_team = 0
current_round = 1
winners_by_round = {}
champion = None
match_schedule = {}
tournament_date = None
scheduled = False
last_report_times = {}
is_test_mode = False
TOURNAMENT_CHANNEL_NAME = "tournament"
BOT_COMMANDS_CHANNEL_NAME = "bot-commands"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_tournament_start.start()
    auto_dq_check.start()

@tasks.loop(minutes=1)
async def check_tournament_start():
    global tournament_started, scheduled
    now = datetime.now()
    if tournament_date and now.date() >= tournament_date and now.time().hour >= 20 and not tournament_started and not scheduled:
        channel = discord.utils.get(bot.get_all_channels(), name=TOURNAMENT_CHANNEL_NAME)
        if channel:
            await auto_start_tournament(channel)
        scheduled = True

@tasks.loop(minutes=5)
async def auto_dq_check():
    to_remove = []
    for match in tournament_matches:
        if match[1] != "BYE" and datetime.now() - last_report_times.get(match, datetime.now()) > timedelta(minutes=30):
            winner = random.choice(match)
            loser = match[0] if winner == match[1] else match[1]
            to_remove.append((winner, loser))
    for winner, loser in to_remove:
        channel = discord.utils.get(bot.get_all_channels(), name=TOURNAMENT_CHANNEL_NAME)
        if channel:
            await handle_report(await bot.get_context(await channel.send("Auto-DQ executing...")), winner, loser, override=True)

async def ensure_command_channel(ctx):
    if ctx.channel.name != BOT_COMMANDS_CHANNEL_NAME:
        await ctx.send(f"Please use #{BOT_COMMANDS_CHANNEL_NAME} for bot commands.")
        return False
    return True

@bot.command()
async def register(ctx, *, gamertag):
    if not await ensure_command_channel(ctx): return
    teams[ctx.author.id] = {'gamertag': gamertag, 'team': None, 'captain': False}
    await ctx.send(f"{ctx.author.mention} registered with gamertag: {gamertag}")

@bot.command()
async def create_team(ctx, *, team_name):
    if not await ensure_command_channel(ctx): return
    if tournament_started:
        await ctx.send("Tournament already started. Can't create teams now.")
        return
    if any(t.get('team') == team_name for t in teams.values()):
        await ctx.send("That team name is already taken.")
        return
    teams[ctx.author.id] = teams.get(ctx.author.id, {})
    teams[ctx.author.id]['team'] = team_name
    teams[ctx.author.id]['captain'] = True
    team_rosters[team_name] = [ctx.author.id]
    await ctx.send(f'Team "{team_name}" created by {ctx.author.mention}')

@bot.command()
async def join_team(ctx, *, team_name):
    if not await ensure_command_channel(ctx): return
    if tournament_started:
        await ctx.send("Tournament already started. Can't join teams now.")
        return
    if team_name not in team_rosters:
        await ctx.send("That team doesn't exist.")
        return
    if players_per_team and len(team_rosters[team_name]) >= players_per_team:
        await ctx.send("This team is already full.")
        return
    teams[ctx.author.id] = teams.get(ctx.author.id, {})
    teams[ctx.author.id]['team'] = team_name
    teams[ctx.author.id]['captain'] = False
    team_rosters[team_name].append(ctx.author.id)
    await ctx.send(f"{ctx.author.mention} joined team {team_name}")

@bot.command()
async def change_player(ctx, old_member: discord.Member, new_member: discord.Member):
    if not await ensure_command_channel(ctx): return
    if tournament_started:
        await ctx.send("Tournament already started. Can't change players now.")
        return
    captain_data = teams.get(ctx.author.id, {})
    if not captain_data.get('captain'):
        await ctx.send("Only team captains can change players.")
        return
    team_name = captain_data.get('team')
    if not team_name:
        await ctx.send("You don't have a team.")
        return
    if old_member.id not in team_rosters[team_name]:
        await ctx.send("That player is not on your team.")
        return
    team_rosters[team_name].remove(old_member.id)
    team_rosters[team_name].append(new_member.id)
    teams[new_member.id] = {'gamertag': "Unknown", 'team': team_name, 'captain': False}
    if old_member.id in teams:
        del teams[old_member.id]
    await ctx.send(f"{old_member.mention} has been replaced by {new_member.mention} on team {team_name}")

@bot.command()
async def team_info(ctx, *, team_name):
    if not await ensure_command_channel(ctx): return
    if teams.get(ctx.author.id, {}).get('captain') is not True:
        await ctx.send("Only team captains can use this command.")
        return
    if team_name not in team_rosters:
        await ctx.send("That team does not exist.")
        return
    member_lines = []
    for uid in team_rosters[team_name]:
        user = await bot.fetch_user(uid)
        info = teams.get(uid, {})
        name = info.get('gamertag', 'Unknown')
        role = " (Captain)" if info.get('captain') else ""
        member_lines.append(f"- {name}{role} ({user.name})")
    await ctx.send(f"**Team {team_name}:**\n" + "\n".join(member_lines))

@bot.command()
async def set_team_size(ctx, size: int):
    if not await ensure_command_channel(ctx): return
    global players_per_team
    if tournament_started:
        await ctx.send("Tournament already started. Can't change team size now.")
        return
    if size < 1:
        await ctx.send("Team size must be at least 1.")
        return
    players_per_team = size
    await ctx.send(f"Team size set to {size} players per team.")

@bot.command()
async def test_mode(ctx):
    if not await ensure_command_channel(ctx): return
    global teams, team_rosters, players_per_team, is_test_mode
    teams_backup.update(teams)
    base_id = 1000000
    for i in range(1, 9):
        uid = base_id + i
        team_name = f"TestTeam{i}"
        teams[uid] = {'gamertag': f"TestPlayer{i}", 'team': team_name, 'captain': True}
        team_rosters[team_name] = [uid]
    players_per_team = 1
    is_test_mode = True
    await ctx.send("**Test mode loaded with 8 fake teams. Use !start_tournament to run the bracket.**")

@bot.command()
async def set_tournament_date(ctx, *, date_str):
    if not await ensure_command_channel(ctx): return
    global tournament_date
    try:
        tournament_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        await ctx.send(f"Tournament start date set to: {tournament_date}")
    except ValueError:
        await ctx.send("Invalid format. Use YYYY-MM-DD (e.g. 2025-05-01)")

@bot.command()
async def start_tournament(ctx):
    if not await ensure_command_channel(ctx): return
    if tournament_started:
        await ctx.send("Tournament already started!")
        return
    await auto_start_tournament(ctx.channel)

async def auto_start_tournament(channel):
    global tournament_started, current_round, tournament_matches, winners_by_round
    full_teams = [team for team, members in team_rosters.items() if len(members) == players_per_team]
    if len(full_teams) < 2:
        await channel.send("Not enough full teams to start the tournament.")
        return
    random.shuffle(full_teams)
    current_round = 1
    tournament_matches.clear()
    winners_by_round.clear()
    match_schedule.clear()
    noon_time = datetime.combine(datetime.now().date(), dtime(hour=20))
    for i in range(0, len(full_teams), 2):
        if i + 1 < len(full_teams):
            match = (full_teams[i], full_teams[i + 1])
            tournament_matches.append(match)
            match_schedule[match] = noon_time.strftime("%I:%M %p EST")
            last_report_times[match] = datetime.now()
        else:
            tournament_matches.append((full_teams[i], "BYE"))
            winners_by_round.setdefault(current_round, []).append(full_teams[i])
    tournament_started = True
    tournament_channel = discord.utils.get(channel.guild.text_channels, name=TOURNAMENT_CHANNEL_NAME)
    if tournament_channel:
        await tournament_channel.send("**Tournament Started! Round 1 Matches:**")
        for match in tournament_matches:
            if match[1] == "BYE":
                await tournament_channel.send(f"**{match[0]}** gets a BYE")
            else:
                await tournament_channel.send(f"**{match[0]}** vs **{match[1]}** — Starts at 08:00 PM EST")

@bot.command()
async def report(ctx, winner: str, loser: str):
    if not await ensure_command_channel(ctx): return
    if not is_test_mode:
        reporter = teams.get(ctx.author.id, {})
        if reporter.get('team') not in [winner, loser]:
            await ctx.send("You can only report results for your own team.")
            return
    await handle_report(ctx, winner, loser)

@bot.command()
async def override_result(ctx, winner: str, loser: str):
    if not await ensure_command_channel(ctx): return
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Only admins can override results.")
        return
    await handle_report(ctx, winner, loser, override=True)

async def handle_report(ctx, winner, loser, override=False):
    global current_round, tournament_matches, champion
    match_reports.append((winner, loser))
    tournament_matches = [match for match in tournament_matches if set(match) != set((winner, loser))]
    winners_by_round.setdefault(current_round, []).append(winner)
    tournament_channel = discord.utils.get(ctx.guild.text_channels, name=TOURNAMENT_CHANNEL_NAME)
    if tournament_channel:
        await tournament_channel.send(f"Match {'overridden' if override else 'reported'}: **{winner}** beat **{loser}**")
    if not tournament_matches:
        if len(winners_by_round[current_round]) == 1:
            champion = winners_by_round[current_round][0]
            await tournament_channel.send(f"**Tournament Winner: {champion}! Congratulations!**")
        else:
            current_round += 1
            next_teams = winners_by_round[current_round - 1]
            random.shuffle(next_teams)
            tournament_matches.clear()
            match_schedule.clear()
            for i in range(0, len(next_teams), 2):
                if i + 1 < len(next_teams):
                    match = (next_teams[i], next_teams[i + 1])
                    tournament_matches.append(match)
                    match_schedule[match] = datetime.now().strftime("%I:%M %p EST")
                    last_report_times[match] = datetime.now()
                else:
                    tournament_matches.append((next_teams[i], "BYE"))
                    winners_by_round.setdefault(current_round, []).append(next_teams[i])
            await tournament_channel.send(f"**Round {current_round} Matchups:**")
            for match in tournament_matches:
                if match[1] == "BYE":
                    await tournament_channel.send(f"**{match[0]}** gets a BYE")
                else:
                    await tournament_channel.send(f"**{match[0]}** vs **{match[1]}**")

@bot.command()
async def winner(ctx, *, team_name):
    global champion
    champion = team_name
    await ctx.send(f"**Tournament Winner Manually Set: {champion}! Congratulations!**")

@bot.command()
async def teams_list(ctx):
    if not await ensure_command_channel(ctx): return
    summary = "\n".join([f"<@{uid}>: {info.get('gamertag', 'Unknown')} - {info.get('team', 'No team')}" for uid, info in teams.items()])
    await ctx.send(f"**Registered Players and Teams:**\n{summary}")

@bot.command()
async def matches(ctx):
    if not await ensure_command_channel(ctx): return
    if not match_reports:
        await ctx.send("No match reports yet.")
    else:
        report_str = "\n".join([f"{w} beat {l}" for w, l in match_reports])
        await ctx.send(f"**Match Results:**\n{report_str}")

@bot.command()
async def leaderboard(ctx):
    if not await ensure_command_channel(ctx): return
    team_wins = {}
    for winner, _ in match_reports:
        team_wins[winner] = team_wins.get(winner, 0) + 1
    if not team_wins:
        await ctx.send("No match results yet.")
        return
    leaderboard = sorted(team_wins.items(), key=lambda x: x[1], reverse=True)
    lines = [f"{team}: {wins} win(s)" for team, wins in leaderboard]
    await ctx.send("**Leaderboard:**\n" + "\n".join(lines))

@bot.command()
async def status(ctx):
    if not await ensure_command_channel(ctx): return
    if not tournament_started:
        await ctx.send("Tournament hasn't started yet.")
        return
    embed = discord.Embed(title=f"Tournament Status - Round {current_round}", color=0x00ff00)
    embed.add_field(name="Current Matches", value="\n".join([f"{a} vs {b}" for a, b in tournament_matches]), inline=False)
    if match_reports:
        embed.add_field(name="Completed Matches", value="\n".join([f"{w} beat {l}" for w, l in match_reports]), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def welcome_embed(ctx):
    if not await ensure_command_channel(ctx): return
    embed = discord.Embed(
        title="Welcome to the COD Tournament Hub!",
        description="Follow these steps to get started and compete:",
        color=0x00bfff
    )
    embed.add_field(
        name="1. Register with Your Activision ID",
        value="In `#bot-commands`, type: `!register YourActivisionID`\n(This is required to compete)",
        inline=False
    )
    embed.add_field(
        name="2. Create or Join a Team",
        value="Lead a team: `!create_team TeamName`\nJoin one: `!join_team TeamName`",
        inline=False
    )
    embed.add_field(
        name="3. Manage Your Roster",
        value="Captains only:\n- Swap players: `!change_player @Old @New`\n- View team: `!team_info TeamName`",
        inline=False
    )
    embed.add_field(
        name="4. Report Matches",
        value="Use `!report WinnerTeam LoserTeam` after your game\nAdmins: `!override_result Winner Loser`",
        inline=False
    )
    embed.add_field(
        name="5. Check Progress",
        value="Use these anytime:\n`!status`, `!matches`, `!leaderboard`, `!teams_list`, `!commands`",
        inline=False
    )
    embed.add_field(
        name="Important Rules",
        value="Use `#bot-commands` for commands\nCheck `#tournament` for brackets\nMissing matches = auto disqualification",
        inline=False
    )
    embed.set_footer(text="Let’s compete fair and have fun — good luck, soldiers!")
    await ctx.send(embed=embed)

@bot.command(name="commands")
async def show_commands(ctx):
    if not await ensure_command_channel(ctx): return
    help_text = """
**Tournament Bot Commands**

__Setup & Registration:__
`!register [gamertag]` – Register yourself with a gamertag  
`!create_team [team_name]` – Create a new team  
`!join_team [team_name]` – Join an existing team  
`!change_player @old @new` – Captain only: replace a player  

__Tournament Setup:__
`!set_team_size [number]` – Set players per team  
`!set_tournament_date [YYYY-MM-DD]` – Set auto start date  
`!start_tournament` – Manually start the tournament  

__Testing & Debugging:__
`!test_mode` – Load 8 fake teams for dry run  

__Match Management:__
`!report [winner] [loser]` – Report match result  
`!override_result [winner] [loser]` – Admin: override result  
`!winner [team_name]` – Manually declare winner  

__Info & Monitoring:__
`!status` – View current round + matches  
`!matches` – View completed match results  
`!leaderboard` – View current rankings  
`!teams_list` – List all players and their teams  
`!team_info [team_name]` – Captain only: view team roster
"""
    await ctx.send(help_text)

keep_alive()
bot.run(os.getenv('TOKEN'))