#!/usr/bin/env python3
"""
SkippyGames — сборщик данных о играх (v3).

Новое в версии 3:
- Каталог хранится не в одном games.json, а как набор файлов:
  data/index.json (лёгкий индекс для каталога/поиска/фильтров) и
  data/games/{id}.json (полные данные одной игры — описание, скриншоты,
  трейлер, DLC). Фронтенд подгружает полные данные игры лениво, только
  когда пользователь открывает её карточку.
- Если у игры нет трейлера в Steam, парсер один раз ищет подходящее видео
  через официальный YouTube Data API v3 (нужен ключ в переменной окружения
  YOUTUBE_API_KEY) и сохраняет его videoId в trailer_youtube_id.

Особенности версии 2, по сравнению с первой:
- Каталог растёт ИНКРЕМЕНТАЛЬНО: каждый прогон не пересобирает всё заново,
  а (1) обновляет цены у "устаревших" карточек (у которых давно не было
  refresh) и (2) добавляет новые игры из полного списка приложений Steam,
  пока не исчерпан лимит времени/запросов на один прогон. Так каталог может
  вырасти до 10 000+ игр за несколько дней/недель без блокировки по
  rate-limit и без превышения таймаута GitHub Actions (6 часов на job).
- Полные (нетронутые) описания игр (detailed_description), а не короткие.
- Изображения высокого разрешения: капсула 616x353 и hero-баннер 1920x620
  вместо низкого header_image (460x215); скриншоты берутся в разрешении
  path_full, а не path_thumbnail.
- DLC / дополнения / внутриигровая валюта — отдельным списком с ценами.
- ID приложений, которые оказались НЕ играми (DLC, саундтреки, софт),
  запоминаются в backend/skipped_ids.json, чтобы не тратить на них
  запросы повторно на следующих прогонах.

Запуск: python backend/parser.py
"""

import json
import os
import re
import sys
import time
import html
import logging
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("skippygames.parser")

# ---------------------------------------------------------------------------
# Константы / конфигурация
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
CUSTOM_IDS_FILE = BACKEND_DIR / "custom_ids.txt"
SKIPPED_IDS_FILE = BACKEND_DIR / "skipped_ids.json"

# Каталог хранится НЕ одним огромным games.json, а как "мини-база данных"
# на файловой системе: один JSON-файл на игру (data/games/{id}.json,
# полные данные — описание, скриншоты, трейлер, DLC) плюс один лёгкий
# сводный индекс (data/index.json — только id/название/обложка/цена/жанры/
# платформы), который фронтенд загружает целиком для каталога и поиска, а
# полные данные конкретной игры подгружает только при открытии её карточки.
# Это и есть "ленивая загрузка" на статическом хостинге (GitHub Pages) —
# там нет настоящей базы данных и серверных запросов, поэтому масштабируемая
# структура строится на файлах.
DATA_DIR = REPO_ROOT / "data"
GAMES_DIR = DATA_DIR / "games"
INDEX_FILE = DATA_DIR / "index.json"

STEAM_APPLIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
STEAM_FEATURED_URL = "https://store.steampowered.com/api/featuredcategories/"
STEAM_TOPSELLERS_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_CDN_BASE = "https://cdn.cloudflare.steamstatic.com/steam/apps"
STEAMSPY_APPDETAILS_URL = "https://steamspy.com/api.php"
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/UAH"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Ключ YouTube Data API v3 (бесплатный, лимит 10 000 "units"/день, поиск
# стоит 100 units => максимум 100 запросов поиска в день на этот ключ).
# Берётся из переменной окружения/секрета GitHub Actions, чтобы не хранить
# его в коде. Если ключ не задан — фолбэк на YouTube просто не работает,
# и на сайте вместо видео покажется честная ссылка "Искать на YouTube".
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

REGION_CC = "ua"
REGION_LANG = "russian"

MARKUP_RUB = 500
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.6
MAX_RETRIES = 3

# Целевой размер каталога и бюджеты одного прогона. Подобраны так, чтобы
# один запуск гарантированно укладывался в лимит GitHub Actions (6 часов)
# и не долбил Steam API слишком агрессивно (у него есть неофициальный
# rate-limit — примерно 200 запросов appdetails за 5 минут на IP).
TARGET_CATALOG_SIZE = 10000
MAX_RUNTIME_SECONDS = 55 * 60          # жёсткий потолок одного прогона — 55 минут
REFRESH_STALE_AFTER_DAYS = 3           # обновлять цену, если старше N дней
MAX_REFRESH_PER_RUN = 1200             # сколько существующих карточек обновить за прогон
MAX_NEW_GAMES_PER_RUN = 600            # сколько новых игр добавить за прогон

RUN_STARTED_AT = time.monotonic()

# Сопоставление тегов SteamSpy/Steam с русским списком жанров сайта.
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
session.headers.update({"User-Agent": "SkippyGamesBot/2.0 (+https://github.com)"})


def time_budget_left():
    return MAX_RUNTIME_SECONDS - (time.monotonic() - RUN_STARTED_AT)


def http_get(url, params=None, retries=MAX_RETRIES):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                log.warning("429 Too Many Requests, пауза 30с")
                time.sleep(30)
                continue
            log.warning("HTTP %s от %s (попытка %s/%s)", resp.status_code, url, attempt, retries)
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("Ошибка сети %s (попытка %s/%s): %s", url, attempt, retries, exc)
        time.sleep(2 * attempt)
    if last_exc:
        log.error("Не удалось получить %s: %s", url, last_exc)
    return None


def http_head_ok(url):
    try:
        resp = session.head(url, timeout=8)
        return resp.status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------------------
# Персистентное состояние: уже собранный каталог и список "не игр"
# ---------------------------------------------------------------------------

def load_existing_catalog():
    """Читает уже собранный каталог из data/games/*.json (по одному файлу
    на игру). При первом запуске (или миграции со старой версии, где всё
    хранилось в одном games.json в корне репозитория) каталог будет пуст —
    это нормально, парсер соберёт его заново инкрементально."""
    catalog = {}
    if not GAMES_DIR.exists():
        legacy_file = REPO_ROOT / "games.json"
        if legacy_file.exists():
            log.info("Обнаружен старый games.json — мигрируем данные в data/games/*.json")
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
                for rec in legacy_data.get("games", []):
                    catalog[rec["id"]] = rec
            except (ValueError, KeyError) as exc:
                log.warning("Не удалось прочитать старый games.json: %s", exc)
        return catalog

    for path in GAMES_DIR.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            catalog[rec["id"]] = rec
        except (ValueError, KeyError, OSError) as exc:
            log.warning("Не удалось прочитать %s: %s", path, exc)

    log.info("Загружен существующий каталог: %s игр (data/games/*.json)", len(catalog))
    return catalog


def load_skipped_ids():
    if SKIPPED_IDS_FILE.exists():
        try:
            return set(json.loads(SKIPPED_IDS_FILE.read_text(encoding="utf-8")))
        except ValueError:
            return set()
    return set()


def save_skipped_ids(skipped):
    SKIPPED_IDS_FILE.write_text(
        json.dumps(sorted(skipped), ensure_ascii=False),
        encoding="utf-8",
    )


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
    return ids


def load_full_applist():
    """Полный список appid+name всех приложений Steam (без деталей)."""
    resp = http_get(STEAM_APPLIST_URL)
    if resp is None:
        return []
    try:
        data = resp.json()
        apps = data.get("applist", {}).get("apps", [])
        return [(a["appid"], a.get("name", "")) for a in apps if a.get("name")]
    except (ValueError, KeyError) as exc:
        log.warning("Не удалось разобрать GetAppList: %s", exc)
        return []


def load_top_appids(limit=1000):
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

    page = 0
    while len(appids) < limit and time_budget_left() > 60:
        params = {"term": "", "l": REGION_LANG, "cc": REGION_CC, "start": page * 100, "count": 100}
        resp = http_get(STEAM_TOPSELLERS_SEARCH_URL, params=params)
        if resp is None:
            break
        try:
            items = resp.json().get("items", [])
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
        time.sleep(0.4)

    seen = set()
    unique = []
    for aid in appids:
        if aid not in seen:
            seen.add(aid)
            unique.append(aid)
    return unique[:limit]


# ---------------------------------------------------------------------------
# Обогащение данными об одной игре
# ---------------------------------------------------------------------------

STRIP_TAGS_RE = re.compile(r"<[^>]+>")
COLLAPSE_WS_RE = re.compile(r"[ \t]+")
COLLAPSE_NL_RE = re.compile(r"\n{3,}")


def clean_full_description(raw_html):
    """Полная (не обрезанная) очистка detailed_description от HTML-разметки."""
    if not raw_html:
        return ""
    text = raw_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n\n").replace("</li>", "\n")
    text = text.replace("<li>", "• ")
    text = STRIP_TAGS_RE.sub("", text)
    text = html.unescape(text)
    text = COLLAPSE_WS_RE.sub(" ", text)
    text = COLLAPSE_NL_RE.sub("\n\n", text)
    return text.strip()


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
    if not platforms_obj:
        return ["PC"]
    if platforms_obj.get("windows") or platforms_obj.get("mac") or platforms_obj.get("linux"):
        return ["PC"]
    return ["PC"]


def build_hires_images(appid, api_header_image, api_background):
    """Собирает изображения высокого разрешения из Steam CDN, с фолбэками."""
    capsule = f"{STEAM_CDN_BASE}/{appid}/capsule_616x353.jpg"
    hero = f"{STEAM_CDN_BASE}/{appid}/library_hero.jpg"

    cover = capsule if http_head_ok(capsule) else (api_header_image or capsule)
    hero_final = hero if http_head_ok(hero) else (api_background or api_header_image or cover)
    return cover, hero_final


def fetch_dlc_upsells(dlc_ids, uah_to_rub):
    """Для каждого DLC (в т.ч. паков внутриигровой валюты) достаём имя и цену."""
    upsells = []
    for dlc_id in dlc_ids[:12]:  # ограничиваем, чтобы не раздувать время прогона
        resp = http_get(STEAM_APPDETAILS_URL, params={"appids": dlc_id, "cc": REGION_CC, "l": REGION_LANG})
        if resp is None:
            continue
        try:
            entry = resp.json().get(str(dlc_id))
        except ValueError:
            continue
        if not entry or not entry.get("success"):
            continue
        d = entry.get("data", {})
        price_overview = d.get("price_overview")
        if not price_overview:
            continue
        price_uah = price_overview.get("final", 0) / 100.0
        price_rub = round(price_uah * uah_to_rub) + MARKUP_RUB
        upsells.append({
            "id": dlc_id,
            "name": d.get("name", "Дополнение"),
            "price_rub": price_rub,
            "cover": d.get("header_image", ""),
        })
        time.sleep(0.3)
    return upsells


def fetch_appdetails(appid):
    resp = http_get(
        STEAM_APPDETAILS_URL,
        params={"appids": appid, "cc": REGION_CC, "l": REGION_LANG, "filters": ""},
    )
    if resp is None:
        return None, "network_error"
    try:
        data = resp.json()
    except ValueError:
        return None, "bad_json"

    entry = data.get(str(appid))
    if not entry or not entry.get("success"):
        return None, "not_found"
    d = entry.get("data", {})
    if d.get("type") != "game":
        return None, "not_a_game"

    price_overview = d.get("price_overview")
    if price_overview and not d.get("is_free"):
        price_uah = price_overview.get("final", 0) / 100.0
    elif d.get("is_free"):
        price_uah = 0.0
    else:
        return None, "not_sold_in_region"

    return {
        "id": appid,
        "title": d.get("name", "Без названия"),
        "header_image": d.get("header_image", ""),
        "background": d.get("background_raw") or d.get("background", ""),
        "description_short": (d.get("short_description") or "").strip(),
        "description_full": clean_full_description(d.get("detailed_description", "")),
        "steam_genres": [g.get("description") for g in d.get("genres", []) if g.get("description")],
        "platforms_raw": d.get("platforms", {}),
        "price_uah": round(price_uah, 2),
        "is_free": bool(d.get("is_free")),
        "movies": d.get("movies", []),
        "screenshots": [s.get("path_full") for s in d.get("screenshots", []) if s.get("path_full")][:8],
        "dlc_ids": d.get("dlc", []) or [],
    }, "ok"


def extract_trailer(movies):
    if not movies:
        return None
    best = None
    best_size = -1
    for movie in movies:
        mp4 = movie.get("mp4", {})
        candidate = mp4.get("max") or mp4.get("480")
        if candidate:
            size_hint = 1 if mp4.get("max") else 0
            if size_hint > best_size:
                best = candidate
                best_size = size_hint
    return best


def fetch_youtube_trailer_id(title):
    """Ищет трейлер игры на YouTube через официальный YouTube Data API v3.

    Вызывается ТОЛЬКО когда у игры нет собственного трейлера в Steam —
    это сделано на бэкенде (а не в браузере пользователя), потому что
    поисковый запрос YouTube Data API стоит 100 "units" из дневного лимита
    в 10 000, то есть с одного ключа доступно всего ~100 поисков в сутки.
    Если бы поиск шёл с фронтенда, лимит исчерпал бы первый десяток
    посетителей сайта. Найденный videoId сохраняется в games.json и
    переиспользуется при каждом обновлении карточки, пока Steam не
    предоставит собственный трейлер.
    """
    if not YOUTUBE_API_KEY:
        return None

    params = {
        "part": "snippet",
        "q": f"{title} official trailer",
        "type": "video",
        "videoEmbeddable": "true",
        "maxResults": 1,
        "safeSearch": "moderate",
        "key": YOUTUBE_API_KEY,
    }
    resp = http_get(YOUTUBE_SEARCH_URL, params=params, retries=1)
    if resp is None:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None

    if "error" in data:
        log.warning("YouTube API вернул ошибку: %s", data["error"].get("message", "unknown"))
        return None

    items = data.get("items", [])
    if not items:
        return None
    video_id = items[0].get("id", {}).get("videoId")
    return video_id


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


def build_game_record(appid, uah_to_rub):
    details, status = fetch_appdetails(appid)
    if details is None:
        return None, status

    tags = fetch_steamspy_tags(appid)
    genres_ru = map_genres(tags, details["steam_genres"])
    platforms = extract_platforms(details["platforms_raw"])
    cover, hero = build_hires_images(appid, details["header_image"], details["background"])
    trailer_video = extract_trailer(details["movies"])

    trailer_youtube_id = None
    if not trailer_video and time_budget_left() > 60:
        trailer_youtube_id = fetch_youtube_trailer_id(details["title"])

    if details["is_free"]:
        price_rub = 0
    else:
        price_rub = round(details["price_uah"] * uah_to_rub) + MARKUP_RUB

    upsells = []
    if details["dlc_ids"] and time_budget_left() > 120:
        upsells = fetch_dlc_upsells(details["dlc_ids"], uah_to_rub)

    record = {
        "id": details["id"],
        "title": details["title"],
        "cover": cover,
        "hero": hero,
        "description": details["description_full"] or details["description_short"],
        "description_short": details["description_short"],
        "genres": genres_ru,
        "platforms": platforms,
        "price_rub": price_rub,
        "is_free": details["is_free"],
        "trailer_video": trailer_video,
        "trailer_youtube_id": trailer_youtube_id,
        "screenshots": details["screenshots"],
        "upsells": upsells,
        "source": "steam",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return record, "ok"


# ---------------------------------------------------------------------------
# Основной пайплайн
# ---------------------------------------------------------------------------

def main():
    log.info("=== SkippyGames parser v2: старт ===")

    catalog = load_existing_catalog()          # {id: record}
    skipped_ids = load_skipped_ids()            # set(id) — точно не игры
    uah_to_rub = fetch_exchange_rate()

    processed = 0
    added = 0
    refreshed = 0

    # --- Этап 1: обновляем цену/данные у самых "старых" карточек -----------
    now = time.time()
    stale_threshold = now - REFRESH_STALE_AFTER_DAYS * 86400

    def parse_ts(record):
        try:
            return time.mktime(time.strptime(record.get("updated_at", ""), "%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, TypeError):
            return 0

    stale_ids = sorted(
        [gid for gid, rec in catalog.items() if parse_ts(rec) < stale_threshold],
        key=lambda gid: parse_ts(catalog[gid]),
    )[:MAX_REFRESH_PER_RUN]

    log.info("К обновлению (устаревшие): %s из %s карточек в каталоге", len(stale_ids), len(catalog))

    for appid in stale_ids:
        if time_budget_left() < 60:
            log.warning("Бюджет времени исчерпан на этапе обновления, переходим к сохранению")
            break
        record, status = build_game_record(appid, uah_to_rub)
        processed += 1
        if record:
            catalog[appid] = record
            refreshed += 1
            log.info("[refresh %s] OK: %s (%s ₽)", refreshed, record["title"], record["price_rub"])
        elif status in ("not_a_game", "not_sold_in_region"):
            log.info("[refresh] appid=%s более недоступен (%s), удаляем из каталога", appid, status)
            catalog.pop(appid, None)
            skipped_ids.add(appid)
        time.sleep(REQUEST_DELAY)

    # --- Этап 2: добавляем новые игры --------------------------------------
    custom_ids = load_custom_ids()
    candidate_ids = []
    for aid in custom_ids:
        if aid not in catalog and aid not in skipped_ids:
            candidate_ids.append(aid)

    if len(catalog) < TARGET_CATALOG_SIZE and time_budget_left() > 120:
        top_ids = load_top_appids(2000)
        for aid in top_ids:
            if aid not in catalog and aid not in skipped_ids and aid not in candidate_ids:
                candidate_ids.append(aid)

    if len(catalog) + len(candidate_ids) < TARGET_CATALOG_SIZE and time_budget_left() > 120:
        log.info("Догружаем полный список приложений Steam для расширения каталога...")
        full_list = load_full_applist()
        log.info("В полном списке Steam: %s приложений", len(full_list))
        for aid, _name in full_list:
            if aid not in catalog and aid not in skipped_ids and aid not in candidate_ids:
                candidate_ids.append(aid)
            if len(candidate_ids) >= MAX_NEW_GAMES_PER_RUN * 3:
                break  # достаточно кандидатов с запасом на отсев не-игр

    log.info("Кандидатов на добавление: %s", len(candidate_ids))

    for appid in candidate_ids:
        if added >= MAX_NEW_GAMES_PER_RUN:
            log.info("Достигнут лимит новых игр за прогон (%s)", MAX_NEW_GAMES_PER_RUN)
            break
        if time_budget_left() < 60:
            log.warning("Бюджет времени исчерпан на этапе добавления новых игр")
            break

        record, status = build_game_record(appid, uah_to_rub)
        processed += 1
        if record:
            catalog[appid] = record
            added += 1
            log.info("[new %s/%s] OK: %s (%s ₽)", added, MAX_NEW_GAMES_PER_RUN, record["title"], record["price_rub"])
        else:
            skipped_ids.add(appid)
        time.sleep(REQUEST_DELAY)

    # --- Сохранение ----------------------------------------------------------
    if not catalog:
        log.error("Каталог пуст — прерываем запись, чтобы не затирать данные пустым каталогом")
        sys.exit(1)

    GAMES_DIR.mkdir(parents=True, exist_ok=True)

    # Полные данные — по одному файлу на игру. Файл перезаписывается, только
    # если содержимое реально изменилось (иначе git-диффы на 10 000 игр были
    # бы огромными и бессмысленными при каждом прогоне).
    written = 0
    for gid, record in catalog.items():
        game_path = GAMES_DIR / f"{gid}.json"
        new_content = json.dumps(record, ensure_ascii=False, indent=2)
        if game_path.exists() and game_path.read_text(encoding="utf-8") == new_content:
            continue
        game_path.write_text(new_content, encoding="utf-8")
        written += 1

    # Удаляем файлы игр, которые больше не в каталоге (были исключены как
    # "не игра" на этапе обновления).
    existing_ids = set(catalog.keys())
    removed = 0
    for path in GAMES_DIR.glob("*.json"):
        try:
            file_id = int(path.stem)
        except ValueError:
            continue
        if file_id not in existing_ids:
            path.unlink()
            removed += 1

    # Лёгкий сводный индекс для каталога/поиска/фильтров на фронтенде —
    # только те поля, которые реально нужны для списка и фильтрации.
    games_list = sorted(catalog.values(), key=lambda g: g["title"])
    index_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uah_to_rub_rate": uah_to_rub,
        "markup_rub": MARKUP_RUB,
        "target_catalog_size": TARGET_CATALOG_SIZE,
        "count": len(games_list),
        "games": [
            {
                "id": g["id"],
                "title": g["title"],
                "cover": g["cover"],
                "genres": g["genres"],
                "platforms": g["platforms"],
                "price_rub": g["price_rub"],
                "is_free": g["is_free"],
            }
            for g in games_list
        ],
    }
    INDEX_FILE.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    save_skipped_ids(skipped_ids)

    # Старый монолитный games.json в корне репозитория больше не используется
    # фронтендом — удаляем его, чтобы не вводить в заблуждение (если остался
    # от предыдущей версии сайта).
    legacy_file = REPO_ROOT / "games.json"
    if legacy_file.exists():
        legacy_file.unlink()
        log.info("Удалён устаревший games.json (заменён на data/index.json + data/games/*.json)")

    log.info("Записано/обновлено файлов игр: %s, удалено: %s", written, removed)

    log.info(
        "Итого: обработано=%s, обновлено=%s, добавлено новых=%s, всего в каталоге=%s (цель %s)",
        processed, refreshed, added, len(games_list), TARGET_CATALOG_SIZE,
    )
    log.info("=== SkippyGames parser v2: завершено ===")


if __name__ == "__main__":
    main()
