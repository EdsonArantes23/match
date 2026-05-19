import asyncio
import aiohttp
import os
from datetime import datetime
from typing import Optional, Dict, Any, Set
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ========== КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
BSD_API_TOKEN = os.environ.get("BSD_API_TOKEN")

# ID Челси в BSD API (нужно найти один раз и указать здесь)
# Чтобы найти: curl -H "Authorization: Token $BSD_API_TOKEN" "https://sports.bzzoiro.com/api/v2/teams/?name=Chelsea"
CHELSEA_TEAM_ID = 42  # ← ЗАМЕНИТЕ НА ПРАВИЛЬНЫЙ ID ПОСЛЕ ПЕРВОГО ЗАПУСКА
PREMIER_LEAGUE_ID = 17
BSD_BASE_URL = "https://sports.bzzoiro.com/api/v2"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Хранилище активных матчей и отправленных событий
active_matches: Dict[int, Dict] = {}
sent_incidents: Dict[int, Set[int]] = {}


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_headers() -> dict:
    return {"Authorization": f"Token {BSD_API_TOKEN}"}


async def bsd_request(endpoint: str, params: dict = None) -> Optional[dict]:
    """Запрос к BSD API"""
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
    """Активные матчи Челси"""
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
    """Следующий матч Челси"""
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
    """Турнирная таблица АПЛ"""
    return await bsd_request(f"leagues/{PREMIER_LEAGUE_ID}/standings/")


# ========== ФОРМАТТЕРЫ СООБЩЕНИЙ ==========

def format_kickoff(event: dict) -> str:
    home = event.get("home_team", "Chelsea")
    away = event.get("away_team", "Opponent")
    return f"⚽ **KICK-OFF!** {home} vs {away} is underway.\n🔵💪 Come on Chelsea!\n\n#LIVE #CHELSEA"


def format_goal(incident: dict, home_team: str, away_team: str, scores: dict) -> str:
    minute = incident.get("minute", "?")
    player = incident.get("player", "Unknown")
    is_home = incident.get("is_home", True)
    team = home_team if is_home else away_team
    
    return (
        f"⚽ **GOAL!** ⚽\n\n"
        f"**{player}** ({team}) - {minute}'\n"
        f"🎯 {home_team} {scores.get('home', 0)} - {scores.get('away', 0)} {away_team}"
    )


def format_card(incident: dict, home_team: str, away_team: str) -> str:
    minute = incident.get("minute", "?")
    player = incident.get("player", "Unknown")
    card_type = incident.get("card_type", "yellow")
    is_home = incident.get("is_home", True)
    team = home_team if is_home else away_team
    
    emoji = "🟨" if card_type == "yellow" else "🟥"
    card_name = "YELLOW CARD" if card_type == "yellow" else "RED CARD"
    return f"{emoji} **{card_name}**\n\n**{player}** ({team}) - {minute}'"


def format_substitution(incident: dict, home_team: str, away_team: str) -> str:
    minute = incident.get("minute", "?")
    player_in = incident.get("player_in", "Unknown")
    player_out = incident.get("player_out", "Unknown")
    is_home = incident.get("is_home", True)
    team = home_team if is_home else away_team
    
    return (
        f"🔄 **SUBSTITUTION**\n\n"
        f"**{team}** - {minute}'\n"
        f"⬆️ {player_in} IN\n"
        f"⬇️ {player_out} OUT"
    )


def format_half_time(event_id: int, stats: dict, event_detail: dict) -> str:
    home_stats = stats.get("stats", {}).get("home", {})
    away_stats = stats.get("stats", {}).get("away", {})
    
    home = event_detail.get("home_team", "Home")
    away = event_detail.get("away_team", "Away")
    home_score = event_detail.get("home_score", 0)
    away_score = event_detail.get("away_score", 0)
    
    # Угловые могут быть в формате {value, total, pct}
    corners_h = home_stats.get("crosses", {})
    corners_a = away_stats.get("crosses", {})
    if isinstance(corners_h, dict):
        corners_h = corners_h.get("value", 0)
    if isinstance(corners_a, dict):
        corners_a = corners_a.get("value", 0)
    
    return (
        f"⏸️ **HALF-TIME: {home} {home_score} - {away_score} {away}** ⏸️\n\n"
        f"📊 **Stats:**\n\n"
        f"• Possession: {home_stats.get('ball_possession', 0)}% vs {away_stats.get('ball_possession', 0)}%\n"
        f"• Shots: {home_stats.get('total_shots', 0)} ({home_stats.get('shots_on_target', 0)} on target) vs {away_stats.get('total_shots', 0)} ({away_stats.get('shots_on_target', 0)})\n"
        f"• Corners: {corners_h} vs {corners_a}\n"
        f"• Pass accuracy: {home_stats.get('pass_accuracy_pct', 0)}% vs {away_stats.get('pass_accuracy_pct', 0)}%"
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
    
    result = "WIN! 💪" if home_score > away_score else "LOSS 😔" if home_score < away_score else "DRAW 🤝"
    
    return (
        f"🏁 **FULL-TIME: {home} {home_score} - {away_score} {away}** 🏁\n\n"
        f"📊 **Final stats:**\n\n"
        f"• Possession: {home_stats.get('ball_possession', 0)}% vs {away_stats.get('ball_possession', 0)}%\n"
        f"• Shots: {home_stats.get('total_shots', 0)} ({home_stats.get('shots_on_target', 0)} on target) vs {away_stats.get('total_shots', 0)} ({away_stats.get('shots_on_target', 0)})\n"
        f"• Corners: {corners_h} vs {corners_a}\n"
        f"• xG: {home_xg:.1f} vs {away_xg:.1f}\n\n"
        f"🏆 **Result: {result}**\n\n"
        f"🔵💪 KTBFFH!\n\n#CHELSEA #CFC"
    )


def format_next_match(match: dict) -> str:
    date_str = match.get("event_date", "").replace("Z", "+00:00")
    event_date = datetime.fromisoformat(date_str)
    home = match.get("home_team", "Chelsea")
    away = match.get("away_team", "Unknown")
    league = match.get("league_name", "Premier League")
    
    return (
        f"🔵 **Next Chelsea Match** 🔵\n\n"
        f"🆚 **{home} vs {away}**\n"
        f"🏆 {league}\n"
        f"📅 {event_date.strftime('%A, %B %d, %Y')}\n"
        f"⏰ {event_date.strftime('%H:%M GMT')}"
    )


def format_table(standings: dict) -> str:
    if not standings or not standings.get("standings"):
        return "❌ Table not available"
    
    lines = ["🏆 **Premier League Table**\n"]
    for row in standings["standings"][:10]:
        pos = row.get("position", "?")
        team = row.get("team_name", "Unknown")
        pts = row.get("pts", 0)
        played = row.get("played", 0)
        gd = row.get("gd", 0)
        
        if "Chelsea" in team:
            team = f"🔵 **{team}**"
        
        lines.append(f"{pos}. {team} - {pts} pts ({played} played, GD: {gd})")
    
    return "\n".join(lines)


# ========== КОМАНДЫ БОТА ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🔵 **Chelsea Match Bot** 🔵\n\n"
        "Автоматические трансляции матчей Челси:\n"
        "⚽ Голы\n"
        "🟨 Карточки\n"
        "🔄 Замены\n"
        "📊 Статистика\n\n"
        "**Команды (только для админа):**\n"
        "/next - следующий матч\n"
        "/table - таблица АПЛ"
    )


@dp.message(Command("next"))
async def cmd_next_match(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    match = await get_chelsea_next_match()
    if match:
        await bot.send_message(CHAT_ID, format_next_match(match))
    else:
        await bot.send_message(CHAT_ID, "❌ No upcoming matches found")


@dp.message(Command("table"))
async def cmd_table(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    data = await get_table()
    if data:
        await bot.send_message(CHAT_ID, format_table(data))
    else:
        await bot.send_message(CHAT_ID, "❌ Failed to load table")


# ========== ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ==========

async def monitor_matches():
    """Фоновая задача: проверяет live матчи и отправляет события"""
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
                
                # Перерыв
                if event_id in active_matches and period == "halftime":
                    if not active_matches[event_id].get("halftime"):
                        stats = await get_match_stats(event_id)
                        if stats:
                            await bot.send_message(CHAT_ID, format_half_time(event_id, stats, detail))
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
                                await bot.send_message(CHAT_ID, format_goal(inc, home, away, scores))
                            elif inc.get("type") == "card":
                                await bot.send_message(CHAT_ID, format_card(inc, home, away))
                            elif inc.get("type") == "substitution":
                                await bot.send_message(CHAT_ID, format_substitution(inc, home, away))
                
                # Финал матча
                if event_id in active_matches and status == "finished":
                    if not active_matches[event_id].get("fulltime"):
                        stats = await get_match_stats(event_id)
                        if stats:
                            await bot.send_message(CHAT_ID, format_full_time(stats, detail))
                            active_matches[event_id]["fulltime"] = True
                            await asyncio.sleep(60)
                            active_matches.pop(event_id, None)
                            sent_incidents.pop(event_id, None)
            
            await asyncio.sleep(30)  # Пауза 30 секунд между проверками
            
        except Exception as e:
            print(f"Monitor error: {e}")
            await asyncio.sleep(60)


async def main():
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())