#!/usr/bin/env python3
"""
SkippyGames — сборщик данных о играх.

Скрипт делает следующее:
1. Получает список популярных игр Steam (топ продаж, cc=ua) и объединяет
   его со списком кастомных appid из backend/custom_ids.txt.
2. Для каждой игры запрашивает подробности через Steam Store API
   (appdetails, cc=ua, l=russian): название, обложку, описание, жанры,
   платформы, цену в UAH, ссылку на трейлер YouTube (если есть).
3. Дополняет жанры детальными тегами сообщества через SteamSpy API и
   сопоставляет их с русским списком жанров сайта.
4. Получает текущий курс UAH -> RUB через open.er-api.com.
5. Конвертирует цену UAH -> RUB и прибавляет фиксированную наценку +500 RUB.
6. Сохраняет итоговый массив в games.json в корне репозитория.

Запуск: python backend/parser.py
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("skippygames.parser")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CUSTOM_IDS_FILE = Path(__file__).resolve().parent / "custom_ids.txt"
OUTPUT_FILE = REPO_ROOT / "games.json"

STEAM_FEATURED_URL = "https://store.steampowered.com/api/featuredcategories/"
STEAM_TOPSELLERS_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAMSPY_APPDETAILS_URL = "https://steamspy.com/api.php"
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/UAH"

REGION_CC = "ua"
REGION_LANG = "russian"

MARKUP_RUB = 500
MAX_TOP_GAMES = 1000
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 1.0  # пауза между запросами appdetails, чтобы не словить rate-limit
MAX_RETRIES = 3

# Сопоставление тегов SteamSpy/Steam с русским списком жанров сайта.
# Ключ — тег в нижнем регистре, как он приходит от SteamSpy, значение —
# соответствующая русская категория, используемая в фильтрах сайта.
TAG_MAP = {
    "action": "Экшен",
    "fps": "Шутеры от первого лица (FPS)",
    "first-person": "Шутеры от первого лица (FPS)",
    "shooter": "Шутеры от первого лица (FPS)",
    "third person shooter": "Шутеры от третьего лица (TPS)",
    "third-person shooter": "Шутеры от третьего лица (TPS)",
    "tactical": "Тактические шутеры",
    "hero shooter": "Геройские шутеры",
    "fighting": "Файтинги",
    "hack and slash": "Слэшеры",
    "beat 'em up": "Beat 'em up",
    "beat em up": "Beat 'em up",
    "platformer": "Платформеры",
    "battle royale": "Королевская битва (Battle Royale)",
    "crpg": "Классические ролевые игры (CRPG)",
    "action rpg": "Экшен-РПГ (Action-RPG)",
    "jrpg": "Японские ролевые игры (JRPG)",
    "mmorpg": "MMORPG",
    "rts": "Стратегии в реальном времени (RTS)",
    "turn-based strategy": "Пошаговые стратегии (TBS)",
    "turn based strategy": "Пошаговые стратегии (TBS)",
    "4x": "Глобальные стратегии (4X)",
    "moba": "MOBA",
    "tower defense": "Башенная защита (Tower Defense)",
    "auto battler": "Автобатлеры",
    "automobile": "Гоночные симуляторы (Simracing)",
    "adventure": "Приключения",
    "point & click": "Квесты (Point-and-Click)",
    "point-and-click": "Квесты (Point-and-Click)",
    "interactive fiction": "Интерактивное кино",
    "visual novel": "Визуальные новеллы",
    "puzzle": "Головоломки",
    "city builder": "Градостроительные симуляторы",
    "economy": "Экономические симуляторы",
    "life sim": "Симуляторы жизни",
    "simulation": "Технические симуляторы",
    "immersive sim": "Иммерсивные симуляторы (Immersive Sim)",
    "sports": "Спортивные симуляторы",
    "racing": "Гоночные симуляторы (Simracing)",
    "arcade": "Аркадные гонки",
    "survival": "Выживание (Survival)",
    "survival horror": "Хорроры на выживание (Survival Horror)",
    "psychological horror": "Психологические хорроры",
    "horror": "Психологические хорроры",
    "action-adventure": "Экшен-адвенчуры",
    "open world": "Песочницы (Sandbox)",
    "sandbox": "Песочницы (Sandbox)",
    "roguelike": "Рогалики (Roguelike/Roguelite)",
    "roguelite": "Рогалики (Roguelike/Roguelite)",
    "roguevania": "Метроидвании",
    "metroidvania": "Метроидвании",
    "stealth": "Стелс-экшен",
    "rhythm": "Ритм-игры",
    "casual": "Казуальные игры",
}

STEAM_GENRE_FALLBACK = {
    "Action": "Экшен",
    "Adventure": "Приключения",
    "RPG": "Классические ролевые игры (CRPG)",
    "Strategy": "Стратегии в реальном времени (RTS)",
    "Simulation": "Технические симуляторы",
    "Sports": "Спортивные симуляторы",
    "Racing": "Гоночные симуляторы (Simracing)",
    "Casual": "Казуальные игры",
    "Indie": "Приключения",
    "Massively Multiplayer": "MMORPG",
    "Free to Play": "Экшен",
}

session = requests.Session()
session.headers.update({"User-Agent": "SkippyGamesBot/1.0 (+https://github.com)"})


def http_get(url, params=None, retries=MAX_RETRIES):
    """GET-запрос с повторными попытками при сетевых ошибках."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            log.warning("HTTP %s от %s (попытка %s/%s)", resp.status_code, url, attempt, retries)
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("Ошибка сети %s (попытка %s/%s): %s", url, attempt, retries, exc)
        time.sleep(2 * attempt)
    if last_exc:
        log.error("Не удалось получить %s: %s", url, last_exc)
    return None


# ---------------------------------------------------------------------------
# Сбор списка appid
# ---------------------------------------------------------------------------

def load_custom_ids():
    ids = []
    if CUSTOM_IDS_FILE.exists():
        for line in CUSTOM_IDS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digits = "".join(ch for ch in line.split()[0] if ch.isdigit())
            if digits:
                ids.append(int(digits))
    else:
        log.warning("Файл %s не найден, кастомный список пуст", CUSTOM_IDS_FILE)
    log.info("Загружено %s кастомных appid", len(ids))
    return ids


def load_top_appids(limit=MAX_TOP_GAMES):
    """Собирает популярные appid через featuredcategories + storesearch."""
    appids = []
    resp = http_get(STEAM_FEATURED_URL, params={"cc": REGION_CC, "l": REGION_LANG})
    if resp is not None:
        try:
            data = resp.json()
            for section_key in ("top_sellers", "specials", "new_releases"):
                section = data.get(section_key, {})
                for item in section.get("items", []):
                    aid = item.get("id")
                    if aid:
                        appids.append(int(aid))
        except (ValueError, KeyError) as exc:
            log.warning("Не удалось разобрать featuredcategories: %s", exc)

    # Дополняем через постраничный поиск магазина, пока не наберём лимит
    page = 0
    while len(appids) < limit:
        params = {
            "term": "",
            "l": REGION_LANG,
            "cc": REGION_CC,
            "start": page * 100,
            "count": 100,
        }
        resp = http_get(STEAM_TOPSELLERS_SEARCH_URL, params=params)
        if resp is None:
            break
        try:
            data = resp.json()
            items = data.get("items", [])
        except ValueError:
            break
        if not items:
            break
        for item in items:
            aid = item.get("id")
            if aid:
                appids.append(int(aid))
        page += 1
        if page > (limit // 100 + 2):
            break
        time.sleep(0.5)

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique = []
    for aid in appids:
        if aid not in seen:
            seen.add(aid)
            unique.append(aid)
    return unique[:limit]


# ---------------------------------------------------------------------------
# Обогащение данными
# ---------------------------------------------------------------------------

def fetch_steamspy_tags(appid):
    resp = http_get(STEAMSPY_APPDETAILS_URL, params={"request": "appdetails", "appid": appid})
    if resp is None:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    tags_obj = data.get("tags")
    if not isinstance(tags_obj, dict):
        return []
    # SteamSpy отдаёт теги вида {"Tag Name": 1234, ...}, сортируем по весу
    sorted_tags = sorted(tags_obj.items(), key=lambda kv: kv[1], reverse=True)
    return [t[0].lower() for t in sorted_tags]


def map_genres(steamspy_tags, steam_genres):
    mapped = []
    for tag in steamspy_tags:
        genre_ru = TAG_MAP.get(tag)
        if genre_ru and genre_ru not in mapped:
            mapped.append(genre_ru)
        if len(mapped) >= 6:
            break
    if not mapped:
        for g in steam_genres:
            genre_ru = STEAM_GENRE_FALLBACK.get(g)
            if genre_ru and genre_ru not in mapped:
                mapped.append(genre_ru)
    if not mapped:
        mapped.append("Экшен")
    return mapped


def extract_platforms(platforms_obj):
    result = []
    if not platforms_obj:
        return ["PC"]
    if platforms_obj.get("windows") or platforms_obj.get("mac") or platforms_obj.get("linux"):
        result.append("PC")
    return result or ["PC"]


def extract_trailer(movies):
    if not movies:
        return None
    first = movies[0]
    webm = first.get("webm", {})
    mp4 = first.get("mp4", {})
    # На сторе трейлеры хранятся не как YouTube-ссылки, а как video-файлы Steam CDN.
    # Возвращаем прямую ссылку на видео Steam, пригодную для встраивания через <video>,
    # а также формируем резервную ссылку на поиск трейлера на YouTube.
    return {
        "steam_video": mp4.get("max") or mp4.get("480") or webm.get("max"),
        "youtube_search": None,
    }


def fetch_appdetails(appid):
    resp = http_get(
        STEAM_APPDETAILS_URL,
        params={"appids": appid, "cc": REGION_CC, "l": REGION_LANG, "filters": ""},
    )
    if resp is None:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None

    entry = data.get(str(appid))
    if not entry or not entry.get("success"):
        return None
    d = entry.get("data", {})
    if d.get("type") != "game":
        return None

    price_overview = d.get("price_overview")
    if price_overview and not d.get("is_free"):
        price_uah = price_overview.get("final", 0) / 100.0
    elif d.get("is_free"):
        price_uah = 0.0
    else:
        # Игра без цены (не продаётся в регионе) — пропускаем
        return None

    steam_genres = [g.get("description") for g in d.get("genres", []) if g.get("description")]
    movies = d.get("movies", [])
    trailer = extract_trailer(movies)

    header_image = d.get("header_image", "")
    # На основе header_image формируем youtube-поиск как запасной вариант трейлера
    youtube_search_url = (
        "https://www.youtube.com/results?search_query="
        + "+".join((d.get("name", "").split())) + "+trailer"
    )
    if trailer is not None:
        trailer["youtube_search"] = youtube_search_url
    else:
        trailer = {"steam_video": None, "youtube_search": youtube_search_url}

    return {
        "id": appid,
        "title": d.get("name", "Без названия"),
        "cover": header_image,
        "description": (d.get("short_description") or "").strip(),
        "steam_genres": steam_genres,
        "platforms_raw": d.get("platforms", {}),
        "price_uah": round(price_uah, 2),
        "is_free": bool(d.get("is_free")),
        "trailer": trailer,
        "screenshots": [s.get("path_thumbnail") for s in d.get("screenshots", [])[:5]],
    }


def fetch_exchange_rate():
    resp = http_get(EXCHANGE_RATE_URL)
    if resp is None:
        log.error("Не удалось получить курс валют, используем резервное значение 2.35")
        return 2.35
    try:
        data = resp.json()
        rate = data.get("rates", {}).get("RUB")
        if rate:
            log.info("Курс UAH -> RUB: %s", rate)
            return float(rate)
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Ошибка разбора курса валют: %s", exc)
    log.error("Резервный курс UAH -> RUB: 2.35")
    return 2.35


# ---------------------------------------------------------------------------
# Основной пайплайн
# ---------------------------------------------------------------------------

def build_game_record(appid, uah_to_rub):
    details = fetch_appdetails(appid)
    if details is None:
        return None

    tags = fetch_steamspy_tags(appid)
    genres_ru = map_genres(tags, details["steam_genres"])
    platforms = extract_platforms(details["platforms_raw"])

    # Дополняем платформы: если появляется в кастомном списке PlayStation/Xbox
    # каталог собирается отдельно на фронтенде (curated catalog), здесь всегда PC.
    if details["is_free"]:
        price_rub = 0
    else:
        price_rub = round(details["price_uah"] * uah_to_rub) + MARKUP_RUB

    record = {
        "id": details["id"],
        "title": details["title"],
        "cover": details["cover"],
        "description": details["description"],
        "genres": genres_ru,
        "platforms": platforms,
        "price_rub": price_rub,
        "is_free": details["is_free"],
        "trailer_video": details["trailer"].get("steam_video"),
        "trailer_youtube_search": details["trailer"].get("youtube_search"),
        "screenshots": details["screenshots"],
        "source": "steam",
    }
    return record


def main():
    log.info("=== SkippyGames parser: старт ===")

    custom_ids = load_custom_ids()
    top_ids = load_top_appids(MAX_TOP_GAMES)
    log.info("Получено %s топовых appid из Steam", len(top_ids))

    all_ids = []
    seen = set()
    for aid in custom_ids + top_ids:
        if aid not in seen:
            seen.add(aid)
            all_ids.append(aid)

    log.info("Итого уникальных appid к обработке: %s", len(all_ids))

    uah_to_rub = fetch_exchange_rate()

    games = []
    total = len(all_ids)
    for idx, appid in enumerate(all_ids, start=1):
        try:
            record = build_game_record(appid, uah_to_rub)
            if record:
                games.append(record)
                log.info("[%s/%s] OK: %s (%s ₽)", idx, total, record["title"], record["price_rub"])
            else:
                log.info("[%s/%s] Пропущено appid=%s (нет данных/не продаётся)", idx, total, appid)
        except Exception as exc:  # noqa: BLE001 — не прерываем весь прогон из-за одной игры
            log.error("[%s/%s] Ошибка обработки appid=%s: %s", idx, total, appid, exc)
        time.sleep(REQUEST_DELAY)

    if not games:
        log.error("Список игр пуст — прерываем запись, чтобы не затирать games.json пустым файлом")
        sys.exit(1)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uah_to_rub_rate": uah_to_rub,
        "markup_rub": MARKUP_RUB,
        "count": len(games),
        "games": games,
    }

    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Сохранено %s игр в %s", len(games), OUTPUT_FILE)
    log.info("=== SkippyGames parser: завершено ===")


if __name__ == "__main__":
    main()
