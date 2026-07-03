# SkippyGames

Статический магазин игр на GitHub Pages с автоматическим сбором данных из Steam.

## Структура

```
index.html                       — главная страница (каталог, поиск, фильтры)
game.html                        — карточка игры
style.css                        — стили (тёмная чёрно-жёлтая тема)
script.js                        — вся клиентская логика (Vanilla JS)
games.json                       — данные о играх (генерируются автоматически)
backend/parser.py                — сборщик данных Steam -> games.json
backend/custom_ids.txt           — список appid, добавляемых вручную
backend/requirements.txt         — зависимости Python
.github/workflows/update_games.yml — ежедневный автозапуск парсера
```

## Как это работает

1. `backend/parser.py` запускается по расписанию через GitHub Actions
   (`.github/workflows/update_games.yml`, ежедневно в 03:00 UTC, а также
   вручную через вкладку Actions -> Update games.json -> Run workflow).
2. Скрипт получает список популярных игр Steam, объединяет его с
   `backend/custom_ids.txt`, запрашивает подробности (Steam Store API +
   SteamSpy для тегов/жанров), конвертирует цену UAH -> RUB и добавляет
   наценку +500 ₽, затем сохраняет всё в `games.json` в корне репозитория.
3. Экшен коммитит обновлённый `games.json` обратно в репозиторий.
4. `index.html` / `game.html` загружают `games.json` через `fetch()` и
   рендерят каталог и карточки игр на чистом JS — бэкенд-сервер не нужен.

## Настройка перед запуском

### 1. Числовой ID группы ВКонтакте

В `script.js` в самом верху файла задайте:

```js
var VK_GROUP_NUMERIC_ID = 0; // замените на реальный числовой ID сообщества
```

Числовой ID (не alias `skippygames`) можно узнать в настройках сообщества
ВКонтакте, раздел «Работа с API», либо через любой сервис resolve-screen-name.
Виджет «Сообщения сообщества» должен быть включён в настройках сообщества
(Управление → Сообщения → Виджет для сайта).

### 2. Кастомный список игр

Добавляйте appid игр (в том числе тех, которых нет в топе продаж) построчно
в `backend/custom_ids.txt`. appid — это число в URL страницы игры в Steam:
`store.steampowered.com/app/730/...` → `730`.

### 3. Аватарки дежурного менеджера

В `script.js` массив `MANAGER_AVATARS` содержит 10 рабочих ссылок-заглушек
(генерируются сервисом placehold.co) — по одной на каждый день недели.
Замените поле `url` на реальные изображения ваших персонажей, когда будут
готовы.

## Деплой на GitHub Pages

1. Создайте репозиторий и загрузите в него все файлы проекта.
2. В настройках репозитория: Settings → Pages → Source → выберите ветку
   `main` и папку `/ (root)`.
3. В настройках репозитория: Settings → Actions → General → Workflow
   permissions → выберите «Read and write permissions» (это нужно, чтобы
   Action мог коммитить обновлённый `games.json`).
4. Запустите workflow вручную один раз: вкладка Actions → Update games.json
   → Run workflow, чтобы сразу получить свежий каталог вместо тестовых
   данных из `games.json`.
5. Откройте `https://<ваш-логин>.github.io/<репозиторий>/`.

## Локальный запуск парсера

```bash
cd backend
pip install -r requirements.txt
python parser.py
```

Файл `games.json` в корне репозитория будет перезаписан.
