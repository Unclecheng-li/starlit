/* ============================================================
   vol 自建聊天客户端
   - 同一个页面既是页面也是 OneBot 11 客户端（正向 WS）
   - 只做私聊：登录者=我，唯一好友=星野
   ============================================================ */
(() => {
  'use strict';

  // ---------------------------------------------------------- 基础
  const $ = (sel) => document.querySelector(sel);
  const LS_THEME = 'vol.theme';
  const LS_TOKEN = 'vol.token';

  const els = {
    connectView: $('#connectView'),
    connectState: $('#connectState'),
    connectStateText: $('#connectStateText'),
    connectBtn: $('#connectBtn'),
    tokenRow: $('#tokenRow'),
    tokenInput: $('#tokenInput'),
    tokenSave: $('#tokenSave'),
    connectTip: $('#connectTip'),

    appView: $('#appView'),
    railAvatar: $('#railAvatar'),
    railTheme: $('#railTheme'),
    railSticker: $('#railSticker'),
    railSettings: $('#railSettings'),
    mobileTheme: $('#mobileTheme'),
    mobileSettings: $('#mobileSettings'),

    meName: $('#meName'),
    connChip: $('#connChip'),
    connChipText: $('#connChip span'),
    searchInput: $('#searchInput'),
    convList: $('#convList'),
    verText: $('#verText'),

    chatPane: $('#chatPane'),
    backBtn: $('#backBtn'),
    chatName: $('#chatName'),
    chatSub: $('#chatSub'),
    onlineDot: $('#onlineDot'),
    btnChatStyle: $('#btnChatStyle'),
    btnSearchMsg: $('#btnSearchMsg'),
    btnMore: $('#btnMore'),
    chatSearch: $('#chatSearch'),
    chatSearchInput: $('#chatSearchInput'),
    searchCount: $('#searchCount'),
    searchClose: $('#searchClose'),

    msgScroll: $('#msgScroll'),
    msgList: $('#msgList'),
    emptyState: $('#emptyState'),
    emptyAvatar: $('#emptyAvatar'),
    toBottom: $('#toBottom'),
    toBottomBadge: $('#toBottomBadge'),
    multiBar: $('#multiBar'),
    multiCount: $('#multiCount'),
    marqueeBox: $('#marqueeBox'),
    forwardMask: $('#forwardMask'),
    forwardTitle: $('#forwardTitle'),
    forwardList: $('#forwardList'),
    forwardClose: $('#forwardClose'),

    composer: $('#composer'),
    input: $('#input'),
    sendBtn: $('#sendBtn'),
    mobileMoreBtn: $('#mobileMoreBtn'),
    emojiBtn: $('#emojiBtn'),
    stickerBtn: $('#stickerBtn'),
    imageBtn: $('#imageBtn'),
    fileInput: $('#fileInput'),

    emojiPanel: $('#emojiPanel'),
    emojiTabs: $('#emojiTabs'),
    emojiGrid: $('#emojiGrid'),
    stickerPanel: $('#stickerPanel'),
    stickerTabs: $('#stickerTabs'),
    stickerGrid: $('#stickerGrid'),
    stickerSearch: $('#stickerSearch'),
    stickerEmpty: $('#stickerEmpty'),
    stickerManageBtn: $('#stickerManageBtn'),
    stickerManageBar: $('#stickerManageBar'),
    stickerAddBtn: $('#stickerAddBtn'),
    stickerCategoryAdd: $('#stickerCategoryAdd'),
    stickerCategoryDel: $('#stickerCategoryDel'),
    stickerUploadInput: $('#stickerUploadInput'),
    categoryMask: $('#categoryMask'),
    categoryClose: $('#categoryClose'),
    categoryCancel: $('#categoryCancel'),
    categoryName: $('#categoryName'),
    categoryCreate: $('#categoryCreate'),

    mobileAvatar: $('#mobileAvatar'),
    mobileName: $('#mobileName'),
    mobileStatus: $('#mobileStatus'),
    mobilePlus: $('#mobilePlus'),
    mobileNav: $('#mobileNav'),
    navBadge: $('#navBadge'),
    contactsPage: $('#contactsPage'),
    contactsBack: $('#contactsBack'),
    contactsAdd: $('#contactsAdd'),
    contactList: $('#contactList'),
    mobileActions: $('#mobileActions'),

    ctxMenu: $('#ctxMenu'),
    moreMenu: $('#moreMenu'),
    lightbox: $('#lightbox'),
    lightboxImg: $('#lightboxImg'),
    toast: $('#toast'),
    dropMask: $('#dropMask'),

    settingsMask: $('#settingsMask'),
    settingsClose: $('#settingsClose'),
    themeSeg: $('#themeSeg'),
    settingsChatStyle: $('#settingsChatStyle'),
    settingsToken: $('#settingsToken'),
    settingsTokenSave: $('#settingsTokenSave'),
    settingsApiKey: $('#settingsApiKey'),
    settingsBaseUrl: $('#settingsBaseUrl'),
    settingsModel: $('#settingsModel'),
    settingsApiState: $('#settingsApiState'),
    settingsLlmSave: $('#settingsLlmSave'),
    settingsAddCharacter: $('#settingsAddCharacter'),

    characterMask: $('#characterMask'),
    characterClose: $('#characterClose'),
    characterPreview: $('#characterPreview'),
    characterPickAvatar: $('#characterPickAvatar'),
    characterAvatarInput: $('#characterAvatarInput'),
    characterName: $('#characterName'),
    characterStatus: $('#characterStatus'),
    characterCancel: $('#characterCancel'),
    characterCreate: $('#characterCreate'),
    settingsUrl: $('#settingsUrl'),
    settingsReconnect: $('#settingsReconnect'),
    settingsStapxs: $('#settingsStapxs'),

    chatSettingsMask: $('#chatSettingsMask'),
    chatSettingsClose: $('#chatSettingsClose'),
    csAvatar: $('#csAvatar'),
    csTitle: $('#csTitle'),
    csSideSeg: $('#csSideSeg'),
    csStyles: $('#csStyles'),
    csCustom: $('#csCustom'),
    csColors: $('#csColors'),
    csBg1: $('#csBg1'),
    csBg2: $('#csBg2'),
    csFg: $('#csFg'),
    csResetColor: $('#csResetColor'),
    csTags: $('#csTags'),
    csTagInput: $('#csTagInput'),
    csDecos: $('#csDecos'),
    csDecoInput: $('#csDecoInput'),
    csStickerGroups: $('#csStickerGroups'),
    csPreviewIn: $('#csPreviewIn'),
    csPreviewOut: $('#csPreviewOut'),
    csPreviewInAvatar: $('#csPreviewInAvatar'),
    csPreviewOutAvatar: $('#csPreviewOutAvatar'),
    csAvatarPreview: $('#csAvatarPreview'),
    csAvatarPick: $('#csAvatarPick'),
    csAvatarReset: $('#csAvatarReset'),
    csEnthusiasm: $('#csEnthusiasm'),
    csEnthusiasmVal: $('#csEnthusiasmVal'),
    csAffection: $('#csAffection'),
    csAffectionVal: $('#csAffectionVal'),
    csTraitPreview: $('#csTraitPreview'),
    csTraitSave: $('#csTraitSave'),

    avatarMask: $('#avatarMask'),
    avatarClose: $('#avatarClose'),
    avatarStage: $('#avatarStage'),
    avatarCropImg: $('#avatarCropImg'),
    avatarZoom: $('#avatarZoom'),
    avatarRepick: $('#avatarRepick'),
    avatarCancel: $('#avatarCancel'),
    avatarConfirm: $('#avatarConfirm'),
    avatarFileInput: $('#avatarFileInput'),
  };

  const state = {
    ws: null,
    connected: false,
    everConnected: false,
    connecting: false,
    token: localStorage.getItem(LS_TOKEN) ||
           new URLSearchParams(location.search).get('access_token') || '',
    me: { id: 0, name: '我' },
    bot: { id: 0, name: '星野' },
    characters: [],
    charMsgs: {},
    convMeta: {},
    loaded: {},
    msgs: [],
    byMid: new Map(),
    keySeq: 0,
    ready: false,
    liveBuffer: [],
    lastTs: 0,
    unread: 0,
    atBottom: true,
    reconnectTimer: 0,
    reconnectDelay: 1000,
    lastFrame: 0,
    pending: new Map(),
    echoSeq: 0,
    emojiCat: 0,
    stickers: null,
    stickerGroupKey: null,
    stickerQuery: '',
    stickerManage: false,
    stickerSets: {},
    stickerSetsLoaded: false,
    avatars: {},
    avatarCrop: null,
    pendingCharacterAvatar: '',
    chatThemes: {},
    chatSide: 'in',
    mobileTab: 'messages',
    ctxMsg: null,
    selectMode: false,
    selected: new Set(),
    marquee: null,
    suppressClickUntil: 0,
    forwardMode: '',
    lastRead: (() => {
      try { return JSON.parse(localStorage.getItem('vol.lastRead') || '{}'); }
      catch (e) { return {}; }
    })(),
    lastReadSent: {},
    searchHits: [],
    searchIdx: -1,
    dragDepth: 0,
  };

  const nowSec = () => Math.floor(Date.now() / 1000);

  const fmtClock = (ts) => {
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  };

  const fmtConvTime = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return fmtClock(ts);
    const y = new Date(now);
    y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return '昨天';
    const days = Math.floor((now - d) / 86400000);
    if (days < 7) return '周' + '日一二三四五六'[d.getDay()];
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  const fmtSep = (ts) => {
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return `今天 ${fmtClock(ts)}`;
    const y = new Date(now);
    y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return `昨天 ${fmtClock(ts)}`;
    if (d.getFullYear() === now.getFullYear()) {
      return `${d.getMonth() + 1}月${d.getDate()}日 ${fmtClock(ts)}`;
    }
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${fmtClock(ts)}`;
  };

  const firstChar = (name) => (String(name || '').trim().slice(0, 1) || '星');

  // QQ 头像（和 Stapxs 用的是同一个公开接口）；加载失败就保留文字头像
  const qqAvatarUrl = (uin, size = 160) =>
    uin ? `https://q1.qlogo.cn/g?b=qq&s=${size}&nk=${uin}` : '';

  // 用户在「聊天设置 → 更换头像」里裁剪上传的自定义头像
  function customAvatarUrl(uin) {
    const key = String(uin || '');
    return key ? (state.avatars[key] || '') : '';
  }

  function fillAvatar(el, name, uin, fallback) {
    if (!el) return;
    el.textContent = '';
    el.classList.remove('has-img');
    const span = document.createElement('span');
    span.textContent = fallback || firstChar(name);
    el.appendChild(span);
    if (!uin) return;

    const attach = (src, onFail) => {
      const img = document.createElement('img');
      img.alt = name || '';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('load', () => el.classList.add('has-img'));
      img.addEventListener('error', () => {
        img.remove();
        if (onFail) onFail();
      });
      img.src = src;
      el.appendChild(img);
    };

    const custom = customAvatarUrl(uin);
    if (custom) {
      // 自定义头像读不到时退回 QQ 头像，不留空白
      attach(resolveAsset(custom), () => {
        const qq = qqAvatarUrl(uin);
        if (qq) attach(qq);
      });
    } else {
      attach(qqAvatarUrl(uin));
    }
  }

  // 头像换好后，把当前会话里的「角色头像」重画；
  // 会话列表/联系人页由各自的 render 重新取头像，不能在这里一把全改。
  function refreshBotAvatars() {
    if (!state.bot.id) return;
    document.querySelectorAll('#msgList .msg-row.in .avatar.bot-avatar, #chatSettingsMask .bot-avatar')
      .forEach((el) => {
        fillAvatar(el, state.bot.name, state.bot.id);
      });
    fillAvatar(els.emptyAvatar, state.bot.name, state.bot.id);
    renderConvList();
    renderContactList();
  }

  async function loadAvatars() {
    try {
      const res = await apiFetch('/api/avatars', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      state.avatars = (data && typeof data.items === 'object') ? data.items : {};
      refreshBotAvatars();
      renderConvList();
      renderContactList();
      applyFavicon();
    } catch (e) { /* 老服务端没有这个接口时静默 */ }
  }

  function applyFavicon() {
    const link = document.getElementById('favicon');
    if (!link || !state.bot.id) return;
    const custom = customAvatarUrl(state.bot.id);
    if (custom) {
      link.href = resolveAsset(custom);
      return;
    }
    const icon = new Image();
    icon.referrerPolicy = 'no-referrer';
    icon.onload = () => { link.href = icon.src; };
    icon.src = qqAvatarUrl(state.bot.id, 100);
  }

  const toastTimer = { id: 0 };
  function toast(text) {
    els.toast.textContent = text;
    els.toast.classList.remove('hidden');
    requestAnimationFrame(() => els.toast.classList.add('show'));
    clearTimeout(toastTimer.id);
    toastTimer.id = setTimeout(() => {
      els.toast.classList.remove('show');
      setTimeout(() => els.toast.classList.add('hidden'), 220);
    }, 2200);
  }

  function copyText(text) {
    const s = String(text || '');
    if (!s) return;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(s).then(() => toast('已复制'), () => fallbackCopy(s));
    } else {
      fallbackCopy(s);
    }
  }
  function fallbackCopy(s) {
    const ta = document.createElement('textarea');
    ta.value = s;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); toast('已复制'); }
    catch (e) { toast('复制失败'); }
    ta.remove();
  }

  // ---------------------------------------------------------- 主题
  function setTheme(theme, save = true) {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    if (save) localStorage.setItem(LS_THEME, theme);
    document.querySelectorAll('#themeSeg button').forEach((b) => {
      b.classList.toggle('active', b.dataset.theme === theme);
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === 'dark' ? '#0b0e14' : '#0099ff';
  }
  els.railTheme.addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  els.themeSeg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-theme]');
    if (b) setTheme(b.dataset.theme);
  });

  // ---------------------------------------------------------- 聊天气泡（按对话保存）
  const LS_CHAT_THEME = 'vol.chatTheme';
  const BUBBLE_STYLES = [
    { id: 'classic', name: '经典' },
    { id: 'tail', name: '尖角' },
    { id: 'glass', name: '玻璃' },
    { id: 'cream', name: '奶油' },
    { id: 'line', name: '线框' },
    { id: 'neon', name: '霓虹' },
    { id: 'lace', name: '花边' },
    { id: 'cloud', name: '云朵' },
  ];
  const DEFAULT_IN = {
    style: 'classic', custom: false,
    bg1: '#ffffff', bg2: '#f7fbff', fg: '#17202c',
    tag: '', deco: 'none',
  };
  const DEFAULT_OUT = {
    style: 'classic', custom: false,
    bg1: '#1aa8ff', bg2: '#0b82ff', fg: '#ffffff',
    tag: '', deco: 'none',
  };
  const TAG_PRESETS = ['', 'MUM', '♡', '(๑•̀ㅂ•́)و✧', '喵', '星野', '大叔'];
  const DECO_PRESETS = [
    { v: 'none', label: '无' },
    { v: '✦', label: '✦' },
    { v: '♡', label: '♡' },
    { v: '✧', label: '✧' },
    { v: '🎀', label: '🎀' },
    { v: '⭐', label: '⭐' },
    { v: '(๑>ᴗ<๑)', label: '(๑>ᴗ<๑)' },
  ];
  const COLOR_RE = /^#[0-9a-f]{6}$/i;

  function sanitizeSide(raw, base) {
    const out = { ...base };
    if (!raw || typeof raw !== 'object') return out;
    if (BUBBLE_STYLES.some((s) => s.id === raw.style)) out.style = raw.style;
    out.custom = !!raw.custom;
    for (const k of ['bg1', 'bg2', 'fg']) {
      if (typeof raw[k] === 'string' && COLOR_RE.test(raw[k])) out[k] = raw[k];
    }
    out.tag = typeof raw.tag === 'string' ? raw.tag.slice(0, 12) : '';
    out.deco = typeof raw.deco === 'string' ? raw.deco.slice(0, 16) : 'none';
    return out;
  }

  function loadChatThemes() {
    try {
      const raw = JSON.parse(localStorage.getItem(LS_CHAT_THEME) || '{}');
      const out = {};
      for (const [peer, v] of Object.entries(raw || {})) {
        if (!v || typeof v !== 'object') continue;
        out[peer] = {
          in: sanitizeSide(v.in, DEFAULT_IN),
          out: sanitizeSide(v.out, DEFAULT_OUT),
        };
      }
      return out;
    } catch (e) {
      return {};
    }
  }
  state.chatThemes = loadChatThemes();

  function ensureChatTheme(peerId) {
    const key = String(peerId || '0');
    if (!state.chatThemes[key]) {
      state.chatThemes[key] = { in: { ...DEFAULT_IN }, out: { ...DEFAULT_OUT } };
    }
    return state.chatThemes[key];
  }

  function chatThemeFor(peerId, side) {
    const t = ensureChatTheme(peerId);
    return side === 'out' ? t.out : t.in;
  }

  function editTheme() {
    return chatThemeFor(state.bot.id, state.chatSide);
  }

  function saveChatThemes() {
    localStorage.setItem(LS_CHAT_THEME, JSON.stringify(state.chatThemes));
  }

  function setSideColorVars(side, t) {
    const root = document.documentElement;
    const cap = side === 'out' ? 'Out' : 'In';
    const pre = side === 'out' ? '--custom-out' : '--custom-in';
    root.dataset['custom' + cap] = t.custom ? '1' : '0';
    if (t.custom) {
      root.style.setProperty(pre + '-bg1', t.bg1);
      root.style.setProperty(pre + '-bg2', t.bg2);
      root.style.setProperty(pre + '-fg', t.fg);
    } else {
      for (const k of ['bg1', 'bg2', 'fg']) root.style.removeProperty(pre + '-' + k);
    }
  }

  function applyChatColors() {
    setSideColorVars('in', chatThemeFor(state.bot.id, 'in'));
    setSideColorVars('out', chatThemeFor(state.bot.id, 'out'));
  }

  function applyBubbleDecor(bubble, theme) {
    if (!bubble) return;
    bubble.querySelectorAll('.bubble-tag,.bubble-deco').forEach((n) => n.remove());
    if (bubble.classList.contains('sticker') || bubble.classList.contains('media')) return;
    if (theme.deco && theme.deco !== 'none') {
      const d = document.createElement('span');
      d.className = 'bubble-deco';
      d.textContent = theme.deco;
      bubble.appendChild(d);
    }
    if (theme.tag) {
      const t = document.createElement('span');
      t.className = 'bubble-tag';
      t.textContent = theme.tag;
      bubble.appendChild(t);
    }
  }

  function renderChatPreview() {
    const pairs = [[els.csPreviewIn, 'in'], [els.csPreviewOut, 'out']];
    for (const [row, side] of pairs) {
      if (!row) continue;
      const bubble = row.querySelector('.bubble');
      if (!bubble) continue;
      applyBubbleDecor(bubble, chatThemeFor(state.bot.id, side));
      row.classList.toggle('has-tag', !!bubble.querySelector('.bubble-tag'));
    }
  }

  function refreshBubbleDecorAll() {
    if (els.msgList) {
      els.msgList.querySelectorAll('.msg-row').forEach((row) => {
        if (row.closest('.cs-preview')) return;
        const bubble = row.querySelector('.bubble');
        if (!bubble) return;
        const dir = row.classList.contains('out') ? 'out' : 'in';
        applyBubbleDecor(bubble, chatThemeFor(state.bot.id, dir));
        row.classList.toggle('has-tag', !!bubble.querySelector('.bubble-tag'));
      });
    }
    renderChatPreview();
  }

  function applyChatTheme() {
    const ti = chatThemeFor(state.bot.id, 'in');
    const to = chatThemeFor(state.bot.id, 'out');
    document.documentElement.dataset.bubbleIn = ti.style;
    document.documentElement.dataset.bubbleOut = to.style;
    applyChatColors();
    refreshBubbleDecorAll();
  }

  // ---------------------------------------------------------- 连接
  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const base = `${proto}//${location.host}/onebot/v11/ws`;
    return state.token ? `${base}?access_token=${encodeURIComponent(state.token)}` : base;
  }

  function setConn(kind, text) {
    els.connChip.className = 'conn-chip' + (kind ? ' ' + kind : '');
    els.connChipText.textContent = text;
    els.onlineDot.className = 'online-dot' + (kind === 'ok' ? ' ok' : '');
    els.chatSub.textContent = kind === 'ok' ? '在线 · 本地直连' : text;
    els.input.placeholder = kind === 'ok'
      ? `和${state.bot.name}说点什么…`
      : '连接断开，正在重连…';
    if (els.mobileStatus) {
      els.mobileStatus.textContent = kind === 'ok' ? '在线' : text;
      const line = els.mobileStatus.closest('.mh-status');
      if (line) line.classList.toggle('ok', kind === 'ok');
    }
  }

  function showConnect(text, tokenVisible) {
    els.connectView.classList.remove('hidden');
    els.appView.classList.add('hidden');
    els.connectState.classList.toggle('bad', !!text);
    els.connectStateText.textContent = text || '正在连接…';
    if (tokenVisible) {
      els.tokenRow.classList.remove('hidden');
      els.tokenInput.value = state.token;
      setTimeout(() => els.tokenInput.focus(), 60);
    }
  }

  function hideConnect() {
    els.connectView.classList.add('hidden');
    els.appView.classList.remove('hidden');
  }

  function rejectAllPending(reason) {
    for (const [, p] of state.pending) {
      clearTimeout(p.timer);
      p.reject(new Error(reason));
    }
    state.pending.clear();
  }

  function call(action, params = {}, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const ws = state.ws;
      if (!ws || ws.readyState !== 1) {
        reject(new Error('未连接'));
        return;
      }
      const echo = `e${++state.echoSeq}_${Date.now()}`;
      const timer = setTimeout(() => {
        state.pending.delete(echo);
        reject(new Error('请求超时'));
      }, timeout);
      state.pending.set(echo, { resolve, reject, timer });
      ws.send(JSON.stringify({ action, params, echo }));
    });
  }

  function connect() {
    if (state.ws && (state.ws.readyState === 0 || state.ws.readyState === 1)) return;
    clearTimeout(state.reconnectTimer);
    if (location.protocol === 'file:') {
      showConnect('请先启动 vol，再用 http://127.0.0.1:8080/ 打开本页面');
      els.connectTip.textContent = '直接双击 HTML 文件无法连接，必须通过 vol 提供的地址访问。';
      return;
    }
    state.connecting = true;
    setConn('warn', '连接中…');
    if (!els.connectView.classList.contains('hidden')) {
      els.connectState.classList.remove('bad');
      els.connectStateText.textContent = '正在连接…';
    }

    let ws;
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      scheduleReconnect();
      return;
    }
    state.ws = ws;

    ws.onopen = async () => {
      state.lastFrame = Date.now();
      try {
        const info = await call('get_version_info', {});
        const rawVer = String(info?.data?.app_version || '');
        const mVer = rawVer.match(/\d+\.\d+(?:\.\d+)?/);
        els.verText.textContent = mVer ? 'v' + mVer[0] : 'v1.0';
      } catch (e) { /* 非关键 */ }

      try {
        const login = await call('get_login_info', {});
        state.me = {
          id: Number(login?.data?.user_id || 0),
          name: login?.data?.nickname || '我',
        };

        let buddies = [];
        try {
          const fr = await call('get_friends_with_category', {});
          for (const cat of (fr?.data || [])) {
            buddies.push(...(cat?.buddyList || []));
          }
        } catch (e) { /* 回退 */ }
        if (!buddies.length) {
          const fl = await call('get_friend_list', {});
          buddies = (fl?.data || []);
        }
        state.characters = buddies
          .map((b) => ({ id: Number(b.user_id || 0), name: b.nickname || '角色' }))
          .filter((c) => c.id);
        if (state.characters.length) {
          const saved = Number(localStorage.getItem('vol.currentPeer') || 0);
          state.bot = state.characters.find((c) => c.id === saved) ||
            state.characters[0];
        }
        // 会话列表的「最近一条」预览（服务端顺带返回，非标准字段）
        try {
          const rec = await call('get_recent_contact', {}, 8000);
          for (const it of (rec?.data || [])) {
            const key = String(it.peerUin || '');
            if (!key) continue;
            const meta = convMetaFor(key);
            if (it.lastMsg) meta.preview = String(it.lastMsg);
            if (it.msgTime) meta.ts = Number(it.msgTime) || 0;
            const rt = Number(it.readTime || 0);
            if (rt > Number(state.lastRead[key] || 0)) state.lastRead[key] = rt;
          }
          saveLastRead();
        } catch (e) { /* 老服务端没有 lastMsg 就留空 */ }

        applyIdentity();
        if (state.token) els.settingsToken.value = state.token;

        // 多端同步：连接时把每个会话都补齐，而不是只补当前打开的这一个。
        await syncAllConversations();
        state.ready = true;
        const buffered = state.liveBuffer.splice(0);
        for (const ev of buffered) onEvent(ev, true);

        state.connected = true;
        state.everConnected = true;
        state.connecting = false;
        hideConnect();
        setConn('ok', '已连接');
        els.settingsUrl.textContent = location.host;
        state.reconnectDelay = 1000;
        scrollToBottom(false);
      } catch (e) {
        setConn('bad', '握手失败');
        scheduleReconnect();
      }
    };

    ws.onmessage = (e) => {
      state.lastFrame = Date.now();
      let data;
      try { data = JSON.parse(e.data); } catch (err) { return; }

      if (data && data.echo && state.pending.has(data.echo)) {
        const p = state.pending.get(data.echo);
        state.pending.delete(data.echo);
        clearTimeout(p.timer);
        if (data.status === 'failed') p.reject(new Error(data.wording || '请求失败'));
        else p.resolve(data);
        return;
      }
      onEvent(data);
    };

    ws.onerror = () => { /* onclose 里统一处理 */ };

    ws.onclose = (e) => {
      state.ws = null;
      state.connected = false;
      state.connecting = false;
      state.ready = false;
      rejectAllPending('连接已断开');
      if (e && e.code === 1008) {
        // 服务端启用了 access_token，但本地没有/不对
        if (!state.everConnected) {
          showConnect('访问令牌不正确，请填写后重试', true);
        } else if (els.appView.classList.contains('hidden')) {
          showConnect('访问令牌不正确，请填写后重试', true);
        } else {
          openSettings();
          els.settingsToken.focus();
          toast('访问令牌不正确，请重新填写');
        }
        setConn('bad', '需要访问令牌');
        return;
      }
      setConn('bad', '连接已断开');
      if (els.appView.classList.contains('hidden')) {
        els.connectState.classList.add('bad');
        els.connectStateText.textContent = '连接不上 vol，正在重试…';
      }
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    clearTimeout(state.reconnectTimer);
    const delay = Math.min(10000, state.reconnectDelay);
    state.reconnectDelay = Math.min(10000, Math.round(state.reconnectDelay * 1.7));
    state.reconnectTimer = setTimeout(connect, delay);
  }

  function applyIdentity() {
    els.meName.textContent = state.me.name;
    els.chatName.textContent = state.bot.name;
    fillAvatar(els.railAvatar, state.me.name, state.me.id, '我');
    fillAvatar(els.emptyAvatar, state.bot.name, state.bot.id);
    fillAvatar(els.mobileAvatar, state.me.name, state.me.id, '我');
    fillAvatar(els.csAvatar, state.bot.name, state.bot.id);
    fillAvatar(els.csPreviewInAvatar, state.bot.name, state.bot.id);
    fillAvatar(els.csPreviewOutAvatar, state.me.name, state.me.id, '我');
    els.mobileName.textContent = state.me.name;
    els.csTitle.textContent = state.bot.name;
    const emptyText = els.emptyState.querySelector('p');
    if (emptyText) emptyText.textContent = `和${state.bot.name}打个招呼吧`;
    els.input.placeholder = `和${state.bot.name}说点什么…`;
    document.title = `${state.bot.name} · vol`;
    applyFavicon();
    applyChatTheme();
    renderConvList();
    renderContactList();
    loadAvatars();
    loadStickerSets();
    if (state.token) {
      els.settingsToken.value = state.token;
      els.tokenInput.value = state.token;
    }
  }

  // ---------------------------------------------------------- 多会话
  function rebuildMidIndex() {
    state.byMid.clear();
    for (const m of state.msgs) if (m.mid) state.byMid.set(m.mid, m);
  }

  function convMetaFor(peerId) {
    const key = String(peerId);
    if (!state.convMeta[key]) state.convMeta[key] = { preview: '', ts: 0, unread: 0 };
    return state.convMeta[key];
  }

  function totalUnread() {
    return Object.values(state.convMeta).reduce((n, m) => n + (m.unread || 0), 0);
  }

  function updateDocTitle() {
    document.title = state.unread
      ? `(${state.unread}) ${state.bot.name} · vol`
      : `${state.bot.name} · vol`;
  }

  function saveLastRead() {
    try { localStorage.setItem('vol.lastRead', JSON.stringify(state.lastRead)); }
    catch (e) { /* 隐身模式写不了，忽略 */ }
  }

  function syncReadState(peerId, ts) {
    if (!state.ws || state.ws.readyState !== 1) return;
    const key = String(peerId);
    const now = nowSec();
    if (now - Number(state.lastReadSent[key] || 0) < 5) return;
    state.lastReadSent[key] = now;
    call('set_msg_read', {
      user_id: Number(peerId),
      time: Math.floor(ts || now),
    }, 8000).catch(() => { /* 老服务端没有这个 action 也不影响 */ });
  }

  function markRead(peerId, ts = 0) {
    const key = String(peerId);
    const prev = Number(state.lastRead[key] || 0);
    const next = Math.max(prev, Number(ts || nowSec()));
    if (next !== prev) {
      state.lastRead[key] = next;
      saveLastRead();
    }
    syncReadState(peerId, next);
  }

  function recomputeUnread(peerId) {
    const key = String(peerId);
    const list = Number(peerId) === Number(state.bot.id)
      ? state.msgs : (state.charMsgs[key] || []);
    let lastRead = Number(state.lastRead[key] || 0);
    if (!lastRead && list.length) {
      // 新设备第一次同步：把当前进度当成已读，避免历史全部变成红点
      lastRead = Number(list[list.length - 1].ts || 0);
      state.lastRead[key] = lastRead;
      saveLastRead();
    }
    const n = list.filter((m) => m.dir === 'in' && !m.recalled &&
      Number(m.ts || 0) > lastRead).length;
    convMetaFor(key).unread = n;
    state.unread = totalUnread();
    updateBadges();
    updateDocTitle();
    renderConvList();
  }

  function renderConvList() {
    if (!els.convList) return;
    const q = (els.searchInput?.value || '').trim();
    els.convList.innerHTML = '';
    // QQ 式排序：最近说过话的排最上面；没有聊天记录的沉底。
    const items = [];
    let order = 0;
    for (const c of state.characters) {
      const meta = convMetaFor(c.id);
      const cache = c.id === state.bot.id ? state.msgs : (state.charMsgs[c.id] || []);
      const last = cache.length ? cache[cache.length - 1] : null;
      const preview = meta.preview || (last ? ((last.dir === 'out' ? '我：' : '') + previewOf(last)) : '还没有聊天，打个招呼吧');
      const ts = meta.ts || (last ? last.ts : 0);
      items.push({ c, meta, preview, ts, order: order++ });
    }
    items.sort((a, b) => (b.ts - a.ts) || (a.order - b.order));

    for (const item of items) {
      const { c, meta, preview, ts } = item;
      if (q && !(c.name.includes(q) || preview.includes(q))) continue;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'conv' + (c.id === state.bot.id ? ' active' : '');
      btn.dataset.peer = String(c.id);

      const av = document.createElement('div');
      av.className = 'avatar bot-avatar';
      fillAvatar(av, c.name, c.id);

      const main = document.createElement('div');
      main.className = 'conv-main';
      const top = document.createElement('div');
      top.className = 'conv-top';
      const nm = document.createElement('span');
      nm.className = 'conv-name';
      nm.textContent = c.name;
      const tm = document.createElement('span');
      tm.className = 'conv-time';
      tm.textContent = fmtConvTime(ts);
      top.append(nm, tm);

      const bottom = document.createElement('div');
      bottom.className = 'conv-bottom';
      const pv = document.createElement('span');
      pv.className = 'conv-preview';
      pv.textContent = preview;
      bottom.appendChild(pv);
      if (meta.unread > 0) {
        const bd = document.createElement('span');
        bd.className = 'badge';
        bd.textContent = meta.unread > 99 ? '99+' : String(meta.unread);
        bottom.appendChild(bd);
      }
      main.append(top, bottom);
      btn.append(av, main);
      btn.addEventListener('click', () => {
        selectCharacter(c.id);
        if (window.matchMedia('(max-width: 880px)').matches) openMobileChat();
      });
      els.convList.appendChild(btn);
    }
  }

  function renderContactList() {
    if (!els.contactList) return;
    els.contactList.innerHTML = '';
    for (const c of state.characters) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mp-contact';
      const av = document.createElement('div');
      av.className = 'avatar bot-avatar';
      fillAvatar(av, c.name, c.id);
      const main = document.createElement('div');
      main.className = 'mp-contact-main';
      const strong = document.createElement('strong');
      strong.textContent = c.name;
      const span = document.createElement('span');
      span.textContent = '点这里开始聊天';
      main.append(strong, span);
      const chev = document.createElement('svg');
      chev.setAttribute('class', 'chev');
      chev.innerHTML = '<use href="#i-back"/>';
      btn.append(av, main, chev);
      btn.addEventListener('click', () => {
        selectCharacter(c.id);
        openMobileChat();
      });
      els.contactList.appendChild(btn);
    }
  }

  function selectCharacter(cid) {
    const char = state.characters.find((c) => c.id === Number(cid));
    if (!char) return;
    if (state.selectMode) exitSelectMode();
    if (char.id === state.bot.id) {
      if (els.searchInput) els.searchInput.value = '';
      renderConvList();
      return;
    }
    const old = state.bot.id;
    if (old) state.charMsgs[old] = state.msgs;
    state.bot = char;
    state.msgs = state.charMsgs[char.id] || [];
    state.lastTs = 0;
    rebuildMidIndex();
    localStorage.setItem('vol.currentPeer', String(char.id));
    clearUnread(char.id);
    applyIdentity();
    renderAll(false);
    if (!state.loaded[char.id]) {
      state.loaded[char.id] = true;
      loadHistoryFor(char.id);
    } else {
      scrollToBottom(false);
    }
  }

  async function loadHistoryFor(id) {
    let history = [];
    try {
      const hist = await call('get_friend_msg_history',
        { user_id: id, count: 80 }, 20000);
      history = hist?.data?.messages || [];
    } catch (e) { /* 历史失败不阻塞聊天 */ }
    if (Number(id) !== Number(state.bot.id)) return;
    mergeHistory(history, id);
  }

  async function syncAllConversations() {
    const currentId = Number(state.bot.id);
    const jobs = state.characters.map(async (c) => {
      const count = c.id === currentId ? 80 : 40;
      try {
        const hist = await call('get_friend_msg_history',
          { user_id: c.id, count }, 20000);
        mergeHistory(hist?.data?.messages || [], c.id, { scroll: false });
        state.loaded[c.id] = true;
      } catch (e) { /* 单个会话失败不影响其他会话 */ }
    });
    await Promise.all(jobs);
    renderConvList();
    scrollToBottom(false);
  }

  // ---------------------------------------------------------- 事件
  function onEvent(ev, replay = false) {
    if (!ev || typeof ev !== 'object') return;
    const isReplay = replay || !!ev._replay;
    if (!state.ready && !isReplay) {
      state.liveBuffer.push(ev);
      return;
    }
    if (ev.post_type === 'message') {
      if (ev.message_type && ev.message_type !== 'private') return;
      handleIncoming(ev, isReplay);
    } else if (ev.post_type === 'message_sent') {
      handleSent(ev);
    } else if (ev.post_type === 'notice') {
      if (ev.notice_type === 'friend_recall' || ev.notice_type === 'group_recall') {
        handleRecall(ev);
      } else if (ev.notice_type === 'read_state') {
        handleReadState(ev);
      }
    }
  }

  function segsOf(ev) {
    return Array.isArray(ev?.message) ? ev.message : [];
  }

  function isStickerSeg(seg) {
    if (!seg || typeof seg !== 'object') return false;
    const d = seg.data || {};
    if (seg.type === 'mface' || seg.type === 'marketface') return true;
    return seg.type === 'image' && String(d.sub_type ?? '') === '1';
  }

  function imageUrlOf(seg) {
    const d = seg?.data || {};
    const candidates = [d.url, d.file, d.path, d.file_path];
    for (const c of candidates) {
      if (typeof c === 'string' && c) {
        if (c.startsWith('file://')) continue;
        return c;
      }
    }
    if (typeof d.base64 === 'string' && d.base64) return 'data:image/png;base64,' + d.base64;
    return '';
  }

  function segsToText(segs) {
    const parts = [];
    for (const seg of (segs || [])) {
      if (!seg || typeof seg !== 'object') continue;
      const d = seg.data || {};
      if (seg.type === 'text') parts.push(String(d.text || ''));
      else if (seg.type === 'image' || seg.type === 'mface' || seg.type === 'marketface') {
        parts.push(isStickerSeg(seg) ? '[表情包]' : '[图片]');
      } else if (seg.type === 'face') parts.push('[表情]');
      else if (seg.type === 'record') parts.push('[语音]');
      else if (seg.type === 'at') parts.push('@' + (d.qq || ''));
      else if (seg.type === 'reply') continue;
      else if (seg.type === 'forward' || seg.type === 'json') parts.push('[聊天记录]');
    }
    return parts.join('');
  }

  function previewOf(msg) {
    if (msg.recalled) return '消息已撤回';
    const t = (msg.text || '').replace(/\s+/g, ' ').trim();
    if (t) return t.length > 42 ? t.slice(0, 42) + '…' : t;
    return '[消息]';
  }

  // ---------------------------------------------------------- 消息模型
  function makeMsg({ dir, segs, text, ts, mid = '', status = 'sent', displaySegs = null }) {
    const key = `m${++state.keySeq}`;
    const t = ts || nowSec();
    return {
      key, dir, segs: displaySegs || segs || [], text: text || '',
      ts: t, mid: String(mid || ''), status,
    };
  }

  function addMsg(msg, force = false) {
    if (!force && msg.mid && state.byMid.has(msg.mid)) return null;
    state.msgs.push(msg);
    if (msg.mid) state.byMid.set(msg.mid, msg);
    hideEmptyState();
    appendRow(msg);
    updateConvPreview(msg);
    if (msg.dir === 'in') {
      const mobileAway = window.matchMedia('(max-width: 880px)').matches &&
        !els.appView.classList.contains('mobile-chat');
      const hidden = document.hidden || !state.atBottom || mobileAway;
      if (hidden) bumpUnread();
      else scrollToBottom(true);
    } else {
      scrollToBottom(true);
    }
    return msg;
  }

  // 历史消息和实时消息可能描述同一条：同一方向、同文本、时间相差 10 秒内
  function normText(s) {
    return String(s || '').replace(/\s+/g, '');
  }

  function coveredByExisting(m, windowSec = 20, list = state.msgs) {
    const target = normText(m.text);
    if (!target) return false;
    const near = list.filter((x) => x.dir === m.dir && x.text &&
      Math.abs((x.ts || 0) - (m.ts || 0)) <= windowSec);
    if (near.some((x) => normText(x.text) === target)) return true;
    const joined = near.map((x) => normText(x.text)).join('');
    if (joined.includes(target)) return true;
    return false;
  }

  function mergeHistory(history, peerId = state.bot.id, opts = {}) {
    const pid = Number(peerId);
    const isCurrent = pid === Number(state.bot.id);
    const list = isCurrent ? state.msgs
      : (state.charMsgs[pid] || (state.charMsgs[pid] = []));
    const seen = new Set(list.map((m) => m.mid).filter(Boolean));
    let added = 0;
    for (const raw of (history || [])) {
      const segs = Array.isArray(raw.message) ? raw.message : [];
      const text = segsToText(segs) || String(raw.raw_message || '');
      if (!text && !segs.length) continue;
      const senderId = Number(raw.sender?.user_id || 0);
      const dir = senderId === pid ? 'in' : 'out';
      const mid = String(raw.message_id || '');
      if (mid && seen.has(mid)) continue;
      const m = makeMsg({
        dir, segs, text: text || '[消息]',
        ts: Number(raw.time) || 0,
        mid,
      });
      // 对方的一轮回复可能是多条气泡拼起来的，时间跨度比单条大；
      // 用户消息仍用 20 秒窗口，避免把重复发的同一句话误删
      if (coveredByExisting(m, dir === 'in' ? 180 : 20, list)) continue;
      list.push(m);
      if (mid) seen.add(mid);
      added += 1;
    }
    if (!added) {
      if (!isCurrent) recomputeUnread(pid);
      return 0;
    }
    list.sort((a, b) => (a.ts - b.ts));
    if (isCurrent) {
      rebuildMidIndex();
      renderAll(false);
    }
    const last = list[list.length - 1];
    if (last) updateConvPreview(last, pid);
    if (isCurrent) {
      markRead(pid, last?.ts || 0);
      clearUnread(pid);
      if (opts.scroll !== false) scrollToBottom(false);
    } else {
      recomputeUnread(pid);
    }
    return added;
  }

  function handleIncoming(ev, replay = false) {
    const mid = String(ev.message_id || '');
    const peer = Number(ev.user_id || ev.sender?.user_id || 0);
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '');
    const msg = makeMsg({
      dir: 'in', segs, text: text || '[消息]',
      ts: Number(ev.time) || nowSec(), mid,
    });

    // 不是当前打开的会话：只更新列表预览和未读
    if (peer && peer !== Number(state.bot.id)) {
      const list = state.charMsgs[peer] || (state.charMsgs[peer] = []);
      if (mid && list.some((m) => m.mid === mid)) return;
      if (replay && coveredByExisting(msg, 180, list)) return;
      list.push(msg);
      list.sort((a, b) => a.ts - b.ts);
      updateConvPreview(msg, peer);
      if (replay) {
        recomputeUnread(peer);
      } else {
        const meta = convMetaFor(peer);
        meta.unread = (meta.unread || 0) + 1;
        state.unread = totalUnread();
        updateBadges();
        renderConvList();
      }
      return;
    }

    if (mid && state.byMid.has(mid)) return;
    // 重放的离线消息 + 历史回放会描述同一批话，按内容去重
    if (replay && coveredByExisting(msg, 180)) return;
    addMsg(msg);
  }

  function handleSent(ev) {
    const mid = String(ev.message_id || '');
    const peer = Number(ev.user_id || state.bot.id);
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '') || '[消息]';
    const replay = !!ev._replay;

    if (peer && peer !== Number(state.bot.id)) {
      const list = state.charMsgs[peer] || (state.charMsgs[peer] = []);
      if (mid && list.some((m) => m.mid === mid)) return;
      const m = makeMsg({
        dir: 'out', segs, text,
        ts: Number(ev.time) || nowSec(), mid,
      });
      if (replay && coveredByExisting(m, 20, list)) return;
      list.push(m);
      list.sort((a, b) => a.ts - b.ts);
      updateConvPreview(m, peer);
      renderConvList();
      return;
    }

    if (mid && state.byMid.has(mid)) return;

    // 本机刚发出的消息：把服务端正式 id 绑到乐观气泡上，避免出现两条
    const recent = state.msgs.find((m) => m.dir === 'out' && !m.mid &&
      m.status === 'pending' && m.text === text &&
      nowSec() - m.ts <= 20);
    if (recent) {
      if (mid) {
        recent.mid = mid;
        state.byMid.set(mid, recent);
      }
      if (recent.status !== 'failed') {
        recent.status = 'sent';
        refreshRow(recent);
      }
      return;
    }
    const m = makeMsg({
      dir: 'out', segs, text,
      ts: Number(ev.time) || nowSec(), mid,
    });
    if (replay && coveredByExisting(m, 20)) return;
    addMsg(m);
  }

  function handleReadState(ev) {
    const peer = Number(ev.user_id || ev.target_id || 0);
    const ts = Number(ev.read_time || ev.time || 0);
    if (!peer || !ts) return;
    const key = String(peer);
    if (ts <= Number(state.lastRead[key] || 0)) return;
    state.lastRead[key] = ts;
    saveLastRead();
    if (peer !== Number(state.bot.id)) {
      recomputeUnread(peer);
    } else {
      const meta = convMetaFor(peer);
      meta.unread = 0;
      state.unread = totalUnread();
      updateBadges();
      updateDocTitle();
      renderConvList();
    }
  }

  function handleRecall(ev) {
    const mid = String(ev.message_id || '');
    if (!mid) return;
    const peer = Number(ev.user_id || ev.target_id || 0);
    const isCurrent = !peer || peer === Number(state.bot.id);
    const list = isCurrent ? state.msgs
      : (state.charMsgs[peer] || []);
    const msg = list.find((m) => m.mid === mid);
    if (!msg) return;
    if (msg.recalled) return;
    msg.recalled = msg.dir === 'out' ? 'me' : 'bot';
    state.selected.delete(msg.key);
    if (isCurrent) {
      refreshRow(msg);
      updateMultiBar();
      const last = list[list.length - 1];
      if (last && last.key === msg.key) updateConvPreview(last, peer || state.bot.id);
      toast(msg.dir === 'out' ? '你撤回了一条消息' : '对方撤回了一条消息');
    } else {
      const last = list[list.length - 1];
      if (last) updateConvPreview(last, peer);
      recomputeUnread(peer);
    }
  }

  // ---------------------------------------------------------- 渲染
  function rowElOf(msg) {
    return els.msgList.querySelector(`[data-key="${msg.key}"]`);
  }

  function resolveAsset(url) {
    if (!url || typeof url !== 'string') return '';
    if (url.startsWith('data:') || url.startsWith('blob:')) return url;
    if (url.startsWith('base64://')) return 'data:image/png;base64,' + url.slice(9);
    if (url.startsWith('file://')) return '';
    try {
      const abs = new URL(url, location.origin);
      const localHosts = ['127.0.0.1', 'localhost', '0.0.0.0', '[::1]'];
      if (localHosts.includes(abs.hostname) && abs.origin !== location.origin) {
        return abs.pathname + abs.search;
      }
      return abs.href;
    } catch (e) {
      return url;
    }
  }

  function appendTextWithLinks(parent, text) {
    const re = /(https?:\/\/[^\s<>"']+)/g;
    let last = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      const a = document.createElement('a');
      a.href = m[0];
      a.target = '_blank';
      a.rel = 'noreferrer noopener';
      a.textContent = m[0];
      parent.appendChild(a);
      last = m.index + m[0].length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  const CAN_HOVER = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  function makeImage(url, sticker) {
    const img = document.createElement('img');
    // 聊天里的图片/表情包直接加载原图：GIF 自动播放。
    // 「悬停才动」只用于上面的表情选择面板（那里用首帧缩略图省性能）。
    img.src = resolveAsset(url);
    img.loading = 'lazy';
    img.alt = sticker ? '表情包' : '图片';
    img.addEventListener('click', (e) => {
      e.stopPropagation();
      openLightbox(img.src);
    });
    img.addEventListener('error', () => {
      const box = document.createElement('span');
      box.className = 'face-chip';
      box.textContent = sticker ? '[表情包加载失败]' : '[图片加载失败]';
      img.replaceWith(box);
    });
    return img;
  }

  function buildBubble(msg) {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    const segs = (msg.segs || []).filter((s) => s && typeof s === 'object');
    const text = segs.filter((s) => s.type === 'text')
      .map((s) => String(s.data?.text || '')).join('');
    const media = segs.filter((s) => s.type === 'image' || s.type === 'mface' ||
      s.type === 'marketface');
    const hasSticker = media.some(isStickerSeg);
    const onlyMedia = media.length > 0 && !text.trim() &&
      segs.every((s) => s.type === 'image' || s.type === 'mface' ||
        s.type === 'marketface' || s.type === 'reply');

    if (onlyMedia) {
      if (hasSticker) {
        bubble.classList.add('sticker');
        for (const seg of media) {
          const url = imageUrlOf(seg);
          if (url) bubble.appendChild(makeImage(url, true));
          else {
            const chip = document.createElement('span');
            chip.className = 'face-chip';
            chip.textContent = '[表情包]';
            bubble.appendChild(chip);
          }
        }
      } else {
        bubble.classList.add('media');
        for (const seg of media) {
          const url = imageUrlOf(seg);
          if (url) bubble.appendChild(makeImage(url, false));
        }
      }
      if (!bubble.childNodes.length) bubble.textContent = '[图片]';
      applyBubbleDecor(bubble, chatThemeFor(state.bot.id, msg.dir));
      return bubble;
    }

    for (const seg of segs) {
      const d = seg.data || {};
      if (seg.type === 'text') {
        const raw = String(d.text || '');
        if (raw) appendTextWithLinks(bubble, raw);
      } else if (seg.type === 'image' || seg.type === 'mface' || seg.type === 'marketface') {
        const url = imageUrlOf(seg);
        if (url) {
          bubble.appendChild(document.createElement('br'));
          bubble.appendChild(makeImage(url, isStickerSeg(seg)));
        }
      } else if (seg.type === 'face') {
        const chip = document.createElement('span');
        chip.className = 'face-chip';
        chip.textContent = '表情';
        bubble.appendChild(chip);
      } else if (seg.type === 'at') {
        const chip = document.createElement('span');
        chip.className = 'face-chip';
        chip.textContent = '@' + (d.qq || '');
        bubble.appendChild(chip);
      } else if (seg.type === 'record') {
        const chip = document.createElement('span');
        chip.className = 'face-chip';
        chip.textContent = '语音';
        bubble.appendChild(chip);
      } else if (seg.type === 'forward' || seg.type === 'json') {
        const chip = document.createElement('span');
        chip.className = 'face-chip';
        chip.textContent = '[聊天记录]';
        bubble.appendChild(chip);
      }
    }
    if (!bubble.childNodes.length) bubble.textContent = msg.text || '[消息]';
    applyBubbleDecor(bubble, chatThemeFor(state.bot.id, msg.dir));
    return bubble;
  }

  function buildRow(msg) {
    const row = document.createElement('div');
    row.className = 'msg-row ' + (msg.dir === 'out' ? 'out' : 'in');
    if (msg.status === 'pending') row.classList.add('pending');
    if (msg.status === 'failed') row.classList.add('failed');
    if (state.selected.has(msg.key)) row.classList.add('selected');
    row.dataset.key = msg.key;
    if (msg.mid) row.dataset.mid = msg.mid;

    if (msg.recalled) {
      row.classList.add('recalled');
      const tip = document.createElement('div');
      tip.className = 'recalled-tip';
      tip.textContent = msg.dir === 'out'
        ? '你撤回了一条消息' : '对方撤回了一条消息';
      row.appendChild(tip);
      row.addEventListener('contextmenu', (e) => e.preventDefault());
      return row;
    }

    const check = document.createElement('span');
    check.className = 'msg-check';
    check.setAttribute('role', 'checkbox');
    check.setAttribute('aria-checked',
      state.selected.has(msg.key) ? 'true' : 'false');
    check.tabIndex = 0;
    check.innerHTML = '<svg><use href="#i-check"/></svg>';
    check.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        toggleSelect(msg);
      }
    });

    const av = document.createElement('div');
    av.className = 'avatar ' + (msg.dir === 'out' ? 'me-avatar' : 'bot-avatar');
    av.title = msg.dir === 'out' ? state.me.name : state.bot.name;
    if (msg.dir === 'out') fillAvatar(av, state.me.name, state.me.id, '我');
    else fillAvatar(av, state.bot.name, state.bot.id);

    const body = document.createElement('div');
    body.className = 'msg-body';
    body.appendChild(buildBubble(msg));
    row.classList.toggle('has-tag', !!body.querySelector('.bubble-tag'));

    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    const time = document.createElement('span');
    time.textContent = fmtClock(msg.ts);
    meta.appendChild(time);

    if (msg.status === 'pending') {
      const s = document.createElement('span');
      s.textContent = '发送中…';
      meta.appendChild(s);
    } else if (msg.status === 'failed') {
      const retry = document.createElement('button');
      retry.className = 'retry';
      retry.textContent = '发送失败，点此重试';
      retry.addEventListener('click', (e) => {
        e.stopPropagation();
        resend(msg);
      });
      meta.appendChild(retry);
    }

    body.appendChild(meta);
    row.append(check, av, body);
    // 多选模式下整行点击切换选中；捕获阶段拦掉图片预览/链接等子元素行为
    row.addEventListener('click', (e) => {
      if (!state.selectMode) return;
      e.preventDefault();
      e.stopPropagation();
      if (Date.now() < state.suppressClickUntil) return;
      toggleSelect(msg);
    }, true);
    row.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (state.selectMode) return;
      openCtx(e.clientX, e.clientY, msg);
    });
    return row;
  }

  function appendSeparator(ts) {
    const sep = document.createElement('div');
    sep.className = 'day-sep';
    sep.textContent = fmtSep(ts);
    sep.dataset.sep = '1';
    els.msgList.appendChild(sep);
  }

  function appendRow(msg) {
    if (!msg.ts) msg.ts = nowSec();
    if (!state.lastTs || msg.ts - state.lastTs > 300) {
      appendSeparator(msg.ts);
    }
    state.lastTs = Math.max(state.lastTs || 0, msg.ts);
    els.msgList.appendChild(buildRow(msg));
  }

  function refreshRow(msg) {
    const old = rowElOf(msg);
    if (!old) return;
    const row = buildRow(msg);
    old.replaceWith(row);
  }

  function renderAll(scrollBottom) {
    els.msgList.innerHTML = '';
    state.lastTs = 0;
    if (!state.msgs.length) {
      els.msgList.appendChild(els.emptyState);
      els.emptyState.classList.remove('hidden');
    } else {
      hideEmptyState();
      for (const m of state.msgs) appendRow(m);
    }
    if (scrollBottom) scrollToBottom(false);
  }

  function hideEmptyState() {
    if (els.emptyState && els.emptyState.parentNode) {
      els.emptyState.classList.add('hidden');
    }
  }

  function updateConvPreview(msg, peerId = state.bot.id) {
    const meta = convMetaFor(peerId);
    meta.preview = (msg.dir === 'out' ? '我：' : '') + previewOf(msg);
    meta.ts = msg.ts;
    renderConvList();
  }

  // ---------------------------------------------------------- 滚动 / 未读
  function isAtBottom() {
    const el = els.msgScroll;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  }

  function scrollToBottom(smooth) {
    requestAnimationFrame(() => {
      els.msgScroll.scrollTo({
        top: els.msgScroll.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto',
      });
      state.atBottom = true;
      clearUnread();
    });
  }

  function bumpUnread(peerId = state.bot.id) {
    const meta = convMetaFor(peerId);
    meta.unread = (meta.unread || 0) + 1;
    state.unread = totalUnread();
    updateBadges();
    renderConvList();
    updateDocTitle();
  }

  function clearUnread(peerId = state.bot.id) {
    markRead(peerId, 0);
    const meta = convMetaFor(peerId);
    meta.unread = 0;
    state.unread = totalUnread();
    updateBadges();
    renderConvList();
    updateDocTitle();
  }

  function updateBadges() {
    const n = state.unread;
    els.toBottomBadge.textContent = n > 99 ? '99+' : String(n);
    els.toBottomBadge.classList.toggle('hidden', n === 0);
    if (els.navBadge) {
      els.navBadge.textContent = n > 99 ? '99+' : String(n);
      els.navBadge.classList.toggle('hidden', n === 0);
    }
  }

  els.msgScroll.addEventListener('scroll', () => {
    state.atBottom = isAtBottom();
    els.toBottom.classList.toggle('hidden', state.atBottom);
    if (state.atBottom) clearUnread();
  }, { passive: true });

  els.toBottom.addEventListener('click', () => scrollToBottom(true));

  // ---------------------------------------------------------- 发送
  function autosize() {
    const ta = els.input;
    ta.style.height = 'auto';
    ta.style.height = Math.min(148, Math.max(44, ta.scrollHeight)) + 'px';
  }

  function updateSendBtn() {
    const disabled = !els.input.value.trim();
    els.sendBtn.disabled = disabled;
  }

  els.input.addEventListener('input', () => {
    autosize();
    updateSendBtn();
  });

  els.input.addEventListener('keydown', (e) => {
    const mobile = window.matchMedia('(max-width: 880px)').matches;
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !mobile) {
      e.preventDefault();
      sendText();
    }
  });

  els.sendBtn.addEventListener('click', sendText);

  function sendText() {
    const text = els.input.value;
    if (!text.trim()) return;
    if (!state.connected) {
      toast('还没连上，稍等一下再发');
      return;
    }
    els.input.value = '';
    autosize();
    updateSendBtn();
    doSend([{ type: 'text', data: { text } }], text);
    els.input.focus();
  }

  async function doSend(sendSegs, text, displaySegs = null) {
    if (!state.connected) {
      toast('还没连上，稍等一下再发');
      return;
    }
    const msg = addMsg(makeMsg({
      dir: 'out', segs: sendSegs, displaySegs,
      text: text || segsToText(displaySegs || sendSegs),
      ts: nowSec(), status: 'pending',
    }));
    if (!msg) return;
    try {
      const res = await call('send_msg', {
        message_type: 'private',
        user_id: state.bot.id,
        message: sendSegs,
      }, 25000);
      if (!res || res.status !== 'ok') throw new Error(res?.wording || '发送失败');
      const mid = String(res?.data?.message_id || '');
      msg.mid = mid;
      if (mid) state.byMid.set(mid, msg);
      msg.status = 'sent';
      refreshRow(msg);
    } catch (e) {
      msg.status = 'failed';
      refreshRow(msg);
      toast('发送失败：' + (e?.message || e));
    }
  }

  async function resend(msg) {
    if (msg.status === 'pending') return;
    msg.status = 'pending';
    msg.ts = nowSec();
    refreshRow(msg);
    try {
      const res = await call('send_msg', {
        message_type: 'private', user_id: state.bot.id, message: msg.segs,
      }, 25000);
      if (!res || res.status !== 'ok') throw new Error(res?.wording || '发送失败');
      msg.mid = String(res?.data?.message_id || '');
      if (msg.mid) state.byMid.set(msg.mid, msg);
      msg.status = 'sent';
      refreshRow(msg);
      toast('已重新发送');
    } catch (e) {
      msg.status = 'failed';
      refreshRow(msg);
      toast('发送失败：' + (e?.message || e));
    }
  }

  // ---------------------------------------------------------- 图片
  els.imageBtn.addEventListener('click', () => els.fileInput.click());
  els.fileInput.addEventListener('change', () => {
    const files = [...(els.fileInput.files || [])];
    els.fileInput.value = '';
    files.forEach(sendImageFile);
  });

  function readDataURL(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result));
      fr.onerror = () => reject(new Error('读取文件失败'));
      fr.readAsDataURL(file);
    });
  }

  async function prepareImage(file) {
    if (file.type === 'image/gif' || file.size < 1_200_000) {
      return { dataUrl: await readDataURL(file), name: file.name || 'image.png' };
    }
    const bitmap = await createImageBitmap(file);
    const max = 1600;
    const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    if (bitmap.close) bitmap.close();
    const base = (file.name || 'image').replace(/\.[^.]+$/, '');
    return { dataUrl: canvas.toDataURL('image/jpeg', 0.86), name: base + '.jpg' };
  }

  async function sendImageFile(file) {
    if (!file || !file.type || !file.type.startsWith('image/')) return;
    try {
      const { dataUrl, name } = await prepareImage(file);
      const base64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
      const sendSeg = {
        type: 'image',
        data: { file: 'base64://' + base64, file_name: name, sub_type: 0, summary: '[图片]' },
      };
      const showSeg = {
        type: 'image',
        data: { file: dataUrl, sub_type: 0, summary: '[图片]' },
      };
      await doSend([sendSeg], '[图片]', [showSeg]);
    } catch (e) {
      toast('图片发送失败：' + (e?.message || e));
    }
  }

  els.input.addEventListener('paste', (e) => {
    const items = [...(e.clipboardData?.items || [])];
    const files = items.filter((it) => it.type.startsWith('image/'))
      .map((it) => it.getAsFile()).filter(Boolean);
    if (files.length) {
      e.preventDefault();
      files.forEach(sendImageFile);
    }
  });

  function hasFiles(e) {
    const types = e.dataTransfer?.types || [];
    return [...types].includes('Files');
  }
  els.chatPane.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    state.dragDepth += 1;
    els.dropMask.classList.remove('hidden');
  });
  els.chatPane.addEventListener('dragover', (e) => {
    if (hasFiles(e)) e.preventDefault();
  });
  els.chatPane.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    state.dragDepth = Math.max(0, state.dragDepth - 1);
    if (state.dragDepth === 0) els.dropMask.classList.add('hidden');
  });
  els.chatPane.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    state.dragDepth = 0;
    els.dropMask.classList.add('hidden');
    const files = [...(e.dataTransfer?.files || [])];
    files.filter((f) => f.type.startsWith('image/')).forEach(sendImageFile);
  });

  // ---------------------------------------------------------- 表情
  const EMOJI = {
    '常用': ['😀','😃','😄','😁','😆','😅','😂','🤣','🙂','🙃','😉','😊','😇','🥰','😍','🤩','😘','😗','😚','😙','😋','😛','😜','🤪','😝','🤗','🤭','🤫','🤔','😐','😑','😶','🙄','😏','😒','😞','😔','😟','😕','🙁','☹️','😣','😖','😫','😩','🥺','😢','😭','😤','😠','😡','🤬','🤯','😳','🥵','🥶','😱','😨','😰','😥','😓','','😴','🥱'],
    '手势': ['👍','👎','👌','✌️','🤞','🤟','🤘','🤙','👈','👉','👆','👇','☝️','✋','🤚','🖐️','🖖','👋','🤝','🙏','💪','👏','🙌','👐','🤲'],
    '爱心': ['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','❣️','💕','💞','💓','💗','💖','💘','💝','💟','♥️'],
    '动物': ['🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐨','🐯','🦁','🐮','🐷','🐸','🐵','🐔','🐧','🐦','🐤','🦄','🐝','🦋','🐢','🐬','🐳','🐙','🦐','🦀'],
    '食物': ['🍎','🍊','🍋','🍌','🍉','🍇','🍓','🍒','🍑','🥭','🍍','🥥','🥝','🍅','🥑','🍞','🥐','🥨','🧀','🍔','🍟','🍕','🌭','🍿','🍩','🍪','🎂','🍰','🧁','🍫','🍬','🍭','☕','🍵','🧋','🍺'],
    '其他': ['⭐','🌟','✨','⚡','🔥','💥','💫','🌈','☀️','🌙','⛅','☁️','🌧️','❄️','🎉','🎊','🎁','🎈','🎵','🎶','💤','💦','💨','🍀','🌸','🌻','🌷','🌹'],
  };
  const EMOJI_TABS = Object.keys(EMOJI);

  function renderEmoji() {
    els.emojiTabs.innerHTML = '';
    EMOJI_TABS.forEach((name, i) => {
      const b = document.createElement('button');
      b.className = 'tab' + (i === state.emojiCat ? ' active' : '');
      b.textContent = name;
      b.addEventListener('click', () => {
        state.emojiCat = i;
        renderEmoji();
      });
      els.emojiTabs.appendChild(b);
    });

    els.emojiGrid.innerHTML = '';
    for (const emoji of EMOJI[EMOJI_TABS[state.emojiCat]]) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = emoji;
      b.title = emoji;
      b.addEventListener('click', () => {
        insertAtCursor(emoji);
      });
      els.emojiGrid.appendChild(b);
    }
  }

  function insertAtCursor(text) {
    const ta = els.input;
    const start = ta.selectionStart ?? ta.value.length;
    const end = ta.selectionEnd ?? start;
    ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    const pos = start + text.length;
    ta.focus();
    try { ta.setSelectionRange(pos, pos); } catch (e) { /* ignore */ }
    autosize();
    updateSendBtn();
  }

  // ---------------------------------------------------------- 表情包
  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set('Authorization', 'Bearer ' + state.token);
    return fetch(url, { ...options, headers });
  }

  async function loadStickerSets() {
    try {
      const res = await apiFetch('/api/sticker-sets', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      state.stickerSets = (data && typeof data.sets === 'object') ? data.sets : {};
      state.stickerSetsLoaded = true;
      if (state.stickers) {
        renderStickerTabs();
        renderStickerGrid();
      }
      renderChatSettings();
    } catch (e) { /* 老服务端没有这个接口时静默 */ }
  }

  function visibleStickerGroups() {
    const all = state.stickers || [];
    if (state.stickerManage) return all;
    const allowed = state.stickerSets[String(state.bot.id)];
    if (!Array.isArray(allowed)) return all;
    return all.filter((g) => allowed.includes(g.key || g.name));
  }

  async function loadStickers(force = false) {
    if (state.stickers && !force) {
      renderStickerTabs();
      renderStickerGrid();
      return;
    }
    els.stickerGrid.innerHTML = '';
    const loading = document.createElement('div');
    loading.className = 'panel-empty';
    loading.textContent = '正在加载表情包…';
    els.stickerGrid.appendChild(loading);
    if (!state.stickerSetsLoaded) loadStickerSets();

    try {
      const res = await fetch('/api/stickers', { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      state.stickers = Array.isArray(data.groups) ? data.groups : [];
      const visible = visibleStickerGroups();
      if (!visible.some((g) => (g.key || g.name) === state.stickerGroupKey)) {
        state.stickerGroupKey = visible[0]?.key || visible[0]?.name || null;
      }
      renderStickerTabs();
      renderStickerGrid();
      renderChatSettings();
    } catch (e) {
      els.stickerGrid.innerHTML = '';
      const err = document.createElement('div');
      err.className = 'panel-empty';
      err.textContent = '表情包加载失败：' + (e?.message || e);
      els.stickerGrid.appendChild(err);
    }
  }

  function renderStickerTabs() {
    const groups = visibleStickerGroups();
    if (!groups.some((g) => (g.key || g.name) === state.stickerGroupKey)) {
      state.stickerGroupKey = groups[0]?.key || groups[0]?.name || null;
    }
    els.stickerTabs.innerHTML = '';
    groups.forEach((group) => {
      const key = group.key || group.name;
      const b = document.createElement('button');
      b.className = 'tab' + (key === state.stickerGroupKey ? ' active' : '');
      b.textContent = `${group.name} (${(group.items || []).length})`;
      b.addEventListener('click', () => {
        state.stickerGroupKey = key;
        state.stickerQuery = '';
        els.stickerSearch.value = '';
        renderStickerTabs();
        renderStickerGrid();
      });
      els.stickerTabs.appendChild(b);
    });
  }

  function normalizeSticker(item) {
    const safeDecode = (s) => {
      try { return decodeURIComponent(s); } catch (e) { return s; }
    };
    if (typeof item === 'string') {
      return {
        url: item,
        thumb: item,
        animated: /\.(gif|webp)(\?|$)/i.test(item),
        name: safeDecode((item.split('/').pop() || '')),
        path: '',
        group: '',
      };
    }
    const url = String(item?.url || '');
    return {
      url,
      thumb: String(item?.thumb || url),
      animated: !!item?.animated,
      name: safeDecode((url.split('/').pop() || '')),
      path: String(item?.path || ''),
      group: String(item?.group || ''),
    };
  }

  function addStickerTile() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sticker-item add';
    btn.title = '添加表情';
    btn.innerHTML = '<svg><use href="#i-plus"/></svg><span>添加</span>';
    btn.addEventListener('click', () => els.stickerUploadInput.click());
    return btn;
  }

  function renderStickerGrid() {
    const groups = visibleStickerGroups();
    const q = state.stickerQuery.trim().toLowerCase();
    let items = [];
    if (q) {
      const seen = new Set();
      for (const g of groups) {
        for (const raw of (g.items || [])) {
          const it = normalizeSticker(raw);
          const hay = (it.url + ' ' + it.name).toLowerCase();
          if (hay.includes(q) && !seen.has(it.url)) {
            seen.add(it.url);
            items.push(it);
          }
        }
      }
    } else {
      const group = groups.find((g) => (g.key || g.name) === state.stickerGroupKey);
      items = (group?.items || []).map(normalizeSticker);
    }

    els.stickerGrid.innerHTML = '';
    const empty = !items.length && !(state.stickerManage && !q);
    els.stickerEmpty.classList.toggle('hidden', !empty);
    if (empty) {
      els.stickerEmpty.textContent = q
        ? '没有找到这个表情…'
        : (state.stickerSetsLoaded && !state.stickerManage && !groups.length
          ? '这个对话还没有可用的表情包，去聊天设置里勾选，或点“管理”添加'
          : '这里还没有表情');
    }

    const frag = document.createDocumentFragment();
    if (state.stickerManage && !q) frag.appendChild(addStickerTile());
    for (const it of items) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sticker-item loading';
      btn.title = state.stickerManage ? '点 × 删除' : '点击发送（悬停看动图）';
      btn.dataset.animated = it.animated ? '1' : '0';
      btn.dataset.url = it.url;
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.decoding = 'async';
      img.src = it.thumb || it.url;
      img.alt = '表情包';
      img.addEventListener('load', () => btn.classList.remove('loading'));

      let animBroken = false;
      const playAnim = () => {
        if (!CAN_HOVER || !it.animated || animBroken) return;
        img.src = it.url;
      };
      const stopAnim = () => {
        if (!CAN_HOVER || !it.animated) return;
        img.src = it.thumb || it.url;
      };
      btn.addEventListener('mouseenter', playAnim);
      btn.addEventListener('mouseleave', stopAnim);

      img.addEventListener('error', () => {
        // 缩略图失败 → 退原图；原图也失败 → 隐藏这一格
        if (img.src !== new URL(it.url, location.origin).href && !animBroken) {
          img.src = it.url;
          return;
        }
        btn.remove();
      });
      btn.appendChild(img);
      btn.addEventListener('click', () => {
        if (!state.stickerManage) sendSticker(it.url);
      });
      if (state.stickerManage && it.path) {
        const del = document.createElement('span');
        del.className = 'sticker-del';
        del.title = '删除这张表情';
        del.setAttribute('role', 'button');
        del.textContent = '×';
        del.addEventListener('click', (e) => {
          e.stopPropagation();
          deleteSticker(it);
        });
        btn.appendChild(del);
      }
      frag.appendChild(btn);
    }
    els.stickerGrid.appendChild(frag);
    els.stickerGrid.scrollTop = 0;
  }

  function setStickerManage(on) {
    state.stickerManage = !!on;
    els.stickerManageBtn.textContent = on ? '完成' : '管理';
    els.stickerManageBtn.classList.toggle('active', on);
    els.stickerManageBar.classList.toggle('hidden', !on);
    if (state.stickers) {
      renderStickerTabs();
      renderStickerGrid();
    }
  }

  async function deleteSticker(it) {
    if (!it.path) {
      toast('这张表情没有文件路径，无法删除');
      return;
    }
    if (!confirm(`从图库删除这张表情？\n${it.name || it.path}\n删除后 vol 也不会再用它。`)) return;
    try {
      const res = await apiFetch('/api/stickers/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: it.path }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      toast('已从图库删除');
      await loadStickers(true);
    } catch (e) {
      toast('删除失败：' + (e?.message || e));
    }
  }

  async function uploadStickerFiles(fileList) {
    const isImage = (f) => (f.type && f.type.startsWith('image/')) ||
      /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name || '');
    const files = [...(fileList || [])].filter(isImage);
    if (!files.length) {
      toast('请选择图片文件');
      return;
    }
    const targetGroup = (state.stickerGroupKey && state.stickerGroupKey !== '其他')
      ? state.stickerGroupKey : 'custom';
    let ok = 0;
    for (const f of files) {
      if (f.size > 8 * 1024 * 1024) {
        toast(`${f.name || '图片'} 超过 8MB，已跳过`);
        continue;
      }
      try {
        const data = await readDataURL(f);
        const res = await apiFetch('/api/stickers/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: f.name || 'sticker.png',
            data,
            group: targetGroup,
          }),
        });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
        ok += 1;
      } catch (e) {
        toast(`上传 ${f.name || '图片'} 失败：${(e?.message || e)}`);
      }
    }
    if (ok) {
      toast(`已添加 ${ok} 张表情`);
      state.stickerGroupKey = targetGroup;
      await loadStickers(true);
      await loadStickerSets();
    }
  }

  function openCategoryModal() {
    els.categoryName.value = '';
    els.categoryMask.classList.remove('hidden');
    setTimeout(() => els.categoryName.focus(), 50);
  }

  function closeCategoryModal() {
    els.categoryMask.classList.add('hidden');
  }

  async function createCategory() {
    const name = els.categoryName.value.trim();
    if (!name) {
      toast('请输入分类名称');
      els.categoryName.focus();
      return;
    }
    try {
      const res = await apiFetch('/api/sticker-category/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      closeCategoryModal();
      toast(`已创建分类「${out.name}」`);
      state.stickerGroupKey = out.key;
      await loadStickers(true);
      await loadStickerSets();
    } catch (e) {
      toast('创建失败：' + (e?.message || e));
    }
  }

  async function deleteActiveCategory() {
    const groups = visibleStickerGroups();
    const group = groups.find((g) => (g.key || g.name) === state.stickerGroupKey);
    if (!group) {
      toast('请先选择一个分类');
      return;
    }
    const key = group.key || group.name;
    if (!key || key === '其他') {
      toast('这个分类不能删除');
      return;
    }
    const count = (group.items || []).length;
    if (!confirm(`删除分类「${group.name}」？\n其中的 ${count} 张表情会一起删除，无法恢复。`)) {
      return;
    }
    try {
      const res = await apiFetch('/api/sticker-category/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      toast(`已删除分类「${group.name}」`);
      state.stickerGroupKey = null;
      await loadStickers(true);
      await loadStickerSets();
    } catch (e) {
      toast('删除失败：' + (e?.message || e));
    }
  }

  async function sendSticker(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const blob = await res.blob();
      const dataUrl = await new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(String(fr.result));
        fr.onerror = () => reject(new Error('读取失败'));
        fr.readAsDataURL(blob);
      });
      const base64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
      const name = decodeURIComponent((url.split('/').pop() || 'sticker.png'));
      const ext = (name.split('.').pop() || 'png').toLowerCase();
      const sendSeg = {
        type: 'image',
        data: {
          file: 'base64://' + base64,
          file_name: 'sticker.' + ext,
          sub_type: 1,
          summary: '[表情包]',
        },
      };
      const showSeg = {
        type: 'image',
        data: { file: url, sub_type: 1, summary: '[表情包]' },
      };
      await doSend([sendSeg], '[表情包]', [showSeg]);
    } catch (e) {
      toast('表情包发送失败：' + (e?.message || e));
    }
  }

  els.stickerSearch.addEventListener('input', () => {
    state.stickerQuery = els.stickerSearch.value || '';
    renderStickerGrid();
  });

  els.stickerManageBtn.addEventListener('click', () => {
    setStickerManage(!state.stickerManage);
  });
  els.stickerAddBtn.addEventListener('click', () => els.stickerUploadInput.click());
  els.stickerUploadInput.addEventListener('change', () => {
    const files = [...(els.stickerUploadInput.files || [])];
    els.stickerUploadInput.value = '';
    uploadStickerFiles(files);
  });
  els.stickerCategoryAdd.addEventListener('click', openCategoryModal);
  els.stickerCategoryDel.addEventListener('click', deleteActiveCategory);
  els.categoryClose.addEventListener('click', closeCategoryModal);
  els.categoryCancel.addEventListener('click', closeCategoryModal);
  els.categoryMask.addEventListener('click', (e) => {
    if (e.target === els.categoryMask) closeCategoryModal();
  });
  els.categoryCreate.addEventListener('click', createCategory);
  els.categoryName.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      createCategory();
    }
  });
  els.stickerGrid.addEventListener('dragover', (e) => {
    if (state.stickerManage && [...(e.dataTransfer?.types || [])].includes('Files')) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
  els.stickerGrid.addEventListener('drop', (e) => {
    if (!state.stickerManage) return;
    e.preventDefault();
    e.stopPropagation();
    uploadStickerFiles(e.dataTransfer?.files);
  });

  // ---------------------------------------------------------- 面板开关
  function showPanel(id) {
    hidePanels();
    const panel = document.getElementById(id);
    if (!panel) return;
    panel.classList.remove('hidden');
    if (id === 'stickerPanel') {
      loadStickers();
      els.stickerBtn.classList.add('active');
    } else {
      els.emojiBtn.classList.add('active');
    }
  }

  function hidePanels() {
    if (state.stickerManage) setStickerManage(false);
    els.emojiPanel.classList.add('hidden');
    els.stickerPanel.classList.add('hidden');
    els.emojiBtn.classList.remove('active');
    els.stickerBtn.classList.remove('active');
  }

  function togglePanel(id) {
    const panel = document.getElementById(id);
    if (panel.classList.contains('hidden')) showPanel(id);
    else hidePanels();
  }

  els.emojiBtn.addEventListener('click', () => togglePanel('emojiPanel'));
  els.stickerBtn.addEventListener('click', () => togglePanel('stickerPanel'));
  els.railSticker.addEventListener('click', () => {
    if (window.matchMedia('(max-width: 880px)').matches) {
      els.appView.classList.add('mobile-chat');
    }
    showPanel('stickerPanel');
  });
  document.querySelectorAll('[data-close]').forEach((b) => {
    b.addEventListener('click', hidePanels);
  });

  // ---------------------------------------------------------- 右键菜单
  function openCtx(x, y, msg) {
    state.ctxMsg = msg;
    els.moreMenu.classList.add('hidden');
    els.ctxMenu.classList.remove('hidden');
    const btns = els.ctxMenu.querySelectorAll('button');
    btns[1].classList.toggle('hidden', msg.dir !== 'out');
    const recallBtn = els.ctxMenu.querySelector('button[data-act="recall"]');
    if (recallBtn) {
      recallBtn.classList.toggle('hidden', !msg.mid || !!msg.recalled);
    }
    const rect = els.ctxMenu.getBoundingClientRect();
    const px = Math.min(x, window.innerWidth - rect.width - 8);
    const py = Math.min(y, window.innerHeight - rect.height - 8);
    els.ctxMenu.style.left = Math.max(8, px) + 'px';
    els.ctxMenu.style.top = Math.max(8, py) + 'px';
  }

  function closeCtx() {
    els.ctxMenu.classList.add('hidden');
    els.moreMenu.classList.add('hidden');
    state.ctxMsg = null;
  }

  els.ctxMenu.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const msg = state.ctxMsg;
    const act = btn.dataset.act;
    closeCtx();
    if (!msg) return;
    if (act === 'copy') copyText(msg.text || previewOf(msg));
    else if (act === 'resend') resend(msg);
    else if (act === 'recall') recallMessage(msg);
    else if (act === 'delete') {
      state.msgs = state.msgs.filter((m) => m.key !== msg.key);
      if (msg.mid) state.byMid.delete(msg.mid);
      renderAll(false);
      toast('已从本机删除（不影响 vol 的记忆）');
    }
  });

  // ---------------------------------------------------------- 多选 / 转发 / 撤回
  function applyRecallLocally(msg, peerId, silent = false) {
    if (!msg || msg.recalled) return false;
    const pid = Number(peerId || state.bot.id);
    const isCurrent = pid === Number(state.bot.id);
    const list = isCurrent ? state.msgs
      : (state.charMsgs[pid] || []);
    msg.recalled = msg.dir === 'out' ? 'me' : 'bot';
    state.selected.delete(msg.key);
    if (isCurrent) {
      refreshRow(msg);
      updateMultiBar();
      const last = list[list.length - 1];
      if (last && last.key === msg.key) updateConvPreview(last, pid);
    } else {
      const last = list[list.length - 1];
      if (last) updateConvPreview(last, pid);
      recomputeUnread(pid);
    }
    if (!silent) {
      toast(msg.dir === 'out' ? '你撤回了一条消息' : '对方撤回了一条消息');
    }
    return true;
  }

  async function recallMessage(msg, quiet = false) {
    if (!msg || msg.recalled) return false;
    if (!msg.mid) {
      if (!quiet) toast('这条消息还没有消息 ID，无法撤回');
      return false;
    }
    try {
      const res = await call('delete_msg', {
        message_id: msg.mid,
        peer_id: state.bot.id,
        text: msg.text || '',
        ts: msg.ts || 0,
      }, 10000);
      if (!res || res.status !== 'ok') throw new Error(res?.wording || '撤回失败');
      applyRecallLocally(msg, state.bot.id, true);
      if (!quiet) toast('已撤回');
      return true;
    } catch (e) {
      if (!quiet) toast('撤回失败：' + (e?.message || e));
      return false;
    }
  }

  function applySelection(next) {
    state.selected = next;
    for (const row of els.msgList.querySelectorAll('.msg-row[data-key]')) {
      const on = next.has(row.dataset.key);
      row.classList.toggle('selected', on);
      row.querySelector('.msg-check')?.setAttribute(
        'aria-checked', on ? 'true' : 'false');
    }
    updateMultiBar();
  }

  function startMarquee(e) {
    if (!state.selectMode || e.button !== 0 || e.pointerType === 'touch') return;
    if (e.target.closest('button, a, input, textarea, .msg-check')) return;
    state.marquee = {
      startX: e.clientX,
      startY: e.clientY,
      pane: els.chatPane.getBoundingClientRect(),
      base: new Set(state.selected),
      active: false,
    };
    window.addEventListener('pointermove', onMarqueeMove);
    window.addEventListener('pointerup', endMarquee, { once: true });
    window.addEventListener('pointercancel', endMarquee);
  }

  function onMarqueeMove(e) {
    const m = state.marquee;
    if (!m) return;
    const dx = e.clientX - m.startX;
    const dy = e.clientY - m.startY;
    if (!m.active && Math.hypot(dx, dy) < 6) return;
    m.active = true;
    e.preventDefault();
    document.body.classList.add('marquee-dragging');
    const x1 = Math.min(m.startX, e.clientX);
    const x2 = Math.max(m.startX, e.clientX);
    const y1 = Math.min(m.startY, e.clientY);
    const y2 = Math.max(m.startY, e.clientY);
    const box = els.marqueeBox;
    box.classList.remove('hidden');
    box.style.left = (x1 - m.pane.left) + 'px';
    box.style.top = (y1 - m.pane.top) + 'px';
    box.style.width = (x2 - x1) + 'px';
    box.style.height = (y2 - y1) + 'px';
    const next = new Set(m.base);
    for (const row of els.msgList.querySelectorAll('.msg-row[data-key]')) {
      if (row.classList.contains('recalled')) continue;
      const r = row.getBoundingClientRect();
      if (r.bottom < y1 || r.top > y2 || r.right < x1 || r.left > x2) continue;
      next.add(row.dataset.key);
    }
    applySelection(next);
  }

  function endMarquee() {
    const m = state.marquee;
    if (!m) return;
    if (m.active) state.suppressClickUntil = Date.now() + 300;
    state.marquee = null;
    document.body.classList.remove('marquee-dragging');
    els.marqueeBox.classList.add('hidden');
    window.removeEventListener('pointermove', onMarqueeMove);
    window.removeEventListener('pointerup', endMarquee);
    window.removeEventListener('pointercancel', endMarquee);
  }

  function enterSelectMode(initialMsg = null) {
    if (state.selectMode) return;
    state.selectMode = true;
    state.selected.clear();
    els.msgList.classList.add('selecting');
    els.multiBar.classList.remove('hidden');
    els.composer.classList.add('hidden');
    if (initialMsg) toggleSelect(initialMsg);
    updateMultiBar();
    toast('点消息前面的圆圈多选');
  }

  function exitSelectMode() {
    if (!state.selectMode) return;
    endMarquee();
    state.selectMode = false;
    state.selected.clear();
    els.msgList.classList.remove('selecting');
    els.multiBar.classList.add('hidden');
    els.composer.classList.remove('hidden');
    els.msgList.querySelectorAll('.msg-row.selected').forEach((r) => {
      r.classList.remove('selected');
    });
    updateMultiBar();
  }

  function toggleSelect(msg) {
    if (!state.selectMode || !msg || msg.recalled) return;
    if (state.selected.has(msg.key)) state.selected.delete(msg.key);
    else state.selected.add(msg.key);
    const row = rowElOf(msg);
    if (row) {
      const on = state.selected.has(msg.key);
      row.classList.toggle('selected', on);
      row.querySelector('.msg-check')?.setAttribute('aria-checked', on ? 'true' : 'false');
    }
    updateMultiBar();
  }

  function selectedMsgs() {
    return state.msgs
      .filter((m) => state.selected.has(m.key) && !m.recalled)
      .sort((a, b) => a.ts - b.ts);
  }

  function updateMultiBar() {
    const n = state.selected.size;
    if (els.multiCount) els.multiCount.textContent = `已选 ${n} 条`;
    if (!els.multiBar) return;
    els.multiBar.querySelectorAll('button[data-multi]').forEach((b) => {
      if (b.dataset.multi === 'cancel') return;
      b.disabled = n === 0;
    });
  }

  function copySelected() {
    const msgs = selectedMsgs();
    if (!msgs.length) { toast('先选几条消息'); return; }
    copyText(msgs.map((m) => m.text || previewOf(m)).join('\n'));
  }

  async function recallSelected() {
    const msgs = selectedMsgs();
    if (!msgs.length) return;
    let ok = 0;
    for (const m of msgs) {
      if (await recallMessage(m, true)) ok += 1;
    }
    toast(ok ? `已撤回 ${ok} 条` : '没有可撤回的消息');
    exitSelectMode();
  }

  function forwardSegsFor(msg) {
    const segs = [];
    for (const seg of (msg.segs || [])) {
      if (!seg || typeof seg !== 'object') continue;
      if (seg.type === 'text') {
        const t = String(seg.data?.text || '');
        if (t) segs.push({ type: 'text', data: { text: t } });
      } else if (seg.type === 'image' || seg.type === 'mface' ||
                 seg.type === 'marketface') {
        const sticker = isStickerSeg(seg);
        const url = resolveAsset(imageUrlOf(seg));
        if (url && /^https?:\/\//i.test(url)) {
          segs.push({
            type: 'image',
            data: {
              file: url,
              sub_type: sticker ? 1 : 0,
              summary: sticker ? '[表情包]' : '[图片]',
            },
          });
        } else {
          segs.push({
            type: 'text',
            data: { text: sticker ? '[表情包]' : '[图片]' },
          });
        }
      }
    }
    if (!segs.length) {
      segs.push({ type: 'text', data: { text: msg.text || previewOf(msg) } });
    }
    return segs;
  }

  function mergedForwardText(msgs) {
    const lines = [`【聊天记录】与${state.bot.name}的聊天`];
    for (const m of msgs) {
      const who = m.dir === 'out' ? state.me.name : state.bot.name;
      lines.push(`${fmtClock(m.ts)} ${who}：${m.text || previewOf(m)}`);
    }
    return lines.join('\n');
  }

  function openForwardModal(mode) {
    const msgs = selectedMsgs();
    if (!msgs.length) { toast('先选几条消息'); return; }
    state.forwardMode = mode;
    els.forwardTitle.textContent = mode === 'merge' ? '合并转发到' : '逐条转发到';
    els.forwardList.innerHTML = '';
    const targets = state.characters.filter((c) => c.id !== Number(state.bot.id));
    for (const c of targets) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'forward-item';
      const av = document.createElement('div');
      av.className = 'avatar bot-avatar';
      fillAvatar(av, c.name, c.id);
      const name = document.createElement('span');
      name.textContent = c.name;
      btn.append(av, name);
      btn.addEventListener('click', () => forwardTo(c.id));
      els.forwardList.appendChild(btn);
    }
    if (!targets.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '还没有别的聊天对象，先添加一个角色吧。';
      els.forwardList.appendChild(empty);
    }
    els.forwardMask.classList.remove('hidden');
  }

  function closeForwardModal() {
    els.forwardMask.classList.add('hidden');
    state.forwardMode = '';
  }

  async function forwardTo(peerId) {
    const msgs = selectedMsgs();
    const mode = state.forwardMode;
    if (!msgs.length) { closeForwardModal(); return; }
    const target = state.characters.find((c) => c.id === Number(peerId));
    try {
      if (mode === 'merge') {
        await call('send_msg', {
          message_type: 'private',
          user_id: Number(peerId),
          message: [{ type: 'text', data: { text: mergedForwardText(msgs) } }],
        }, 25000);
      } else {
        for (const m of msgs) {
          await call('send_msg', {
            message_type: 'private',
            user_id: Number(peerId),
            message: forwardSegsFor(m),
          }, 25000);
        }
      }
      toast(`已转发 ${msgs.length} 条给 ${target?.name || '对方'}`);
      closeForwardModal();
      exitSelectMode();
    } catch (e) {
      toast('转发失败：' + (e?.message || e));
    }
  }

  els.multiBar.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-multi]');
    if (!btn) return;
    const act = btn.dataset.multi;
    if (act === 'cancel') exitSelectMode();
    else if (act === 'copy') copySelected();
    else if (act === 'recall') recallSelected();
    else if (act === 'forward-each') openForwardModal('each');
    else if (act === 'forward-merge') openForwardModal('merge');
  });

  // 多选模式下，鼠标在消息区拖出矩形即可框选
  els.msgScroll.addEventListener('pointerdown', startMarquee);

  els.forwardClose.addEventListener('click', closeForwardModal);
  els.forwardMask.addEventListener('click', (e) => {
    if (e.target === els.forwardMask) closeForwardModal();
  });

  // ---------------------------------------------------------- 更多 / 设置
  function openMoreMenu() {
    closeCtx();
    const rect = els.btnMore.getBoundingClientRect();
    els.moreMenu.classList.remove('hidden');
    const mrect = els.moreMenu.getBoundingClientRect();
    els.moreMenu.style.left = Math.max(8, Math.min(rect.right - mrect.width,
      window.innerWidth - mrect.width - 8)) + 'px';
    els.moreMenu.style.top = Math.max(8, Math.min(rect.bottom + 6,
      window.innerHeight - mrect.height - 8)) + 'px';
  }

  els.btnMore.addEventListener('click', (e) => {
    e.stopPropagation();
    openMoreMenu();
  });

  els.moreMenu.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    closeCtx();
    if (act === 'chatStyle') {
      openChatSettings();
    } else if (act === 'multiselect') {
      enterSelectMode();
    } else if (act === 'stickerManage') {
      showPanel('stickerPanel');
      setStickerManage(true);
    } else if (act === 'reconnect') {
      reconnectNow();
    } else if (act === 'clear') {
      if (!state.msgs.length) { toast('没有可清空的消息'); return; }
      if (confirm('清空本机显示？不会删除 vol 的记忆和聊天记录。')) {
        state.msgs = [];
        state.byMid.clear();
        renderAll(false);
      }
    } else if (act === 'stapxs') {
      window.open('/stapxs/', '_blank');
    }
  });

  function reconnectNow() {
    clearTimeout(state.reconnectTimer);
    if (state.ws) {
      try { state.ws.onclose = null; state.ws.close(); } catch (e) { /* ignore */ }
      state.ws = null;
    }
    state.connected = false;
    state.ready = false;
    rejectAllPending('重新连接');
    setConn('warn', '连接中…');
    connect();
  }

  function openSettings() {
    els.settingsToken.value = state.token;
    els.settingsUrl.textContent = location.host;
    els.settingsMask.classList.remove('hidden');
    loadLlmSettings();
  }

  async function loadLlmSettings() {
    try {
      const res = await apiFetch('/api/settings', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const llm = data?.llm || {};
      els.settingsBaseUrl.value = llm.base_url || '';
      els.settingsModel.value = llm.model || '';
      els.settingsApiKey.value = '';
      els.settingsApiKey.placeholder = llm.api_key_set
        ? `已配置：${llm.api_key_hint || '****'}（留空不修改）`
        : '未配置';
      els.settingsApiState.textContent = llm.api_key_set ? '已配置' : '未配置';
    } catch (e) { /* 老服务端没有这个接口 */ }
  }

  async function saveLlmSettings() {
    const llm = {
      base_url: els.settingsBaseUrl.value.trim(),
      model: els.settingsModel.value.trim(),
    };
    const key = els.settingsApiKey.value.trim();
    if (key) llm.api_key = key;
    if (!llm.base_url && !llm.model && !key) {
      toast('没有要保存的内容');
      return;
    }
    els.settingsLlmSave.disabled = true;
    try {
      const res = await apiFetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      els.settingsApiKey.value = '';
      await loadLlmSettings();
      toast('模型设置已保存');
    } catch (e) {
      toast('保存失败：' + (e?.message || e));
    } finally {
      els.settingsLlmSave.disabled = false;
    }
  }

  // ---------------------------------------------------------- 添加角色
  function openCharacterModal() {
    els.settingsMask.classList.add('hidden');
    state.pendingCharacterAvatar = '';
    els.characterName.value = '';
    els.characterPreview.innerHTML = '<span>?</span>';
    els.characterPreview.classList.remove('has-img');
    els.characterStatus.textContent = '添加后会联网搜索资料并蒸馏人设，可能需要几十秒。';
    els.characterStatus.classList.remove('busy');
    els.characterCreate.disabled = false;
    els.characterCreate.textContent = '开始蒸馏并添加';
    els.characterMask.classList.remove('hidden');
    els.characterName.focus();
  }

  function closeCharacterModal() {
    els.characterMask.classList.add('hidden');
  }

  function pickCharacterAvatar() {
    els.characterAvatarInput.value = '';
    els.characterAvatarInput.click();
  }

  function previewCharacterAvatar(file) {
    if (!file) return;
    if (!/^image\//.test(file.type || '')) { toast('请选择图片文件'); return; }
    if (file.size > 8 * 1024 * 1024) { toast('头像太大（上限 8MB）'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      state.pendingCharacterAvatar = String(reader.result || '');
      els.characterPreview.innerHTML = '';
      const img = document.createElement('img');
      img.alt = '头像预览';
      img.src = state.pendingCharacterAvatar;
      els.characterPreview.appendChild(img);
      els.characterPreview.classList.add('has-img');
    };
    reader.readAsDataURL(file);
  }

  async function createCharacter() {
    const name = els.characterName.value.trim();
    if (!name) { toast('请填写角色名'); els.characterName.focus(); return; }
    if (!state.pendingCharacterAvatar) { toast('请先选择头像'); return; }
    els.characterCreate.disabled = true;
    els.characterCreate.textContent = '正在蒸馏…';
    els.characterStatus.classList.add('busy');
    els.characterStatus.textContent = '正在联网搜索资料并蒸馏人设，请稍候（可能需要几十秒）…';
    try {
      const res = await apiFetch('/api/characters/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          avatar: state.pendingCharacterAvatar,
        }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      const ch = out.character || {};
      const cid = Number(ch.id || 0);
      if (cid && !state.characters.some((c) => c.id === cid)) {
        state.characters.push({ id: cid, name: ch.name || name });
      }
      if (cid) {
        state.charMsgs[cid] = [];
        convMetaFor(cid);
      }
      closeCharacterModal();
      await loadAvatars();
      renderConvList();
      renderContactList();
      if (cid) selectCharacter(cid);
      toast(`「${ch.name || name}」已添加`);
    } catch (e) {
      els.characterStatus.textContent = '添加失败：' + (e?.message || e);
      els.characterStatus.classList.remove('busy');
      els.characterCreate.disabled = false;
      els.characterCreate.textContent = '重试';
    }
  }

  els.railSettings.addEventListener('click', openSettings);
  els.mobileSettings.addEventListener('click', openSettings);
  els.mobileTheme.addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  els.settingsClose.addEventListener('click', () => els.settingsMask.classList.add('hidden'));
  els.settingsMask.addEventListener('click', (e) => {
    if (e.target === els.settingsMask) els.settingsMask.classList.add('hidden');
  });
  els.settingsReconnect.addEventListener('click', () => {
    els.settingsMask.classList.add('hidden');
    reconnectNow();
  });
  els.settingsStapxs.addEventListener('click', () => window.open('/stapxs/', '_blank'));
  els.settingsLlmSave.addEventListener('click', saveLlmSettings);
  els.settingsApiKey.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveLlmSettings(); }
  });
  els.settingsAddCharacter.addEventListener('click', openCharacterModal);
  els.characterClose.addEventListener('click', closeCharacterModal);
  els.characterCancel.addEventListener('click', closeCharacterModal);
  els.characterMask.addEventListener('click', (e) => {
    if (e.target === els.characterMask) closeCharacterModal();
  });
  els.characterPickAvatar.addEventListener('click', pickCharacterAvatar);
  els.characterAvatarInput.addEventListener('change', () => {
    const f = els.characterAvatarInput.files && els.characterAvatarInput.files[0];
    if (f) previewCharacterAvatar(f);
  });
  els.characterCreate.addEventListener('click', createCharacter);
  els.characterName.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); createCharacter(); }
  });

  // ---------------------------------------------------------- 更换头像（QQ 式裁剪）
  const AVATAR_PX = 256;

  function openAvatarPicker() {
    els.avatarFileInput.value = '';
    els.avatarFileInput.click();
  }

  function closeAvatarCrop() {
    els.avatarMask.classList.add('hidden');
    const c = state.avatarCrop;
    if (c && c.url) URL.revokeObjectURL(c.url);
    state.avatarCrop = null;
    els.avatarCropImg.removeAttribute('src');
    els.avatarCropImg.removeAttribute('style');
  }

  function startAvatarCrop(file) {
    if (!file) return;
    if (!/^image\//.test(file.type || '')) { toast('请选择图片文件'); return; }
    if (file.size > 12 * 1024 * 1024) { toast('图片太大（上限 12MB）'); return; }
    const old = state.avatarCrop;
    if (old && old.url) URL.revokeObjectURL(old.url);
    state.avatarCrop = null;

    const url = URL.createObjectURL(file);
    // 先显示弹窗，才能量到裁剪框的真实尺寸
    els.avatarMask.classList.remove('hidden');
    els.avatarZoom.value = '100';

    const img = new Image();
    img.onload = () => {
      const stage = els.avatarStage;
      state.avatarCrop = {
        url,
        img,
        stageW: stage.clientWidth || 280,
        stageH: stage.clientHeight || 280,
        base: 1,
        zoom: 1,
        x: 0,
        y: 0,
      };
      els.avatarCropImg.src = url;
      layoutAvatarCrop();
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      els.avatarMask.classList.add('hidden');
      toast('图片读取失败');
    };
    img.src = url;
  }

  function layoutAvatarCrop() {
    const c = state.avatarCrop;
    if (!c) return;
    const stage = els.avatarStage;
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    if (w && h) { c.stageW = w; c.stageH = h; }
    const iw = c.img.naturalWidth || 1;
    const ih = c.img.naturalHeight || 1;
    // base = 刚好铺满裁剪框的缩放；zoom 只在此基础上放大
    c.base = Math.max(c.stageW / iw, c.stageH / ih) || 1;
    const scale = c.base * c.zoom;
    const dw = iw * scale;
    const dh = ih * scale;
    const maxX = Math.max(0, (dw - c.stageW) / 2);
    const maxY = Math.max(0, (dh - c.stageH) / 2);
    c.x = Math.max(-maxX, Math.min(maxX, c.x));
    c.y = Math.max(-maxY, Math.min(maxY, c.y));
    const el = els.avatarCropImg;
    el.style.width = dw + 'px';
    el.style.height = dh + 'px';
    el.style.left = (c.stageW / 2 + c.x - dw / 2) + 'px';
    el.style.top = (c.stageH / 2 + c.y - dh / 2) + 'px';
  }

  function setAvatarZoom(z) {
    const c = state.avatarCrop;
    if (!c) return;
    c.zoom = Math.max(1, Math.min(4, z));
    els.avatarZoom.value = String(Math.round(c.zoom * 100));
    layoutAvatarCrop();
  }

  function confirmAvatarCrop() {
    const c = state.avatarCrop;
    if (!c) return;
    const scale = c.base * c.zoom;
    const dw = c.img.naturalWidth * scale;
    const left = c.stageW / 2 + c.x - dw / 2;
    const side = c.stageW / scale;
    const sx = -left / scale;
    const sy = -((c.stageH / 2 + c.y - c.img.naturalHeight * scale / 2) / scale);

    const canvas = document.createElement('canvas');
    canvas.width = AVATAR_PX;
    canvas.height = AVATAR_PX;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, AVATAR_PX, AVATAR_PX);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(c.img, sx, sy, side, side, 0, 0, AVATAR_PX, AVATAR_PX);
    saveAvatar(canvas.toDataURL('image/png'));
  }

  async function saveAvatar(dataUrl) {
    try {
      const res = await apiFetch('/api/avatar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: state.bot.id, data: dataUrl }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      state.avatars[String(state.bot.id)] = out.url ||
        `/api/avatar?peer_id=${state.bot.id}&v=${Date.now()}`;
      closeAvatarCrop();
      refreshBotAvatars();
      applyFavicon();
      toast('头像已更新');
    } catch (e) {
      toast('头像保存失败：' + (e?.message || e));
    }
  }

  async function resetAvatar() {
    if (!state.bot.id) return;
    try {
      const res = await apiFetch('/api/avatar/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: state.bot.id }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      delete state.avatars[String(state.bot.id)];
      // 新增角色会恢复成导入时的原头像；星野会回到 QQ 头像
      await loadAvatars();
      refreshBotAvatars();
      applyFavicon();
      toast('已恢复默认头像');
    } catch (e) {
      toast('恢复失败：' + (e?.message || e));
    }
  }

  els.csAvatarPick.addEventListener('click', openAvatarPicker);
  els.csAvatarPreview.addEventListener('click', openAvatarPicker);
  els.csAvatar.addEventListener('click', openAvatarPicker);
  els.csAvatar.title = '点击更换头像';
  els.csAvatarReset.addEventListener('click', resetAvatar);
  els.avatarClose.addEventListener('click', closeAvatarCrop);
  els.avatarCancel.addEventListener('click', closeAvatarCrop);
  els.avatarMask.addEventListener('click', (e) => {
    if (e.target === els.avatarMask) closeAvatarCrop();
  });
  els.avatarRepick.addEventListener('click', openAvatarPicker);
  els.avatarConfirm.addEventListener('click', confirmAvatarCrop);
  els.avatarFileInput.addEventListener('change', () => {
    const f = els.avatarFileInput.files && els.avatarFileInput.files[0];
    if (f) startAvatarCrop(f);
  });
  els.avatarZoom.addEventListener('input', () => {
    setAvatarZoom(Number(els.avatarZoom.value) / 100);
  });
  window.addEventListener('resize', () => {
    if (state.avatarCrop) layoutAvatarCrop();
  });

  // 拖动选图：QQ 里按住图片挪位置
  let cropDrag = null;
  els.avatarStage.addEventListener('pointerdown', (e) => {
    const c = state.avatarCrop;
    if (!c) return;
    e.preventDefault();
    cropDrag = { id: e.pointerId, sx: e.clientX, sy: e.clientY, ox: c.x, oy: c.y };
    els.avatarStage.classList.add('dragging');
    try { els.avatarStage.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
  });
  els.avatarStage.addEventListener('pointermove', (e) => {
    const c = state.avatarCrop;
    if (!c || !cropDrag || cropDrag.id !== e.pointerId) return;
    c.x = cropDrag.ox + (e.clientX - cropDrag.sx);
    c.y = cropDrag.oy + (e.clientY - cropDrag.sy);
    layoutAvatarCrop();
  });
  const endCropDrag = (e) => {
    if (!cropDrag || (e && cropDrag.id !== e.pointerId)) return;
    cropDrag = null;
    els.avatarStage.classList.remove('dragging');
  };
  els.avatarStage.addEventListener('pointerup', endCropDrag);
  els.avatarStage.addEventListener('pointercancel', endCropDrag);
  els.avatarStage.addEventListener('wheel', (e) => {
    if (!state.avatarCrop) return;
    e.preventDefault();
    setAvatarZoom(state.avatarCrop.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
  }, { passive: false });

  // ---------------------------------------------------------- 聊天设置（按对话）
  function openChatSettings() {
    ensureChatTheme(state.bot.id);
    state.chatSide = 'in';
    els.chatSettingsMask.classList.remove('hidden');
    renderChatSettings();
    loadTraits();
    if (!state.stickers) loadStickers();
    else if (!state.stickerSetsLoaded) loadStickerSets();
  }

  function closeChatSettings() {
    els.chatSettingsMask.classList.add('hidden');
  }

  // ---------------------------------------------------------- 关系参数
  // 与后端 traits.py 保持一致：热情影响已放大 4 倍
  const TRAIT_SESSION_POINTS = [[0, 0.32], [10, 2.00], [25, 3.76], [50, 4.92],
    [75, 6.48], [90, 8.16], [100, 16.40]];
  const TRAIT_REPLY_POINTS = [[0, 37.5], [10, 17.5], [25, 11.25], [50, 6],
    [75, 5], [90, 4], [100, 3]];

  function traitInterp(points, x) {
    const v = Math.max(points[0][0], Math.min(points[points.length - 1][0], Number(x)));
    for (let i = 1; i < points.length; i++) {
      const [x0, y0] = points[i - 1];
      const [x1, y1] = points[i];
      if (v <= x1) {
        if (x1 === x0) return y1;
        return y0 + (y1 - y0) * (v - x0) / (x1 - x0);
      }
    }
    return points[points.length - 1][1];
  }

  function updateTraitPreview() {
    const e = Number(els.csEnthusiasm.value);
    els.csEnthusiasmVal.textContent = String(e);
    els.csAffectionVal.textContent = String(els.csAffection.value);
    const sessions = traitInterp(TRAIT_SESSION_POINTS, e);
    const reply = traitInterp(TRAIT_REPLY_POINTS, e);
    els.csTraitPreview.textContent =
      `参考真实聊天：主动约 ${sessions.toFixed(1)} 次/天 · 回复约 ${Math.round(reply)} 秒`;
  }

  async function loadTraits() {
    if (!state.bot?.id) return;
    try {
      const res = await apiFetch(
        `/api/character-traits?peer_id=${encodeURIComponent(state.bot.id)}`,
        { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) return;
      els.csEnthusiasm.value = data.enthusiasm ?? 50;
      els.csAffection.value = data.affection ?? 60;
      updateTraitPreview();
    } catch (e) { updateTraitPreview(); }
  }

  async function saveTraits() {
    if (!state.bot?.id) return;
    els.csTraitSave.disabled = true;
    try {
      const res = await apiFetch('/api/character-traits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          peer_id: state.bot.id,
          enthusiasm: Number(els.csEnthusiasm.value),
          affection: Number(els.csAffection.value),
        }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      if (out.preview) els.csTraitPreview.textContent = out.preview;
      toast('关系参数已保存');
    } catch (e) {
      toast('保存失败：' + (e?.message || e));
    } finally {
      els.csTraitSave.disabled = false;
    }
  }

  function chip(label, active, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip' + (active ? ' active' : '');
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  function renderChatSettings() {
    if (!els.csStyles) return;
    const theme = editTheme();

    els.csSideSeg.querySelectorAll('button').forEach((b) => {
      b.classList.toggle('active', b.dataset.side === state.chatSide);
    });

    // 样式
    els.csStyles.innerHTML = '';
    for (const s of BUBBLE_STYLES) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'bubble-opt' + (s.id === theme.style ? ' active' : '');
      const mini = document.createElement('span');
      mini.className = 'mini mini-' + s.id;
      const label = document.createElement('span');
      label.textContent = s.name;
      b.append(mini, label);
      b.addEventListener('click', () => {
        theme.style = s.id;
        saveChatThemes();
        applyChatTheme();
        renderChatSettings();
      });
      els.csStyles.appendChild(b);
    }

    // 自定义颜色
    els.csCustom.checked = !!theme.custom;
    els.csBg1.value = theme.bg1;
    els.csBg2.value = theme.bg2;
    els.csFg.value = theme.fg;
    els.csColors.classList.toggle('disabled', !theme.custom);

    // 角标
    els.csTags.innerHTML = '';
    for (const t of TAG_PRESETS) {
      els.csTags.appendChild(chip(t || '无', theme.tag === t, () => {
        theme.tag = t;
        saveChatThemes();
        refreshBubbleDecorAll();
        renderChatSettings();
      }));
    }
    els.csTagInput.value = theme.tag;

    // 装饰
    els.csDecos.innerHTML = '';
    for (const d of DECO_PRESETS) {
      els.csDecos.appendChild(chip(d.label, theme.deco === d.v, () => {
        theme.deco = d.v;
        saveChatThemes();
        refreshBubbleDecorAll();
        renderChatSettings();
      }));
    }
    els.csDecoInput.value = theme.deco === 'none' ? '' : theme.deco;

    // 这个对话可用的表情包分类
    const groups = state.stickers || [];
    const allowedRaw = state.stickerSets[String(state.bot.id)];
    const allowed = Array.isArray(allowedRaw) ? new Set(allowedRaw) : null;
    els.csStickerGroups.innerHTML = '';
    if (!groups.length) {
      const hint = document.createElement('span');
      hint.className = 'cs-loading';
      hint.textContent = '正在加载表情包…';
      els.csStickerGroups.appendChild(hint);
      if (!state.stickers) loadStickers();
    } else {
      for (const g of groups) {
        const key = g.key || g.name;
        const label = document.createElement('label');
        label.className = 'chip-check';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.dataset.key = key;
        cb.checked = allowed ? allowed.has(key) : true;
        const span = document.createElement('span');
        span.textContent = `${g.name} (${(g.items || []).length})`;
        cb.addEventListener('change', () => {
          const keys = [...els.csStickerGroups.querySelectorAll('input[type=checkbox]')]
            .filter((x) => x.checked).map((x) => x.dataset.key);
          saveStickerSet(keys);
        });
        label.append(cb, span);
        els.csStickerGroups.appendChild(label);
      }
    }

    renderChatPreview();
  }

  async function saveStickerSet(keys) {
    state.stickerSets[String(state.bot.id)] = keys;
    if (state.stickers) {
      renderStickerTabs();
      renderStickerGrid();
    }
    try {
      const res = await apiFetch('/api/sticker-sets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: state.bot.id, groups: keys }),
      });
      if (!res.ok) toast('表情包设置保存失败');
    } catch (e) {
      toast('表情包设置保存失败：' + (e?.message || e));
    }
  }

  els.btnChatStyle.addEventListener('click', openChatSettings);
  els.settingsChatStyle.addEventListener('click', () => {
    els.settingsMask.classList.add('hidden');
    openChatSettings();
  });
  els.chatSettingsClose.addEventListener('click', closeChatSettings);
  els.chatSettingsMask.addEventListener('click', (e) => {
    if (e.target === els.chatSettingsMask) closeChatSettings();
  });
  els.csEnthusiasm.addEventListener('input', updateTraitPreview);
  els.csAffection.addEventListener('input', updateTraitPreview);
  els.csTraitSave.addEventListener('click', saveTraits);
  els.csSideSeg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-side]');
    if (!b) return;
    state.chatSide = b.dataset.side === 'out' ? 'out' : 'in';
    renderChatSettings();
  });
  els.csCustom.addEventListener('change', () => {
    const theme = editTheme();
    theme.custom = els.csCustom.checked;
    saveChatThemes();
    applyChatColors();
    renderChatSettings();
  });
  for (const [el, key] of [[els.csBg1, 'bg1'], [els.csBg2, 'bg2'], [els.csFg, 'fg']]) {
    el.addEventListener('input', () => {
      const theme = editTheme();
      theme[key] = el.value;
      saveChatThemes();
      applyChatColors();
    });
  }
  els.csResetColor.addEventListener('click', () => {
    const theme = editTheme();
    const base = state.chatSide === 'out' ? DEFAULT_OUT : DEFAULT_IN;
    theme.custom = false;
    theme.bg1 = base.bg1;
    theme.bg2 = base.bg2;
    theme.fg = base.fg;
    saveChatThemes();
    applyChatColors();
    renderChatSettings();
  });
  let csInputTimer = 0;
  function scheduleDecorSave() {
    clearTimeout(csInputTimer);
    csInputTimer = setTimeout(() => {
      saveChatThemes();
      refreshBubbleDecorAll();
    }, 120);
  }
  els.csTagInput.addEventListener('input', () => {
    editTheme().tag = els.csTagInput.value.slice(0, 12);
    scheduleDecorSave();
  });
  els.csDecoInput.addEventListener('input', () => {
    editTheme().deco = els.csDecoInput.value.slice(0, 16) || 'none';
    scheduleDecorSave();
  });

  function saveToken(value) {
    state.token = String(value || '').trim();
    if (state.token) localStorage.setItem(LS_TOKEN, state.token);
    else localStorage.removeItem(LS_TOKEN);
  }

  els.settingsTokenSave.addEventListener('click', () => {
    saveToken(els.settingsToken.value);
    els.settingsMask.classList.add('hidden');
    toast('令牌已保存，正在重新连接');
    reconnectNow();
  });

  els.tokenSave.addEventListener('click', () => {
    saveToken(els.tokenInput.value);
    els.tokenRow.classList.add('hidden');
    connect();
  });
  els.tokenInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') els.tokenSave.click();
  });

  els.connectBtn.addEventListener('click', () => {
    if (state.ws) { reconnectNow(); return; }
    connect();
  });

  // ---------------------------------------------------------- 搜索
  function toggleChatSearch(show) {
    const visible = show !== undefined ? show : els.chatSearch.classList.contains('hidden');
    els.chatSearch.classList.toggle('hidden', !visible);
    if (visible) {
      setTimeout(() => els.chatSearchInput.focus(), 30);
    } else {
      els.chatSearchInput.value = '';
      clearSearch();
    }
  }

  function clearSearch() {
    els.searchCount.textContent = '';
    els.msgList.querySelectorAll('.msg-row.hit').forEach((r) => r.classList.remove('hit'));
    state.searchHits = [];
    state.searchIdx = -1;
  }

  function runSearch() {
    const q = els.chatSearchInput.value.trim().toLowerCase();
    clearSearch();
    if (!q) return;
    state.searchHits = state.msgs.filter((m) =>
      (m.text || '').toLowerCase().includes(q) ||
      (m.segs || []).some((s) => s.type === 'text' &&
        String(s.data?.text || '').toLowerCase().includes(q)));
    els.searchCount.textContent = state.searchHits.length
      ? `${state.searchHits.length} 条` : '无结果';
    for (const m of state.searchHits) {
      const row = rowElOf(m);
      if (row) row.classList.add('hit');
    }
    if (state.searchHits.length) {
      state.searchIdx = 0;
      jumpToHit(0);
    }
  }

  function jumpToHit(index) {
    if (!state.searchHits.length) return;
    const i = ((index % state.searchHits.length) + state.searchHits.length) %
      state.searchHits.length;
    state.searchIdx = i;
    els.searchCount.textContent = `${i + 1}/${state.searchHits.length}`;
    const row = rowElOf(state.searchHits[i]);
    if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  els.btnSearchMsg.addEventListener('click', () => toggleChatSearch());
  els.searchClose.addEventListener('click', () => toggleChatSearch(false));
  let searchTimer = 0;
  els.chatSearchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 180);
  });
  els.chatSearchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (state.searchHits.length <= 1) runSearch();
      else jumpToHit(state.searchIdx + 1);
    }
  });

  // 左侧会话搜索：按角色名 / 最近一条预览过滤
  els.searchInput.addEventListener('input', () => {
    renderConvList();
  });

  // ---------------------------------------------------------- 移动端
  function openMobileChat() {
    els.appView.classList.add('mobile-chat');
    els.contactsPage.classList.add('hidden');
    els.mobileActions.classList.add('hidden');
    setMobileTab('messages');
    scrollToBottom(false);
  }

  function setMobileTab(tab) {
    state.mobileTab = tab || 'messages';
    els.mobileNav.querySelectorAll('.mn-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === state.mobileTab);
    });
  }

  function switchMobileTab(tab) {
    if (tab === 'contacts') {
      els.contactsPage.classList.remove('hidden');
      setMobileTab('contacts');
      return;
    }
    els.contactsPage.classList.add('hidden');
    if (tab === 'stickers') {
      openMobileChat();
      showPanel('stickerPanel');
      setMobileTab('stickers');
      return;
    }
    if (tab === 'me') {
      setMobileTab('me');
      openSettings();
      return;
    }
    els.appView.classList.remove('mobile-chat');
    setMobileTab('messages');
  }

  els.backBtn.addEventListener('click', () => {
    els.appView.classList.remove('mobile-chat');
    hidePanels();
    setMobileTab('messages');
  });
  els.mobileNav.addEventListener('click', (e) => {
    const b = e.target.closest('.mn-item');
    if (b) switchMobileTab(b.dataset.tab);
  });
  els.contactsBack.addEventListener('click', () => {
    els.contactsPage.classList.add('hidden');
    setMobileTab('messages');
  });
  els.contactsAdd.addEventListener('click', () => els.mobileActions.classList.remove('hidden'));

  function openMobileActions() {
    els.mobileActions.classList.remove('hidden');
  }
  els.mobilePlus.addEventListener('click', openMobileActions);
  els.mobileMoreBtn.addEventListener('click', openMobileActions);
  els.mobileActions.addEventListener('click', (e) => {
    if (e.target === els.mobileActions) {
      els.mobileActions.classList.add('hidden');
      return;
    }
    const b = e.target.closest('button[data-act]');
    if (!b) return;
    const act = b.dataset.act;
    els.mobileActions.classList.add('hidden');
    if (act === 'chatStyle') openChatSettings();
    else if (act === 'multiselect') {
      openMobileChat();
      enterSelectMode();
    } else if (act === 'stickerManage') {
      openMobileChat();
      showPanel('stickerPanel');
      setStickerManage(true);
    } else if (act === 'theme') {
      setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    } else if (act === 'settings') {
      openSettings();
    }
  });

  // ---------------------------------------------------------- 图片大图
  function openLightbox(src) {
    if (!src) return;
    els.lightboxImg.src = src;
    els.lightbox.classList.remove('hidden');
  }
  function closeLightbox() {
    els.lightbox.classList.add('hidden');
    els.lightboxImg.removeAttribute('src');
  }
  els.lightbox.addEventListener('click', closeLightbox);

  // ---------------------------------------------------------- 全局点击 / 快捷键
  document.addEventListener('pointerdown', (e) => {
    if (!els.ctxMenu.classList.contains('hidden') && !els.ctxMenu.contains(e.target)) {
      els.ctxMenu.classList.add('hidden');
    }
    if (!els.moreMenu.classList.contains('hidden') && !els.moreMenu.contains(e.target) &&
        !els.btnMore.contains(e.target)) {
      els.moreMenu.classList.add('hidden');
    }
    if (!els.emojiPanel.classList.contains('hidden') &&
        !els.emojiPanel.contains(e.target) && !els.emojiBtn.contains(e.target)) {
      els.emojiPanel.classList.add('hidden');
      els.emojiBtn.classList.remove('active');
    }
    if (!els.stickerPanel.classList.contains('hidden') &&
        !els.stickerPanel.contains(e.target) && !els.stickerBtn.contains(e.target) &&
        !els.railSticker.contains(e.target)) {
      els.stickerPanel.classList.add('hidden');
      els.stickerBtn.classList.remove('active');
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!els.lightbox.classList.contains('hidden')) { closeLightbox(); return; }
      if (!els.forwardMask.classList.contains('hidden')) { closeForwardModal(); return; }
      if (!els.categoryMask.classList.contains('hidden')) {
        closeCategoryModal(); return;
      }
      if (!els.chatSettingsMask.classList.contains('hidden')) {
        closeChatSettings(); return;
      }
      if (!els.settingsMask.classList.contains('hidden')) {
        els.settingsMask.classList.add('hidden'); return;
      }
      if (!els.mobileActions.classList.contains('hidden')) {
        els.mobileActions.classList.add('hidden'); return;
      }
      if (!els.contactsPage.classList.contains('hidden')) {
        els.contactsPage.classList.add('hidden');
        setMobileTab('messages');
        return;
      }
      if (!els.ctxMenu.classList.contains('hidden') || !els.moreMenu.classList.contains('hidden')) {
        closeCtx(); return;
      }
      if (!els.emojiPanel.classList.contains('hidden') ||
          !els.stickerPanel.classList.contains('hidden')) {
        hidePanels(); return;
      }
      if (state.selectMode) { exitSelectMode(); return; }
      if (!els.chatSearch.classList.contains('hidden')) toggleChatSearch(false);
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      toggleChatSearch(true);
    }
  });

  function viewingChat() {
    return !window.matchMedia('(max-width: 880px)').matches ||
      els.appView.classList.contains('mobile-chat');
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      if (viewingChat()) clearUnread();
      if (!state.connected) connect();
    }
  });
  window.addEventListener('focus', () => {
    if (viewingChat()) clearUnread();
  });

  // 心跳外的兜底：服务端每 25s 推一次 heartbeat，75s 没有任何帧就重连
  setInterval(() => {
    if (!state.ws || state.ws.readyState !== 1) return;
    if (Date.now() - state.lastFrame > 75000) {
      try { state.ws.close(); } catch (e) { /* ignore */ }
      return;
    }
    call('get_status', {}, 8000).catch(() => {});
  }, 30000);

  // ---------------------------------------------------------- 启动
  function init() {
    const qTheme = new URLSearchParams(location.search).get('theme');
    setTheme(qTheme || localStorage.getItem(LS_THEME) || 'light');
    applyChatTheme();
    if (state.token) localStorage.setItem(LS_TOKEN, state.token);
    renderEmoji();
    setConn('warn', '连接中…');
    updateBadges();
    autosize();
    updateSendBtn();
    els.tokenInput.value = state.token;
    if (state.token) els.tokenRow.classList.remove('hidden');
    connect();
  }

  init();
})();
