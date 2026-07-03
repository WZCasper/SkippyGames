'use strict';

/* =========================================================================
   КОНФИГУРАЦИЯ
   ========================================================================= */

// Числовой ID группы ВКонтакте (не alias!) для виджета "Сообщения сообщества".
// Узнать свой ID: Управление сообществом -> Работа с API -> ID сообщества,
// либо через https://vk.com/dev/community_messages (там же берётся и код).
// Alias группы для обычных ссылок (кнопки в шапке/футере) — vk.com/skippygames.
var VK_GROUP_ALIAS = 'skippygames';
var VK_GROUP_NUMERIC_ID = 195484236; // <-- замените на реальный числовой ID сообщества (например 123456789)

var GAMES_JSON_URL = 'games.json';

// Полный список жанров, используемый для фильтрации на главной странице.
var GENRE_LIST = [
  'Экшен', 'Шутеры от первого лица (FPS)', 'Шутеры от третьего лица (TPS)',
  'Тактические шутеры', 'Геройские шутеры', 'Файтинги', 'Слэшеры',
  "Beat 'em up", 'Платформеры', 'Королевская битва (Battle Royale)',
  'Классические ролевые игры (CRPG)', 'Экшен-РПГ (Action-RPG)',
  'Японские ролевые игры (JRPG)', 'MMORPG', 'Стратегии в реальном времени (RTS)',
  'Пошаговые стратегии (TBS)', 'Глобальные стратегии (4X)', 'MOBA',
  'Башенная защита (Tower Defense)', 'Автобатлеры', 'Приключения',
  'Квесты (Point-and-Click)', 'Интерактивное кино', 'Визуальные новеллы',
  'Головоломки', 'Градостроительные симуляторы', 'Экономические симуляторы',
  'Симуляторы жизни', 'Технические симуляторы', 'Иммерсивные симуляторы (Immersive Sim)',
  'Спортивные симуляторы', 'Гоночные симуляторы (Simracing)', 'Аркадные гонки',
  'Выживание (Survival)', 'Хорроры на выживание (Survival Horror)',
  'Психологические хорроры', 'Экшен-адвенчуры', 'Песочницы (Sandbox)',
  'Рогалики (Roguelike/Roguelite)', 'Метроидвании', 'Стелс-экшен',
  'Ритм-игры', 'Казуальные игры'
];

// 10 аватаров "дежурного менеджера" на каждый день недели по кругу.
// Это рабочие ссылки-заглушки (генерируются сервисом placehold.co),
// замените на реальные изображения игровых персонажей в любой момент.
var MANAGER_AVATARS = [
  { name: 'Смотритель Ключей', url: 'https://placehold.co/100x100/141416/ffd200?text=01' },
  { name: 'Капитан Байт', url: 'https://placehold.co/100x100/141416/ffd200?text=02' },
  { name: 'Страж Портала', url: 'https://placehold.co/100x100/141416/ffd200?text=03' },
  { name: 'Рейдер Пиксель', url: 'https://placehold.co/100x100/141416/ffd200?text=04' },
  { name: 'Механик Врат', url: 'https://placehold.co/100x100/141416/ffd200?text=05' },
  { name: 'Охотник Скидок', url: 'https://placehold.co/100x100/141416/ffd200?text=06' },
  { name: 'Хранитель Сейва', url: 'https://placehold.co/100x100/141416/ffd200?text=07' },
  { name: 'Наёмник Скиппи', url: 'https://placehold.co/100x100/141416/ffd200?text=08' },
  { name: 'Тень Сервера', url: 'https://placehold.co/100x100/141416/ffd200?text=09' },
  { name: 'Голос Саппорта', url: 'https://placehold.co/100x100/141416/ffd200?text=10' }
];

var PLATFORM_LABELS = { PC: 'Steam (PC)', PlayStation: 'PlayStation', Xbox: 'Xbox' };

/* =========================================================================
   СОСТОЯНИЕ
   ========================================================================= */

var STATE = {
  allGames: [],
  filtered: [],
  search: '',
  platforms: ['PC'],
  genres: []
};

/* =========================================================================
   ЗАГРУЗКА ДАННЫХ
   ========================================================================= */

function loadGamesData() {
  return fetch(GAMES_JSON_URL, { cache: 'no-store' })
    .then(function (resp) {
      if (!resp.ok) {
        throw new Error('HTTP ' + resp.status);
      }
      return resp.json();
    })
    .then(function (payload) {
      STATE.allGames = Array.isArray(payload.games) ? payload.games : [];
      STATE.filtered = STATE.allGames.slice();
    })
    .catch(function (err) {
      console.error('Не удалось загрузить games.json:', err);
      var grid = document.getElementById('games-grid');
      if (grid) {
        grid.innerHTML = '<div class="empty-state"><h3>Каталог временно недоступен</h3><p>Попробуйте обновить страницу позже.</p></div>';
      }
      STATE.allGames = [];
      STATE.filtered = [];
    });
}

/* =========================================================================
   ГЛАВНАЯ СТРАНИЦА: ФИЛЬТРЫ И РЕНДЕР СЕТКИ
   ========================================================================= */

function renderGenreCheckboxes() {
  var wrap = document.getElementById('genre-checkboxes');
  if (!wrap) return;
  wrap.innerHTML = GENRE_LIST.map(function (genre) {
    return '<label class="check-item"><input type="checkbox" value="' + escapeHtml(genre) + '"><span>' + escapeHtml(genre) + '</span></label>';
  }).join('');
}

function initSearchAndFilters() {
  var searchInput = document.getElementById('search-input');
  var filtersToggle = document.getElementById('filters-toggle');
  var filtersPanel = document.getElementById('filters-panel');
  var filtersReset = document.getElementById('filters-reset');
  var platformBoxes = document.querySelectorAll('#platform-checkboxes input[type="checkbox"]');
  var genreBoxes = document.querySelectorAll('#genre-checkboxes input[type="checkbox"]');

  searchInput.addEventListener('input', function (e) {
    STATE.search = e.target.value.trim().toLowerCase();
    applyFiltersAndRender();
  });

  filtersToggle.addEventListener('click', function () {
    filtersPanel.classList.toggle('open');
  });

  platformBoxes.forEach(function (box) {
    box.addEventListener('change', function () {
      STATE.platforms = Array.prototype.filter.call(platformBoxes, function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      applyFiltersAndRender();
    });
  });

  genreBoxes.forEach(function (box) {
    box.addEventListener('change', function () {
      STATE.genres = Array.prototype.filter.call(genreBoxes, function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      applyFiltersAndRender();
    });
  });

  filtersReset.addEventListener('click', function () {
    STATE.search = '';
    STATE.genres = [];
    STATE.platforms = ['PC'];
    searchInput.value = '';
    genreBoxes.forEach(function (b) { b.checked = false; });
    platformBoxes.forEach(function (b) { b.checked = (b.value === 'PC'); });
    applyFiltersAndRender();
  });
}

function applyFiltersAndRender() {
  var search = STATE.search;
  var platforms = STATE.platforms;
  var genres = STATE.genres;

  STATE.filtered = STATE.allGames.filter(function (game) {
    if (search && game.title.toLowerCase().indexOf(search) === -1) {
      return false;
    }
    if (platforms.length > 0) {
      var hasPlatform = (game.platforms || []).some(function (p) { return platforms.indexOf(p) !== -1; });
      if (!hasPlatform) return false;
    }
    if (genres.length > 0) {
      var hasGenre = (game.genres || []).some(function (g) { return genres.indexOf(g) !== -1; });
      if (!hasGenre) return false;
    }
    return true;
  });

  updateFiltersBadge();
  renderGamesGrid();
}

function updateFiltersBadge() {
  var badge = document.getElementById('filters-count');
  if (!badge) return;
  var count = STATE.genres.length + (STATE.platforms.length !== 1 || STATE.platforms[0] !== 'PC' ? STATE.platforms.length : 0);
  badge.textContent = String(count);
}

function renderGamesGrid() {
  var grid = document.getElementById('games-grid');
  var resultsCount = document.getElementById('results-count');
  if (!grid) return;

  if (resultsCount) {
    resultsCount.textContent = STATE.filtered.length + ' игр найдено';
  }

  if (STATE.filtered.length === 0) {
    grid.innerHTML = '<div class="empty-state"><h3>Ничего не найдено</h3><p>Попробуйте изменить параметры поиска или фильтры.</p></div>';
    return;
  }

  grid.innerHTML = '';
  var fragment = document.createDocumentFragment();
  STATE.filtered.forEach(function (game) {
    fragment.appendChild(createGameCard(game));
  });
  grid.appendChild(fragment);
}

function platformIconSvg(platform) {
  if (platform === 'PC') {
    return '<svg viewBox="0 0 24 24"><path d="M2 4h20v13H2V4Zm0 15h20v2H2v-2Z"/></svg>';
  }
  if (platform === 'PlayStation') {
    return '<svg viewBox="0 0 24 24"><path d="M8 3v16.5l3.5 1.2V7.3c0-.6.3-1 .8-.8.7.2 1 .8 1 1.6v6.3c1.9.9 3.4.1 3.4-2.1 0-2.3-.8-3.3-3.2-4.2L8 5.6V3Zm10.5 14.6-6 2.1v-2.2l4.3-1.5c.5-.2.6-.5 0-.7l-4.3-1.5v-2.2l6.4 2.3c1.8.7 1.6 2.9-.4 3.7Z"/></svg>';
  }
  return '<svg viewBox="0 0 24 24"><path d="M12 2 2 12l10 10 10-10L12 2Zm0 3.4L18.6 12 12 18.6 5.4 12 12 5.4Z"/></svg>';
}

function createGameCard(game) {
  var card = document.createElement('div');
  card.className = 'game-card';

  var priceLabel = game.is_free ? 'Бесплатно' : formatRub(game.price_rub);
  var priceClass = game.is_free ? 'game-card__price free' : 'game-card__price';

  card.innerHTML =
    '<div class="game-card__media">' +
      '<img src="' + escapeHtml(game.cover) + '" alt="' + escapeHtml(game.title) + '" loading="lazy">' +
      '<div class="game-card__badges">' +
        (game.is_free ? '<span class="badge badge-free">Free</span>' : '') +
      '</div>' +
    '</div>' +
    '<div class="game-card__body">' +
      '<div class="game-card__title">' + escapeHtml(game.title) + '</div>' +
      '<div class="game-card__genres">' + escapeHtml((game.genres || []).slice(0, 3).join(' • ')) + '</div>' +
      '<div class="game-card__footer">' +
        '<span class="' + priceClass + '">' + priceLabel + '</span>' +
        '<span class="platform-icons">' + (game.platforms || []).map(platformIconSvg).join('') + '</span>' +
      '</div>' +
    '</div>';

  attachTiltEffect(card);

  card.addEventListener('click', function () {
    window.location.href = 'game.html?id=' + encodeURIComponent(game.id);
  });

  return card;
}

/* =========================================================================
   3D-НАКЛОН КАРТОЧЕК (ПАРАЛЛАКС)
   ========================================================================= */

function attachTiltEffect(card) {
  var maxTilt = 10;

  function handleMove(e) {
    var rect = card.getBoundingClientRect();
    var x = e.clientX - rect.left;
    var y = e.clientY - rect.top;
    var px = x / rect.width - 0.5;
    var py = y / rect.height - 0.5;
    var rotateY = px * maxTilt * 2;
    var rotateX = -py * maxTilt * 2;
    card.style.transform = 'perspective(900px) rotateX(' + rotateX.toFixed(2) + 'deg) rotateY(' + rotateY.toFixed(2) + 'deg) scale3d(1.02, 1.02, 1.02)';
  }

  function handleLeave() {
    card.style.transform = 'perspective(900px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
  }

  card.addEventListener('mousemove', handleMove);
  card.addEventListener('mouseleave', handleLeave);
}

/* =========================================================================
   СТРАНИЦА ИГРЫ
   ========================================================================= */

function getGameIdFromUrl() {
  var params = new URLSearchParams(window.location.search);
  var raw = params.get('id');
  return raw ? isNaN(Number(raw)) ? raw : Number(raw) : null;
}

function renderGameDetail() {
  var container = document.getElementById('game-content');
  var breadcrumbTitle = document.getElementById('breadcrumb-title');
  var gameId = getGameIdFromUrl();

  var game = STATE.allGames.find(function (g) { return String(g.id) === String(gameId); });

  if (!game) {
    container.innerHTML = '<div class="empty-state"><h3>Игра не найдена</h3><p>Возможно, ссылка устарела. <a href="index.html">Вернуться в каталог</a></p></div>';
    if (breadcrumbTitle) breadcrumbTitle.textContent = 'Игра не найдена';
    return;
  }

  document.title = game.title + ' — SkippyGames';
  document.getElementById('page-title').textContent = game.title + ' — SkippyGames';
  if (breadcrumbTitle) breadcrumbTitle.textContent = game.title;

  var trailerHtml = '';
  if (game.trailer_video) {
    trailerHtml = '<div class="detail-trailer"><video controls preload="none" poster="' + escapeHtml(game.cover) + '"><source src="' + escapeHtml(game.trailer_video) + '" type="video/mp4"></video></div>';
  } else if (game.trailer_youtube_search) {
    var query = encodeURIComponent(game.title + ' trailer');
    trailerHtml = '<div class="detail-trailer"><iframe src="https://www.youtube.com/embed?listType=search&list=' + query + '" allowfullscreen loading="lazy"></iframe></div>';
  }

  var screenshotsHtml = '';
  if (game.screenshots && game.screenshots.length > 0) {
    screenshotsHtml = '<div class="detail-screens">' + game.screenshots.map(function (src) {
      return '<img src="' + escapeHtml(src) + '" alt="' + escapeHtml(game.title) + ' screenshot" loading="lazy">';
    }).join('') + '</div>';
  }

  var platformsHtml = (game.platforms || ['PC']).map(function (p, idx) {
    var label = PLATFORM_LABELS[p] || p;
    return '<button class="platform-option' + (idx === 0 ? ' active' : '') + '" data-platform="' + escapeHtml(p) + '">' + escapeHtml(label) + '</button>';
  }).join('');

  var priceLabel = game.is_free ? 'Бесплатно' : formatRub(game.price_rub);
  var priceClass = game.is_free ? 'price free' : 'price';

  container.innerHTML =
    '<div class="detail-hero"><img src="' + escapeHtml(game.cover) + '" alt="' + escapeHtml(game.title) + '"></div>' +
    '<div class="detail-layout">' +
      '<div class="detail-main">' +
        '<h1>' + escapeHtml(game.title) + '</h1>' +
        '<div class="detail-tags">' + (game.genres || []).map(function (g) { return '<span class="tag-pill">' + escapeHtml(g) + '</span>'; }).join('') + '</div>' +
        '<p class="detail-description">' + escapeHtml(game.description || 'Описание появится позже.') + '</p>' +
        trailerHtml +
        screenshotsHtml +
      '</div>' +
      '<div class="purchase-card">' +
        '<div class="' + priceClass + '" id="detail-price">' + priceLabel + '</div>' +
        '<div class="price-note">Цена указана с учётом всех комиссий</div>' +
        '<div class="platform-select">' +
          '<h4>Выберите платформу</h4>' +
          '<div class="platform-options" id="platform-options">' + platformsHtml + '</div>' +
        '</div>' +
        '<button class="btn btn-primary buy-btn" id="buy-btn">Купить</button>' +
        '<p class="purchase-note">После нажатия текст заказа скопируется в буфер обмена — просто вставьте его (Ctrl+V) в открывшемся чате ВКонтакте.</p>' +
      '</div>' +
    '</div>';

  var selectedPlatform = (game.platforms && game.platforms[0]) || 'PC';
  var optionButtons = container.querySelectorAll('.platform-option');
  optionButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      optionButtons.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      selectedPlatform = btn.getAttribute('data-platform');
    });
  });

  document.getElementById('buy-btn').addEventListener('click', function () {
    handleBuyClick(game, selectedPlatform);
  });
}

function handleBuyClick(game, platform) {
  var platformLabel = PLATFORM_LABELS[platform] || platform;
  var orderText = 'Здравствуйте! Хочу купить игру ' + game.title + ' на платформу ' + platformLabel;

  copyToClipboard(orderText).then(function () {
    openVkWidget();
    showToast('Название игры скопировано!', 'Нажмите Ctrl+V (или «Вставить») в чате, чтобы отправить заказ администратору.');
  }).catch(function () {
    openVkWidget();
    showToast('Не удалось скопировать автоматически', 'Скопируйте вручную: «' + orderText + '»');
  });
}

function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise(function (resolve, reject) {
    try {
      var textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      ok ? resolve() : reject(new Error('execCommand failed'));
    } catch (err) {
      reject(err);
    }
  });
}

/* =========================================================================
   TOAST-УВЕДОМЛЕНИЯ
   ========================================================================= */

function showToast(title, text) {
  var container = document.getElementById('toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = '<strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(text) + '</p>';
  container.appendChild(toast);
  requestAnimationFrame(function () {
    toast.classList.add('show');
  });
  setTimeout(function () {
    toast.classList.remove('show');
    setTimeout(function () { toast.remove(); }, 400);
  }, 6000);
}

/* =========================================================================
   ВИДЖЕТ ЧАТА ВКОНТАКТЕ
   ========================================================================= */

function getManagerOfTheDay() {
  var dayIndex = new Date().getDay(); // 0 (вс) .. 6 (сб)
  return MANAGER_AVATARS[dayIndex % MANAGER_AVATARS.length];
}

function initVkWidget() {
  var manager = getManagerOfTheDay();

  var toggleAvatar = document.getElementById('vk-toggle-avatar');
  var headerAvatar = document.getElementById('vk-manager-avatar');
  var headerName = document.getElementById('vk-manager-name');

  if (toggleAvatar) toggleAvatar.src = manager.url;
  if (headerAvatar) headerAvatar.src = manager.url;
  if (headerName) headerName.textContent = manager.name;

  var toggleBtn = document.getElementById('vk-chat-toggle');
  var panel = document.getElementById('vk-widget-panel');
  var closeBtn = document.getElementById('vk-widget-close');
  var widgetLoaded = false;

  function loadVkWidgetScript(callback) {
    if (window.VK && window.VK.Widgets) {
      callback();
      return;
    }
    var script = document.createElement('script');
    script.src = 'https://vk.com/js/api/openapi.js?169';
    script.async = true;
    script.onload = callback;
    document.head.appendChild(script);
  }

  function mountVkWidget() {
    if (widgetLoaded) return;
    widgetLoaded = true;
    loadVkWidgetScript(function () {
      if (window.VK && window.VK.Widgets && window.VK.Widgets.CommunityMessages) {
        window.VK.Widgets.CommunityMessages('vk_community_messages', VK_GROUP_NUMERIC_ID, {
          expandTimeout: 500,
          tooltipButtonText: 'Написать нам'
        });
      }
    });
  }

  function openPanel() {
    panel.classList.add('open');
    mountVkWidget();
  }

  function closePanel() {
    panel.classList.remove('open');
  }

  toggleBtn.addEventListener('click', function () {
    if (panel.classList.contains('open')) {
      closePanel();
    } else {
      openPanel();
    }
  });

  closeBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    closePanel();
  });

  window.openVkWidget = openPanel;
}

function openVkWidget() {
  // Переопределяется внутри initVkWidget после инициализации.
  var panel = document.getElementById('vk-widget-panel');
  if (panel) panel.classList.add('open');
}

/* =========================================================================
   УТИЛИТЫ
   ========================================================================= */

function formatRub(amount) {
  return new Intl.NumberFormat('ru-RU').format(amount) + ' ₽';
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
