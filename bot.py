import asyncio
import aiohttp
import os
from datetime import datetime
from typing import Optional, Dict, Any, Set
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ========== КОНФИГУРАЦИЯ ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
BSD_API_TOKEN = os.environ.get("BSD_API_TOKEN")

CHELSEA_TEAM_ID = 13
PREMIER_LEAGUE_ID = 17
BSD_BASE_URL = "https://sports.bzzoiro.com/api/v2"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

active_matches: Dict[int, Dict] = {}
sent_incidents: Dict[int, Set[int]] = {}

# Настройки (хранятся в памяти, при перезапуске сбрасываются)
send_goal_photos = True


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_headers() -> dict:
    return {"Authorization": f"Token {BSD_API_TOKEN}"}


async def bsd_request(endpoint: str, params: dict = None) -> Optional[dict]:
    url = f"{BSD_BASE_URL}/{endpoint}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=get_headers(), params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"BSD API error {resp.status}: {await resp.text()}")
                    return None
        except Exception as e:
            print(f"Request error: {e}")
            return None


async def get_chelsea_live_matches() -> list:
    data = await bsd_request("events/live/", {"team_id": CHELSEA_TEAM_ID})
    if data and "events" in data:
        return [e for e in data["events"] if e["status"] == "inprogress"]
    return []


async def get_match_detail(event_id: int) -> Optional[dict]:
    return await bsd_request(f"events/{event_id}/")


async def get_match_incidents(event_id: int) -> Optional[dict]:
    return await bsd_request(f"events/{event_id}/incidents/")


async def get_match_stats(event_id: int) -> Optional[dict]:
    return await bsd_request(f"events/{event_id}/stats/")


async def get_chelsea_next_match() -> Optional[dict]:
    data = await bsd_request("events/", {
        "team_id": CHELSEA_TEAM_ID,
        "status": "notstarted",
        "date_from": datetime.now().strftime("%Y-%m-%d"),
        "limit": 1
    })
    if data and data.get("results"):
        return data["results"][0]
    return None


async def get_table() -> Optional[dict]:
    return await bsd_request(f"leagues/{PREMIER_LEAGUE_ID}/standings/")


async def get_current_live_match_info() -> Optional[dict]:
    live_matches = await get_chelsea_live_matches()
    if live_matches:
        return await get_match_detail(live_matches[0]["id"])
    return None


async def get_player_photo(player_id: int) -> Optional[str]:
    """Получить URL фото игрока"""
    return f"https://sports.bzzoiro.com/img/player/{player_id}/"


async def get_match_prediction(event_id: int) -> Optional[dict]:
    """Получить AI-прогноз на матч"""
    return await bsd_request(f"events/{event_id}/prediction/")


async def get_broadcasts(event_id: int) -> Optional[dict]:
    """Получить ТВ-каналы для матча"""
    return await bsd_request(f"events/{event_id}/broadcasts/")


async def get_team_photo(team_id: int) -> str:
    """Получить URL логотипа команды"""
    return f"https://sports.bzzoiro.com/img/team/{team_id}/"


# ========== ФОРМАТТЕРЫ СООБЩЕНИЙ (АНГЛИЙСКИЙ) ==========

def format_kickoff(event: dict) -> str:
    home = event.get("home_team", "Chelsea")
    away = event.get("away_team", "Opponent")
    is_home = (home == "Chelsea")
    
    if is_home:
        return (
            f"🏟️ **MATCH STARTED**\n\n"
            f"┌─────────────────────────────────────┐\n"
            f"│  🔵 Chelsea vs {away} 🔴\n"
            f"│  📍 Stamford Bridge\n"
            f"│  🏆 {event.get('league_name', 'Premier League')}\n"
            f"└─────────────────────────────────────┘\n\n"
            f"#CHELSEA #LIVE"
        )
    else:
        return (
            f"🏟️ **MATCH STARTED**\n\n"
            f"┌─────────────────────────────────────┐\n"
            f"│  {home} 🔴 vs 🔵 Chelsea\n"
            f"│  📍 Away Game\n"
            f"│  🏆 {event.get('league_name', 'Premier League')}\n"
            f"└─────────────────────────────────────┘\n\n"
            f"#CHELSEA #LIVE"
        )


def format_goal(incident: dict, home_team: str, away_team: str, scores: dict) -> str:
    minute = incident.get("minute", "?")
    player = incident.get("player", "Unknown")
    player_id = incident.get("player_id")
    is_home = incident.get("is_home", True)
    is_chelsea_goal = (is_home and home_team == "Chelsea") or (not is_home and away_team == "Chelsea")
    
    goal_team = home_team if is_home else away_team
    
    if is_chelsea_goal:
        message = (
            f"⚽ **GOAL!** ⚽\n\n"
            f"┌─────────────────────────────────────┐\n"
            f"│  🔵 Chelsea\n"
            f"│  🌟 {player}\n"
            f"│  ⏱️ {minute}'\n"
            f"├─────────────────────────────────────┤\n"
            f"│  📊 SCORE: {home_team} {scores.get('home', 0)} — {scores.get('away', 0)} {away_team}\n"
            f"└─────────────────────────────────────┘"
        )
    else:
        message = (
            f"⚠️ **GOAL CONCEDED** ⚠️\n\n"
            f"┌─────────────────────────────────────┐\n"
            f"│  {goal_team}\n"
            f"│  🌟 {player}\n"
            f"│  ⏱️ {minute}'\n"
            f"├─────────────────────────────────────┤\n"
            f"│  📊 SCORE: {home_team} {scores.get('home', 0)} — {scores.get('away', 0)} {away_team}\n"
            f"└─────────────────────────────────────┘"
        )
    
    return message


def format_card(incident: dict, home_team: str, away_team: str) -> str:
    minute = incident.get("minute", "?")
    player = incident.get("player", "Unknown")
    card_type = incident.get("card_type", "yellow")
    is_home = incident.get("is_home", True)
    is_chelsea_card = (is_home and home_team == "Chelsea") or (not is_home and away_team == "Chelsea")
    
    team = home_team if is_home else away_team
    
    if card_type == "yellow":
        if is_chelsea_card:
            return (
                f"🟨 **YELLOW CARD**\n\n"
                f"┌─────────────────────────────────────┐\n"
                f"│  🔵 Chelsea\n"
                f"│  👤 {player}\n"
                f"│  ⏱️ {minute}'\n"
                f"└─────────────────────────────────────┘"
            )
        else:
            return (
                f"🟨 **YELLOW CARD**\n\n"
                f"┌─────────────────────────────────────┐\n"
                f"│  {team}\n"
                f"│  👤 {player}\n"
                f"│  ⏱️ {minute}'\n"
                f"└─────────────────────────────────────┘"
            )
    else:
        if is_chelsea_card:
            return (
                f"🟥 **RED CARD**\n\n"
                f"┌─────────────────────────────────────┐\n"
                f"│  🔵 Chelsea\n"
                f"│  👤 {player}\n"
                f"│  ⏱️ {minute}'\n"
                f"│  ⚠️ Chelsea down to 10 men\n"
                f"└─────────────────────────────────────┘"
            )
        else:
            return (
                f"🟥 **RED CARD**\n\n"
                f"┌─────────────────────────────────────┐\n"
                f"│  {team}\n"
                f"│  👤 {player}\n"
                f"│  ⏱️ {minute}'\n"
                f"│  ✅ Advantage Chelsea\n"
                f"└─────────────────────────────────────┘"
            )


def format_substitution(incident: dict, home_team: str, away_team: str) -> str:
    minute = incident.get("minute", "?")
    player_in = incident.get("player_in", "Unknown")
    player_out = incident.get("player_out", "Unknown")
    is_home = incident.get("is_home", True)
    team = home_team if is_home else away_team
    is_chelsea = (team == "Chelsea")
    
    team_prefix = "🔵" if is_chelsea else "⚪"
    
    return (
        f"🔄 **SUBSTITUTION**\n\n"
        f"┌─────────────────────────────────────┐\n"
        f"│  {team_prefix} {team}\n"
        f"│  ⏱️ {minute}'\n"
        f"│  ⬆️ {player_in} IN\n"
        f"│  ⬇️ {player_out} OUT\n"
        f"└─────────────────────────────────────┘"
    )


def format_half_time(stats: dict, event_detail: dict) -> str:
    home_stats = stats.get("stats", {}).get("home", {})
    away_stats = stats.get("stats", {}).get("away", {})
    
    home = event_detail.get("home_team", "Home")
    away = event_detail.get("away_team", "Away")
    home_score = event_detail.get("home_score", 0)
    away_score = event_detail.get("away_score", 0)
    
    corners_h = home_stats.get("crosses", {})
    corners_a = away_stats.get("crosses", {})
    if isinstance(corners_h, dict):
        corners_h = corners_h.get("value", 0)
    if isinstance(corners_a, dict):
        corners_a = corners_a.get("value", 0)
    
    return (
        f"⏸️ **HALF-TIME**\n\n"
        f"┌─────────────────────────────────────┐\n"
        f"│  📊 {home} {home_score} — {away_score} {away}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  🧭 POSSESSION   {home_stats.get('ball_possession', 0)}%  —  {away_stats.get('ball_possession', 0)}%\n"
        f"│  🎯 SHOTS        {home_stats.get('total_shots', 0)}  —  {away_stats.get('total_shots', 0)}\n"
        f"│  🎪 ON TARGET    {home_stats.get('shots_on_target', 0)}  —  {away_stats.get('shots_on_target', 0)}\n"
        f"│  🚩 CORNERS      {corners_h}  —  {corners_a}\n"
        f"│  📞 PASS ACC (%) {home_stats.get('pass_accuracy_pct', 0)}%  —  {away_stats.get('pass_accuracy_pct', 0)}%\n"
        f"└─────────────────────────────────────┘"
    )


def format_full_time(stats: dict, event_detail: dict) -> str:
    home_stats = stats.get("stats", {}).get("home", {})
    away_stats = stats.get("stats", {}).get("away", {})
    
    home = event_detail.get("home_team", "Home")
    away = event_detail.get("away_team", "Away")
    home_score = event_detail.get("home_score", 0)
    away_score = event_detail.get("away_score", 0)
    
    home_xg = home_stats.get("xg", {}).get("actual", 0)
    away_xg = away_stats.get("xg", {}).get("actual", 0)
    
    corners_h = home_stats.get("crosses", {})
    corners_a = away_stats.get("crosses", {})
    if isinstance(corners_h, dict):
        corners_h = corners_h.get("value", 0)
    if isinstance(corners_a, dict):
        corners_a = corners_a.get("value", 0)
    
    if home_score > away_score:
        result = "🏆 CHELSEA WIN"
    elif home_score < away_score:
        result = "📉 DEFEAT"
    else:
        result = "🤝 DRAW"
    
    return (
        f"🏁 **FULL-TIME**\n\n"
        f"┌─────────────────────────────────────┐\n"
        f"│  📊 {home} {home_score} — {away_score} {away}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  🧭 POSSESSION   {home_stats.get('ball_possession', 0)}%  —  {away_stats.get('ball_possession', 0)}%\n"
        f"│  🎯 SHOTS        {home_stats.get('total_shots', 0)}  —  {away_stats.get('total_shots', 0)}\n"
        f"│  🎪 ON TARGET    {home_stats.get('shots_on_target', 0)}  —  {away_stats.get('shots_on_target', 0)}\n"
        f"│  🚩 CORNERS      {corners_h}  —  {corners_a}\n"
        f"│  📐 xG           {home_xg:.1f}  —  {away_xg:.1f}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  🏁 RESULT: {result}\n"
        f"└─────────────────────────────────────┘\n\n"
        f"#CHELSEA #CFC"
    )


def format_next_match(match: dict) -> str:
    date_str = match.get("event_date", "").replace("Z", "+00:00")
    event_date = datetime.fromisoformat(date_str)
    home = match.get("home_team", "Chelsea")
    away = match.get("away_team", "Unknown")
    league = match.get("league_name", "Premier League")
    is_home = (home == "Chelsea")
    
    location = "🏟️ Stamford Bridge" if is_home else "✈️ Away Game"
    
    return (
        f"🔵 **NEXT CHELSEA MATCH**\n\n"
        f"┌─────────────────────────────────────┐\n"
        f"│  🆚 {home} vs {away}\n"
        f"│  🏆 {league}\n"
        f"│  📅 {event_date.strftime('%A, %B %d, %Y')}\n"
        f"│  ⏰ {event_date.strftime('%H:%M GMT')}\n"
        f"│  📍 {location}\n"
        f"└─────────────────────────────────────┘"
    )


def format_table(standings: dict) -> str:
    if not standings or not standings.get("standings"):
        return "❌ Table not available"
    
    lines = ["🏆 **PREMIER LEAGUE TABLE**\n"]
    lines.append("┌────┬────────────────────┬─────┬─────┬─────┐")
    lines.append("│ #  │ TEAM               │  P  │  PTS│ GD  │")
    lines.append("├────┼────────────────────┼─────┼─────┼─────┤")
    
    for row in standings["standings"][:10]:
        pos = row.get("position", "?")
        team = row.get("team_name", "Unknown")
        pts = row.get("pts", 0)
        played = row.get("played", 0)
        gd = row.get("gd", 0)
        
        if len(team) > 18:
            team = team[:16] + ".."
        
        if "Chelsea" in team:
            team = f"🔵{team[1:]}" if team.startswith("🔵") else f"🔵 {team}"
            lines.append(f"│ {pos:2} │ {team:18} │ {played:3} │ {pts:3} │ {gd:+4} │")
        else:
            lines.append(f"│ {pos:2} │ {team:18} │ {played:3} │ {pts:3} │ {gd:+4} │")
    
    lines.append("└────┴────────────────────┴─────┴─────┴─────┘")
    
    return "\n".join(lines)


def format_prediction(prediction: dict, match: dict) -> str:
    """Форматирует AI-прогноз на матч"""
    if not prediction or "markets" not in prediction:
        return "❌ Prediction not available for this match"
    
    markets = prediction.get("markets", {})
    match_result = markets.get("match_result", {})
    expected_goals = markets.get("expected_goals", {})
    over_under = markets.get("over_under", {})
    btts = markets.get("btts", {})
    score = markets.get("score", {})
    recommendations = prediction.get("recommendations", {})
    
    home_team = match.get("home_team", "Chelsea")
    away_team = match.get("away_team", "Opponent")
    
    # Определяем предсказанный исход
    predicted = match_result.get("predicted", "?")
    if predicted == "H":
        predicted_text = f"🏠 {home_team} win"
    elif predicted == "A":
        predicted_text = f"✈️ {away_team} win"
    else:
        predicted_text = "🤝 Draw"
    
    message = (
        f"🧠 **AI MATCH PREDICTION**\n\n"
        f"┌─────────────────────────────────────┐\n"
        f"│  🆚 {home_team} vs {away_team}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  📊 MATCH RESULT:\n"
        f"│     {home_team}: {match_result.get('prob_home', 0):.1f}%\n"
        f"│     Draw: {match_result.get('prob_draw', 0):.1f}%\n"
        f"│     {away_team}: {match_result.get('prob_away', 0):.1f}%\n"
        f"│     → Predicted: {predicted_text}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  ⚽ EXPECTED GOALS (xG):\n"
        f"│     {home_team}: {expected_goals.get('home', 0):.2f}\n"
        f"│     {away_team}: {expected_goals.get('away', 0):.2f}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  📈 OVER/UNDER:\n"
        f"│     Over 1.5: {over_under.get('prob_over_15', 0):.1f}%\n"
        f"│     Over 2.5: {over_under.get('prob_over_25', 0):.1f}%\n"
        f"│     Over 3.5: {over_under.get('prob_over_35', 0):.1f}%\n"
        f"├─────────────────────────────────────┤\n"
        f"│  🤝 BOTH TEAMS TO SCORE:\n"
        f"│     YES: {btts.get('prob_yes', 0):.1f}%\n"
        f"├─────────────────────────────────────┤\n"
        f"│  🎯 MOST LIKELY SCORE:\n"
        f"│     {score.get('most_likely', 'N/A')}\n"
        f"├─────────────────────────────────────┤\n"
        f"│  💡 RECOMMENDATIONS:\n"
    )
    
    if recommendations.get("bet_favorite"):
        message += f"│     ✓ Bet on favorite\n"
    if recommendations.get("over_25"):
        message += f"│     ✓ Over 2.5 goals\n"
    if recommendations.get("btts"):
        message += f"│     ✓ Both teams to score\n"
    
    message += (
        f"└─────────────────────────────────────┘\n\n"
        f"🤖 AI confidence: {prediction.get('model', {}).get('confidence', 0):.0%}\n"
        f"#CHELSEA #PREDICTION"
    )
    
    return message


def format_injuries(lineups: dict) -> str:
    """Форматирует список травмированных/дисквалифицированных игроков"""
    if not lineups or lineups.get("lineup_status") != "confirmed":
        return None
    
    unavailable = lineups.get("unavailable_players", {})
    chelsea_unavailable = unavailable.get("home", []) if unavailable else []
    
    if not chelsea_unavailable:
        return None
    
    message = "📋 **INJURIES & SUSPENSIONS**\n\n┌─────────────────────────────────────┐\n"
    for player in chelsea_unavailable[:5]:  # Показываем до 5 игроков
        name = player.get("name", "Unknown")
        status = player.get("status", "unavailable")
        reason = player.get("reason", "")
        status_emoji = "🟡" if status == "doubtful" else "❌"
        message += f"│  {status_emoji} {name} — {reason if reason else status}\n"
    
    message += "└─────────────────────────────────────┘"
    return message


def format_broadcasts(broadcasts: dict) -> str:
    """Форматирует ТВ-каналы для матча"""
    if not broadcasts or not broadcasts.get("results"):
        return None
    
    channels = []
    countries_shown = set()
    
    for b in broadcasts["results"][:5]:  # Показываем до 5 каналов
        country = b.get("country_code", "")
        if country in countries_shown:
            continue
        countries_shown.add(country)
        channel = b.get("channel_name", "Unknown")
        channels.append(f"│  📺 {country}: {channel}")
    
    if not channels:
        return None
    
    message = "📡 **WHERE TO WATCH**\n\n┌─────────────────────────────────────┐\n"
    message += "\n".join(channels)
    message += "\n└─────────────────────────────────────┘"
    return message


# ========== КОМАНДЫ БОТА ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🔵 **Chelsea FC Live Bot**\n\n"
        "I broadcast Chelsea matches in real-time.\n\n"
        "📺 Goals, cards, substitutions, stats\n\n"
        "Type /help to see all commands."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """/help — на русском только для админа, иначе на английском"""
    if message.from_user.id == ADMIN_ID:
        # Русская версия для админа
        help_text = (
            "🔵 **Chelsea FC Live Bot — Справка**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**📺 АВТОМАТИЧЕСКИЕ ТРАНСЛЯЦИИ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚽ **ГОЛЫ** — кто забил, минута, счёт\n"
            "🟨🟥 **КАРТОЧКИ** — игрок, минута\n"
            "🔄 **ЗАМЕНЫ** — кто вышел/ушёл\n"
            "📊 **СТАТИСТИКА** — владение, удары, угловые, xG\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**🎮 КОМАНДЫ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/start — Приветствие\n"
            "/help — Эта справка\n"
            "/next — Следующий матч\n"
            "/table — Таблица АПЛ\n"
            "/status — Статус бота\n"
            "/predict — AI прогноз на следующий матч\n"
            "/injuries — Травмы и дисквалификации\n"
            "/wheretowatch — ТВ-каналы на следующий матч\n"
            "/goalphoto — Вкл/выкл фото игроков при голах\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**📱 КАК ИСПОЛЬЗОВАТЬ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Добавьте бота в группу\n"
            "2️⃣ Сделайте бота АДМИНИСТРАТОРОМ\n"
            "3️⃣ Ждите матч — всё автоматически\n\n"
            "🔵💪 #KTBFFH"
        )
        await message.answer(help_text, parse_mode="Markdown")
    else:
        # Английская версия для всех остальных
        help_text = (
            "🔵 **Chelsea FC Live Bot — Help**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**📺 AUTOMATIC LIVE UPDATES**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚽ **GOALS** — scorer, minute, score\n"
            "🟨🟥 **CARDS** — player, minute\n"
            "🔄 **SUBSTITUTIONS** — in/out\n"
            "📊 **STATISTICS** — possession, shots, corners, xG\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**🎮 COMMANDS**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/start — Welcome message\n"
            "/help — This help\n"
            "/next — Next Chelsea match\n"
            "/table — Premier League table\n"
            "/status — Bot status\n"
            "/predict — AI prediction for next match\n"
            "/injuries — Injuries & suspensions\n"
            "/wheretowatch — TV channels for next match\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**📱 HOW TO USE**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Add bot to your Chelsea fan group\n"
            "2️⃣ Make the bot an ADMIN\n"
            "3️⃣ Wait for the next match — everything is automatic!\n\n"
            "🔵💪 #KTBFFH"
        )
        await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    current_match = await get_current_live_match_info()
    
    status_text = (
        "🔵 **BOT STATUS**\n\n"
        f"✅ Chelsea Team ID: `{CHELSEA_TEAM_ID}`\n"
        f"✅ Premier League ID: `{PREMIER_LEAGUE_ID}`\n"
        f"✅ Active matches tracked: {len(active_matches)}\n"
        f"✅ Goal photos: {'ON' if send_goal_photos else 'OFF'}\n"
        f"📡 Last check: {datetime.now().strftime('%H:%M:%S')} GMT\n"
    )
    
    if current_match:
        home = current_match.get("home_team", "Chelsea")
        away = current_match.get("away_team", "Opponent")
        home_score = current_match.get("home_score", 0)
        away_score = current_match.get("away_score", 0)
        period = current_match.get("period", "inprogress")
        minute = current_match.get("current_minute", "?")
        
        if period == "1st_half":
            period_text = f"FIRST HALF, {minute}'"
        elif period == "2nd_half":
            period_text = f"SECOND HALF, {minute}'"
        elif period == "halftime":
            period_text = "HALF-TIME"
        else:
            period_text = "MATCH IN PROGRESS"
        
        status_text += (
            f"\n🔴 **LIVE MATCH!**\n\n"
            f"┌─────────────────────────────────────┐\n"
            f"│  {home} {home_score} — {away_score} {away}\n"
            f"│  ⏱️ {period_text}\n"
            f"└─────────────────────────────────────┘"
        )
    else:
        next_match = await get_chelsea_next_match()
        if next_match:
            date_str = next_match.get("event_date", "").replace("Z", "+00:00")
            try:
                event_date = datetime.fromisoformat(date_str)
                status_text += f"\n⚽ Next match:\n   {next_match.get('home_team')} vs {next_match.get('away_team')} — {event_date.strftime('%d %b %H:%M')}"
            except:
                status_text += "\n⚽ Next match: date unknown"
        else:
            status_text += "\n⚽ Next match: not found"
    
    await message.answer(status_text, parse_mode="Markdown")


@dp.message(Command("next"))
async def cmd_next_match(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    match = await get_chelsea_next_match()
    if match:
        await bot.send_message(CHAT_ID, format_next_match(match))
    else:
        await bot.send_message(CHAT_ID, "❌ No upcoming matches found")


@dp.message(Command("table"))
async def cmd_table(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    data = await get_table()
    if data:
        await bot.send_message(CHAT_ID, format_table(data))
    else:
        await bot.send_message(CHAT_ID, "❌ Failed to load table")


@dp.message(Command("predict"))
async def cmd_predict(message: Message):
    """AI прогноз на следующий матч Челси"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    next_match = await get_chelsea_next_match()
    if not next_match:
        await bot.send_message(CHAT_ID, "❌ No upcoming matches found")
        return
    
    event_id = next_match.get("id")
    prediction = await get_match_prediction(event_id)
    
    if prediction:
        await bot.send_message(CHAT_ID, format_prediction(prediction, next_match), parse_mode="Markdown")
    else:
        await bot.send_message(CHAT_ID, "❌ AI prediction not available for this match")


@dp.message(Command("injuries"))
async def cmd_injuries(message: Message):
    """Травмы и дисквалификации Челси"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    next_match = await get_chelsea_next_match()
    if not next_match:
        await bot.send_message(CHAT_ID, "❌ No upcoming matches found")
        return
    
    event_id = next_match.get("id")
    lineups = await bsd_request(f"events/{event_id}/lineups/")
    
    injuries_text = format_injuries(lineups)
    if injuries_text:
        await bot.send_message(CHAT_ID, injuries_text, parse_mode="Markdown")
    else:
        await bot.send_message(CHAT_ID, "✅ No injuries or suspensions reported")


@dp.message(Command("wheretowatch"))
async def cmd_wheretowatch(message: Message):
    """ТВ-каналы для следующего матча"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    next_match = await get_chelsea_next_match()
    if not next_match:
        await bot.send_message(CHAT_ID, "❌ No upcoming matches found")
        return
    
    event_id = next_match.get("id")
    broadcasts = await get_broadcasts(event_id)
    
    broadcasts_text = format_broadcasts(broadcasts)
    if broadcasts_text:
        await bot.send_message(CHAT_ID, broadcasts_text, parse_mode="Markdown")
    else:
        await bot.send_message(CHAT_ID, "❌ TV broadcast information not available")


@dp.message(Command("goalphoto"))
async def cmd_goalphoto(message: Message):
    """Включить/выключить фото игроков при голах"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only.")
        return
    
    global send_goal_photos
    send_goal_photos = not send_goal_photos
    status = "ON" if send_goal_photos else "OFF"
    await message.answer(f"📸 Goal player photos: **{status}**", parse_mode="Markdown")


# ========== ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ==========

async def monitor_matches():
    global send_goal_photos
    
    while True:
        try:
            live_matches = await get_chelsea_live_matches()
            
            for match in live_matches:
                event_id = match["id"]
                detail = await get_match_detail(event_id)
                if not detail:
                    continue
                
                home = detail.get("home_team", "Chelsea")
                away = detail.get("away_team", "Opponent")
                period = detail.get("period")
                status = detail.get("status")
                
                # Новый матч (kick-off)
                if event_id not in active_matches:
                    if period == "1st_half" or (status == "inprogress" and match.get("current_minute", 0) >= 0):
                        active_matches[event_id] = {}
                        sent_incidents[event_id] = set()
                        await bot.send_message(CHAT_ID, format_kickoff(detail))
                        
                        # Также отправляем травмы перед матчем
                        lineups = await bsd_request(f"events/{event_id}/lineups/")
                        injuries_text = format_injuries(lineups)
                        if injuries_text:
                            await bot.send_message(CHAT_ID, injuries_text, parse_mode="Markdown")
                
                # Перерыв
                if event_id in active_matches and period == "halftime":
                    if not active_matches[event_id].get("halftime"):
                        stats = await get_match_stats(event_id)
                        if stats:
                            await bot.send_message(CHAT_ID, format_half_time(stats, detail))
                            active_matches[event_id]["halftime"] = True
                
                # События (голы, карточки, замены)
                incidents_data = await get_match_incidents(event_id)
                if incidents_data and "incidents" in incidents_data:
                    scores = {"home": detail.get("home_score", 0), "away": detail.get("away_score", 0)}
                    
                    for inc in incidents_data["incidents"]:
                        inc_key = hash(f"{inc.get('type')}_{inc.get('minute')}_{inc.get('player', '')}_{inc.get('player_in', '')}")
                        
                        if inc_key not in sent_incidents.get(event_id, set()):
                            sent_incidents.setdefault(event_id, set()).add(inc_key)
                            
                            if inc.get("type") == "goal":
                                message_text = format_goal(inc, home, away, scores)
                                
                                # Отправляем фото игрока, если включено и есть ID
                                if send_goal_photos:
                                    player_id = inc.get("player_id")
                                    if player_id:
                                        photo_url = await get_player_photo(player_id)
                                        try:
                                            await bot.send_photo(CHAT_ID, photo_url, caption=message_text, parse_mode="Markdown")
                                        except:
                                            await bot.send_message(CHAT_ID, message_text, parse_mode="Markdown")
                                    else:
                                        await bot.send_message(CHAT_ID, message_text, parse_mode="Markdown")
                                else:
                                    await bot.send_message(CHAT_ID, message_text, parse_mode="Markdown")
                                    
                            elif inc.get("type") == "card":
                                await bot.send_message(CHAT_ID, format_card(inc, home, away), parse_mode="Markdown")
                            elif inc.get("type") == "substitution":
                                await bot.send_message(CHAT_ID, format_substitution(inc, home, away), parse_mode="Markdown")
                
                # Финал матча
                if event_id in active_matches and status == "finished":
                    if not active_matches[event_id].get("fulltime"):
                        stats = await get_match_stats(event_id)
                        if stats:
                            await bot.send_message(CHAT_ID, format_full_time(stats, detail), parse_mode="Markdown")
                            active_matches[event_id]["fulltime"] = True
                            await asyncio.sleep(60)
                            active_matches.pop(event_id, None)
                            sent_incidents.pop(event_id, None)
            
            await asyncio.sleep(30)
            
        except Exception as e:
            print(f"Monitor error: {e}")
            await asyncio.sleep(60)


async def main():
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
