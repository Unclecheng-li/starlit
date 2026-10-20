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
    connectBg: $('#connectBg'),
    connectBgPick: $('#connectBgPick'),
    connectBgInput: $('#connectBgInput'),
    brandAvatar: $('#brandAvatar'),
    railAvatar: $('#railAvatar'),
    railDot: $('#railDot'),
    railTheme: $('#railTheme'),
    railSticker: $('#railSticker'),
    railSettings: $('#railSettings'),
    mobileTheme: $('#mobileTheme'),
    mobileSettings: $('#mobileSettings'),

    meName: $('#meName'),
    presenceChip: $('#presenceChip'),
    presenceChipText: $('#presenceChipText'),
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
    mobileDot: $('#mobileDot'),
    mobilePresence: $('#mobilePresence'),
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
    presenceMenu: $('#presenceMenu'),
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
    csSubTitle: $('#csSubTitle'),
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

    // ---- 群聊 ----
    chatMain: $('#chatMain'),
    chatAvatar: $('#chatAvatar'),
    btnGroupSet: $('#btnGroupSet'),
    btnGroupAt: $('#btnGroupAt'),
    groupSide: $('#groupSide'),
    gsAvatar: $('#gsAvatar'),
    gsName: $('#gsName'),
    gsCount: $('#gsCount'),
    gsClose: $('#gsClose'),
    gsRequestCard: $('#gsRequestCard'),
    gsRequestCount: $('#gsRequestCount'),
    gsRequests: $('#gsRequests'),
    gsAnnounce: $('#gsAnnounce'),
    gsAnnounceEdit: $('#gsAnnounceEdit'),
    gsMemberCount: $('#gsMemberCount'),
    gsInvite: $('#gsInvite'),
    gsMemberSearch: $('#gsMemberSearch'),
    gsMembers: $('#gsMembers'),
    memberMenu: $('#memberMenu'),
    mactAdminText: $('#mactAdminText'),
    mactKickText: $('#mactKickText'),
    createGroupMask: $('#createGroupMask'),
    cgName: $('#cgName'),
    cgMembers: $('#cgMembers'),
    cgCancel: $('#cgCancel'),
    cgCreate: $('#cgCreate'),
    cgClose: $('#cgClose'),
    inviteMask: $('#inviteMask'),
    inviteMembers: $('#inviteMembers'),
    inviteDone: $('#inviteDone'),
    inviteClose: $('#inviteClose'),
    groupSetMask: $('#groupSetMask'),
    gsSetName: $('#gsSetName'),
    gsSetSaveName: $('#gsSetSaveName'),
    gsSetMute: $('#gsSetMute'),
    gsSetSearch: $('#gsSetSearch'),
    gsSetAvatar: $('#gsSetAvatar'),
    gsSetAvatarPreview: $('#gsSetAvatarPreview'),
    gsLimits: $('#gsLimits'),
    gsSetGid: $('#gsSetGid'),
    gsSetClose: $('#gsSetClose'),
    announceMask: $('#announceMask'),
    announceInput: $('#announceInput'),
    announceCancel: $('#announceCancel'),
    announceSave: $('#announceSave'),
    announceClose: $('#announceClose'),
    groupAvatarInput: $('#groupAvatarInput'),
    gsFileTabs: $('#gsFileTabs'),
    gsFiles: $('#gsFiles'),
    gsUpload: $('#gsUpload'),
    gsFileCount: $('#gsFileCount'),
    gsFileInput: $('#gsFileInput'),
    quoteBar: $('#quoteBar'),
    qbName: $('#qbName'),
    qbText: $('#qbText'),
    qbClose: $('#qbClose'),
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
    presence: null,
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

    // ---- 群聊 ----
    // 当前会话身份：private（私聊某个角色）/ group（某个自建群）。
    // 「会话键」统一成字符串：私聊 = 角色 id，群聊 = "g"+群号 —— 两套
    // id 空间互不重叠，convMeta / 已读 / 聊天气泡主题都能按同一个键索引。
    peer: { type: 'private', id: 0, name: '星野' },
    groups: [],                 // 群概览列表（/api/groups）
    groupMsgs: {},              // gid(str) -> 消息数组（非当前会话的缓存）
    groupDetail: {},            // gid(str) -> 完整详情（成员/公告/禁言）
    groupMenuFor: '',           // 成员行操作菜单当前指向的成员 id
    memberMenuFor: null,        // 成员行操作菜单当前指向的成员对象
    joinRequests: [],           // 待审的入群申请（全局，群行红点用）
    pendingMentions: [],        // 本次输入里 @ 了谁（发送时转成 at 段）
    replyTo: null,              // 正在引用回复的消息（群里用）
    groupFiles: {},             // gid(str) -> 群文件列表
    groupFileTab: 'file',       // 群文件面板的页签：file / album
    avatarTarget: null,         // 当前裁剪的是谁的头像（peer / group）
  };

  const nowSec = () => Math.floor(Date.now() / 1000);

  // ---------------------------------------------------------- 会话键
  // 私聊键 = String(角色 id)；群聊键 = "g" + 群号。所有按会话索引的表
  // （convMeta / lastRead / 气泡主题 / 消息缓存）都用同一个键。
  const isGroup = () => state.peer.type === 'group';
  const groupKey = (gid) => 'g' + String(gid);
  function curConvKey() {
    return isGroup() ? groupKey(state.peer.id) : String(state.bot.id);
  }
  // 气泡主题也按会话键索引（私聊按角色；群里共用一套默认主题）
  const themeKey = () => curConvKey();
  // 取某个会话的消息数组（当前会话 = state.msgs），必要时惰性创建
  function listFor(key) {
    const k = String(key);
    if (k === curConvKey()) return state.msgs;
    if (k.charAt(0) === 'g') {
      const gid = k.slice(1);
      return state.groupMsgs[gid] || (state.groupMsgs[gid] = []);
    }
    return state.charMsgs[k] || (state.charMsgs[k] = []);
  }
  function groupById(gid) {
    const g = String(gid);
    return state.groups.find((x) => String(x.group_id) === g) || null;
  }
  function groupKnown(gid) {
    const g = String(gid);
    return !!groupById(g) || !!state.groupDetail[g];
  }
  // 群头像：优先用自建群上传的头像（/api/avatars 里键是 "g"+群号），
  // 否则退回首字文字头像（群里没有 QQ 号可用），保持和好友头像同一尺寸。
  function fillGroupAvatar(el, name, gid) {
    if (!el) return;
    const key = 'g' + String(gid);
    el.textContent = '';
    el.classList.remove('has-img');
    const span = document.createElement('span');
    span.textContent = firstChar(name || '群');
    el.appendChild(span);
    const custom = state.avatars[key];
    if (!custom) return;
    const img = document.createElement('img');
    img.alt = name || '群';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('load', () => el.classList.add('has-img'));
    img.addEventListener('error', () => img.remove());
    img.src = resolveAsset(custom);
    el.appendChild(img);
  }
  function groupName(gid) {
    const d = state.groupDetail[String(gid)];
    if (d && d.group_name) return d.group_name;
    const g = groupById(gid);
    return (g && g.group_name) || '群聊';
  }
  // 当前会话的显示名（群名 / 角色名）
  function curPeerName() {
    return isGroup() ? groupName(state.peer.id) : state.bot.name;
  }
  function isOwner(uid) {
    return String(uid || '') === String(state.me.id || '');
  }
  // 消息发送者（群消息用；私聊回落到当前角色）
  function senderOf(ev) {
    const s = ev.sender || {};
    return {
      id: String(s.user_id || ev.user_id || ''),
      name: String(s.nickname || s.card || '').trim() || '成员',
      role: String(s.role || 'member'),
      title: String(s.title || ''),
      level: Number(s.level || 1),
    };
  }

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
    // 在线状态点是 railAvatar 的常驻子元素，不能被重画头像清掉
    const dot = el.querySelector('.presence-dot');
    el.textContent = '';
    el.classList.remove('has-img');
    const span = document.createElement('span');
    span.textContent = fallback || firstChar(name);
    el.appendChild(span);
    const keepDot = () => { if (dot && !el.contains(dot)) el.appendChild(dot); };
    if (!uin) { keepDot(); return; }

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
    keepDot();
  }

  // 头像换好后，把当前会话里的「角色头像」重画。
  // ★ 群聊里每条消息的发送者各不相同 —— 拿 state.bot 去重画会把所有群成员
  //   都画成同一个头像（实测 bug），所以群里直接按消息重建整屏。
  function refreshBotAvatars() {
    // ★ 群模式放在 state.bot.id 检查之前：群聊里 state.bot 可能还没/已经
    //   指向别的私聊角色，用它当闸门会把「刷新进页面时群头像没加载出来」
    //   这个 bug 重新引回来（群渲染本就不依赖 state.bot）。
    if (isGroup()) {
      // ★ 群模式下：整屏消息要重画，右侧面板 + 聊天头部的群头像也要重画。
      //   只调 renderAll 的话，刷新进页面时 chatAvatar 会停在文字兜底上，
      //   必须等切走再切回来才变正常（实测 bug）—— 因为 state.avatars 是
      //   异步才加载好的，而这里没通知头部。
      renderAll(false);
      renderGroupSide();
      renderConvList();
      renderContactList();
      return;
    }
    if (!state.bot.id) return;
    document.querySelectorAll('#msgList .msg-row.in .avatar.bot-avatar')
      .forEach((el) => {
        fillAvatar(el, state.bot.name, state.bot.id);
      });
    fillAvatar(els.emptyAvatar, state.bot.name, state.bot.id);
    applyChatSettingsIdentity();
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
    return chatThemeFor(themeKey(), state.chatSide);
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
    setSideColorVars('in', chatThemeFor(themeKey(), 'in'));
    setSideColorVars('out', chatThemeFor(themeKey(), 'out'));
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
      applyBubbleDecor(bubble, chatThemeFor(themeKey(), side));
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
        applyBubbleDecor(bubble, chatThemeFor(themeKey(), dir));
        row.classList.toggle('has-tag', !!bubble.querySelector('.bubble-tag'));
      });
    }
    renderChatPreview();
  }

  function applyChatTheme() {
    const ti = chatThemeFor(themeKey(), 'in');
    const to = chatThemeFor(themeKey(), 'out');
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
    // 群会话的副标题由群状态（人数/禁言）决定，不被连接文案覆盖
    if (!isGroup()) {
      els.chatSub.textContent = kind === 'ok' ? '在线 · 本地直连' : text;
    }
    els.input.placeholder = kind === 'ok'
      ? `和${curPeerName()}说点什么…`
      : '连接断开，正在重连…';
    if (els.mobileStatus) {
      if (state.presence) {
        // 已经拿到在线状态 → 用状态标签，连接状态交给别处显示
        applyPresenceUI();
      } else {
        els.mobileStatus.textContent = kind === 'ok' ? '在线' : text;
        const line = els.mobileStatus.closest('.mh-status');
        if (line) line.classList.toggle('ok', kind === 'ok');
      }
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

        // 群列表（自建群走 HTTP；拿到后才有群会话可切）
        await loadGroups();
        restorePeer();
        applyIdentity();
        applyChatTheme();
        renderConvList();
        renderContactList();
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
    fillAvatar(els.railAvatar, state.me.name, state.me.id, '我');
    fillAvatar(els.mobileAvatar, state.me.name, state.me.id, '我');
    els.mobileName.textContent = state.me.name;
    applyChatSettingsIdentity();
    applyFavicon();
    applyPeerIdentity();
    loadAvatars();
    loadStickerSets();
    loadPresence();
    if (state.token) {
      els.settingsToken.value = state.token;
      els.tokenInput.value = state.token;
    }
  }

  // 「聊天设置」弹窗代表的是**当前私聊角色**。这几行以前只写在 applyIdentity()
  // 里，而它只在连接握手时跑一次 —— 于是切换会话后弹窗一直显示同一个人
  // （实测 bug：每个人的聊天设置都长一样）。现在它跟着每次切会话一起刷新。
  function applyChatSettingsIdentity() {
    const name = state.bot.name;
    fillAvatar(els.csAvatar, name, state.bot.id);
    // ★ 弹窗顶部那颗「聊天对象头像」预览也必须跟着走 —— 以前漏了它，
    //   所以不管切到谁，预览里永远是默认的那个字。
    fillAvatar(els.csAvatarPreview, name, state.bot.id);
    fillAvatar(els.csPreviewInAvatar, name, state.bot.id);
    fillAvatar(els.csPreviewOutAvatar, state.me.name, state.me.id, '我');
    els.csTitle.textContent = name;
    if (els.csSubTitle) {
      els.csSubTitle.textContent = `头像 / 气泡 · 只对「${name}」生效`;
    }
    if (els.csAvatar) els.csAvatar.title = `点击更换「${name}」的头像`;
    if (els.csAvatarPreview) els.csAvatarPreview.title = `点击更换「${name}」的头像`;
  }

  // 当前会话（私聊 / 群聊）的身份：标题 / 头像 / 副标题 / 输入框提示 / 文档标题。
  // 私聊专属的入口（聊天设置、表情包管理）在群里隐藏，群专属入口（群设置、
  // @全体、右侧面板）在私聊里隐藏。
  function applyPeerIdentity() {
    const g = isGroup();
    // ★ 聊天设置弹窗的内容跟着当前私聊角色走（群里虽然打不开它，但切回私聊时
    //   必须是那个人的信息）
    applyChatSettingsIdentity();
    els.chatName.textContent = curPeerName();
    if (els.chatAvatar) {
      els.chatAvatar.classList.toggle('hidden', !g);
      if (g) fillGroupAvatar(els.chatAvatar, curPeerName(), state.peer.id);
    }
    if (g) {
      const d = state.groupDetail[String(state.peer.id)];
      const n = d ? (d.member_count || (d.members || []).length)
                  : ((groupById(state.peer.id) || {}).member_count || 0);
      const muted = d ? !!d.mute_all : !!((groupById(state.peer.id) || {}).mute_all);
      els.chatSub.textContent = (muted ? '全员禁言中 · ' : '') + `${n} 人`;
    } else {
      els.chatSub.textContent = state.connected ? '在线 · 本地直连' : '连接中…';
      fillAvatar(els.emptyAvatar, state.bot.name, state.bot.id);
      const emptyText = els.emptyState.querySelector('p');
      if (emptyText) emptyText.textContent = `和${state.bot.name}打个招呼吧`;
    }
    els.input.placeholder = state.connected
      ? `和${curPeerName()}说点什么…` : '连接断开，正在重连…';
    updateDocTitle();
    if (els.btnChatStyle) els.btnChatStyle.classList.toggle('hidden', g);
    if (els.btnGroupSet) els.btnGroupSet.classList.toggle('hidden', !g);
    if (els.btnGroupAt) els.btnGroupAt.classList.toggle('hidden', !g);
    if (els.groupSide) {
      els.groupSide.classList.toggle('hidden', !g || !!state.groupSideHidden);
    }
    renderGroupSide();
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
    const n = curPeerName();
    document.title = state.unread
      ? `(${state.unread}) ${n} · vol`
      : `${n} · vol`;
  }

  function saveLastRead() {
    try { localStorage.setItem('vol.lastRead', JSON.stringify(state.lastRead)); }
    catch (e) { /* 隐身模式写不了，忽略 */ }
  }

  function syncReadState(peerId, ts) {
    if (!state.ws || state.ws.readyState !== 1) return;
    const key = String(peerId);
    // 群聊的已读只存在本机（服务端 set_msg_read 没有群的语义）
    if (key.charAt(0) === 'g') return;
    const now = nowSec();
    if (now - Number(state.lastReadSent[key] || 0) < 5) return;
    state.lastReadSent[key] = now;
    call('set_msg_read', {
      user_id: Number(peerId),
      time: Math.floor(ts || now),
    }, 8000).catch(() => { /* 老服务端没有这个 action 也不影响 */ });
  }

  function markRead(peerId = curConvKey(), ts = 0) {
    const key = String(peerId);
    const prev = Number(state.lastRead[key] || 0);
    const next = Math.max(prev, Number(ts || nowSec()));
    if (next !== prev) {
      state.lastRead[key] = next;
      saveLastRead();
    }
    syncReadState(peerId, next);
  }

  function recomputeUnread(peerId = curConvKey()) {
    const key = String(peerId);
    const list = key === curConvKey() ? state.msgs : listFor(key);
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
    const cur = curConvKey();
    // QQ 式排序：最近说过话的排最上面；没有聊天记录的沉底。
    // 私聊和群聊在同一个列表里合并排序（像 QQ 的消息页）。
    const items = [];
    let order = 0;
    for (const c of state.characters) {
      const key = String(c.id);
      const meta = convMetaFor(key);
      const cache = key === cur ? state.msgs : (state.charMsgs[key] || []);
      const last = cache.length ? cache[cache.length - 1] : null;
      const preview = meta.preview ||
        (last ? ((last.dir === 'out' ? '我：' : '') + previewOf(last))
              : '还没有聊天，打个招呼吧');
      const ts = meta.ts || (last ? last.ts : 0);
      items.push({ kind: 'private', id: c.id, key, name: c.name,
                   meta, preview, ts, order: order++ });
    }
    for (const g of state.groups) {
      const gid = String(g.group_id);
      const key = groupKey(gid);
      const meta = convMetaFor(key);
      const cache = key === cur ? state.msgs : (state.groupMsgs[gid] || []);
      const last = cache.length ? cache[cache.length - 1] : null;
      let preview = meta.preview;
      if (!preview && last) {
        const who = last.dir === 'out' ? '我：'
          : (last.sender ? last.sender.name + '：' : '');
        preview = who + previewOf(last);
      }
      const ts = meta.ts || (last ? last.ts : 0);
      items.push({ kind: 'group', id: gid, key, name: g.group_name || '群聊',
                   meta, preview, ts, order: order++,
                   pending: Number(g.pending || 0), muteAll: !!g.mute_all });
    }
    items.sort((a, b) => (b.ts - a.ts) || (a.order - b.order));

    for (const it of items) {
      if (q && !(it.name.includes(q) || (it.preview || '').includes(q))) continue;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'conv' + (it.key === cur ? ' active' : '');
      btn.dataset.peer = it.key;

      const av = document.createElement('div');
      av.className = 'avatar ' + (it.kind === 'group' ? 'group-avatar' : 'bot-avatar');
      if (it.kind === 'group') fillGroupAvatar(av, it.name, it.id);
      else fillAvatar(av, it.name, it.id);

      const main = document.createElement('div');
      main.className = 'conv-main';
      const top = document.createElement('div');
      top.className = 'conv-top';
      const nm = document.createElement('span');
      nm.className = 'conv-name';
      nm.textContent = it.name;
      if (it.kind === 'group') {
        const tag = document.createElement('span');
        tag.className = 'conv-tag';
        tag.textContent = '群';
        nm.appendChild(tag);
      }
      const tm = document.createElement('span');
      tm.className = 'conv-time';
      tm.textContent = fmtConvTime(it.ts);
      top.append(nm, tm);

      const bottom = document.createElement('div');
      bottom.className = 'conv-bottom';
      const pv = document.createElement('span');
      pv.className = 'conv-preview';
      pv.textContent = it.preview || (it.kind === 'group' ? '群里还很安静' : '');
      bottom.appendChild(pv);
      if (it.meta.unread > 0) {
        const bd = document.createElement('span');
        bd.className = 'badge';
        bd.textContent = it.meta.unread > 99 ? '99+' : String(it.meta.unread);
        bottom.appendChild(bd);
      } else if (it.pending > 0) {
        // 有待审的入群申请：群行挂红点数字（点进去就能审批）
        const bd = document.createElement('span');
        bd.className = 'conv-pending';
        bd.title = '有入群申请待处理';
        bd.textContent = String(it.pending);
        bottom.appendChild(bd);
      }
      main.append(top, bottom);
      btn.append(av, main);
      btn.addEventListener('click', () => {
        selectPeer(it.kind, it.id);
        if (window.matchMedia('(max-width: 880px)').matches) openMobileChat();
      });
      els.convList.appendChild(btn);
    }
  }

  function renderContactList() {
    if (!els.contactList) return;
    els.contactList.innerHTML = '';
    const addRow = (kind, id, name, sub) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mp-contact';
      const av = document.createElement('div');
      av.className = 'avatar ' + (kind === 'group' ? 'group-avatar' : 'bot-avatar');
      if (kind === 'group') fillGroupAvatar(av, name, id);
      else fillAvatar(av, name, id);
      const main = document.createElement('div');
      main.className = 'mp-contact-main';
      const strong = document.createElement('strong');
      strong.textContent = name;
      const span = document.createElement('span');
      span.textContent = sub;
      main.append(strong, span);
      const chev = document.createElement('svg');
      chev.setAttribute('class', 'chev');
      chev.innerHTML = '<use href="#i-back"/>';
      btn.append(av, main, chev);
      btn.addEventListener('click', () => {
        selectPeer(kind, id);
        openMobileChat();
      });
      els.contactList.appendChild(btn);
    };
    for (const g of state.groups) {
      addRow('group', g.group_id, g.group_name || '群聊',
             `${Number(g.member_count || 0)} 人 · 点这里进群`);
    }
    for (const c of state.characters) {
      addRow('private', c.id, c.name, '点这里开始聊天');
    }
    if (!state.groups.length && !state.characters.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '还没有好友，先在设置里添加一个吧。';
      els.contactList.appendChild(empty);
    }
  }

  // ---------------------------------------------------------- 群聊数据层
  // 群列表 / 详情 / 管理走 HTTP（/api/groups*），群消息走 OneBot WS。
  // 用 HTTP 是因为建群、审批、改名这些动作没有对应的 OneBot action，
  // 而消息历史两条路都通，走 WS 能跟实时事件共用一套渲染。

  async function loadGroups() {
    try {
      const res = await apiFetch('/api/groups', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || data.ok === false) return;
      state.groups = Array.isArray(data.groups) ? data.groups : [];
      state.joinRequests = Array.isArray(data.requests) ? data.requests : [];
    } catch (e) { /* 老服务端没有群接口，静默 */ }
  }

  function syncGroupSummary(d) {
    if (!d || !d.group_id) return;
    const g = groupById(d.group_id);
    const pend = (d.pending || d.pending_requests || []).length;
    if (g) {
      g.group_name = d.group_name || g.group_name;
      g.member_count = d.member_count || g.member_count;
      g.mute_all = !!d.mute_all;
      g.searchable = !!d.searchable;
      g.announce = (d.announce || {}).text || '';
      g.pending = pend;
    }
  }

  // 群资料（成员/公告/参数）节流刷新：系统消息一来就刷，但别刷爆接口
  const groupDetailRefreshedAt = {};
  function refreshGroupDetailSoon(gid) {
    const g = String(gid || '');
    if (!g) return;
    const now = Date.now();
    if (now - Number(groupDetailRefreshedAt[g] || 0) < 3000) return;
    groupDetailRefreshedAt[g] = now;
    loadGroupDetail(g);
    loadGroupFiles(g);
  }

  // 群成员的「等级 / 角色 / 群名片」是动态的（说得多就升级）。气泡上的徽章
  // 是**当刻快照**，之后有人又说几句，聊天里的旧徽章就和右侧成员列表对不上
  // 了（用户实测 bug）。这里以成员表为唯一真源，把该群所有缓存消息的发送者
  // 徽章刷一遍；当前会话变了就重画。
  function syncGroupMemberMeta(gid) {
    const g = String(gid || '');
    const d = state.groupDetail[g];
    if (!d || !(d.members || []).length) return;
    const byUid = {};
    for (const m of d.members) byUid[String(m.user_id)] = m;
    const lists = [];
    if (state.groupMsgs[g]) lists.push(state.groupMsgs[g]);
    if (curConvKey() === 'g' + g && state.msgs !== state.groupMsgs[g]) {
      lists.push(state.msgs);
    }
    let changed = false;
    for (const list of lists) {
      for (const msg of list) {
        if (!msg || !msg.sender) continue;
        const m = byUid[String(msg.sender.id)];
        if (!m) continue;
        const lv = Number(m.level || 1);
        if (Number(msg.sender.level || 0) !== lv) { msg.sender.level = lv; changed = true; }
        const role = String(m.role || 'member');
        if (String(msg.sender.role || '') !== role) { msg.sender.role = role; changed = true; }
        const nm = String(m.nickname || '');
        if (nm && msg.sender.name !== nm) { msg.sender.name = nm; changed = true; }
      }
    }
    if (changed && isGroup() && String(state.peer.id) === g) renderAll(false);
  }

  // 我（群主）在这个群里的等级。以前本机刚发出去的气泡写死 level:0（=不显示
  // 徽章），一刷新又变成 LV1，和右侧成员列表里的「群主 LV_x」对不上。
  function myGroupLevel() {
    const d = curGroupDetail();
    const m = ((d && d.members) || []).find((x) => x.is_me
      || String(x.user_id) === String(state.me.id));
    return Number((m && m.level) || 1);
  }

  async function loadGroupDetail(gid, opts = {}) {
    const g = String(gid || '');
    if (!g) return null;
    try {
      const res = await apiFetch(
        `/api/groups/detail?group_id=${encodeURIComponent(g)}`,
        { cache: 'no-store' });
      if (!res.ok) return null;
      const data = await res.json();
      if (!data || data.ok === false) return null;
      state.groupDetail[g] = data;
      syncGroupSummary(data);
      syncGroupMemberMeta(g);
      if (opts.render !== false) {
        renderConvList();
        if (isGroup() && String(state.peer.id) === g) renderGroupSide();
      }
      return data;
    } catch (e) { return null; }
  }

  async function groupManage(op, body = {}) {
    const res = await apiFetch('/api/groups/manage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op, ...body }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data || data.ok === false) {
      throw new Error((data && data.error) || '操作失败');
    }
    if (data.group_id) {
      state.groupDetail[String(data.group_id)] = data;
      syncGroupSummary(data);
      syncGroupMemberMeta(data.group_id);
      renderConvList();
      if (isGroup() && String(state.peer.id) === String(data.group_id)) {
        renderGroupSide();
      }
    }
    return data;
  }

  function restorePeer() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('vol.peer') || 'null'); }
    catch (e) { saved = null; }
    if (saved && saved.type === 'group' && groupById(saved.id)) {
      return setActivePeer('group', saved.id);
    }
    const savedId = Number(localStorage.getItem('vol.currentPeer') || 0);
    const char = state.characters.find((c) => c.id === savedId) ||
      (saved && saved.type === 'private'
        ? state.characters.find((c) => c.id === Number(saved.id)) : null) ||
      state.characters[0];
    if (char) return setActivePeer('private', char.id);
    if (state.groups.length) return setActivePeer('group', state.groups[0].group_id);
    return false;
  }

  // 只切「当前会话」，不拉历史、不重画（连接握手时用）
  function setActivePeer(type, id) {
    // ★ 先把「当前会话」的消息数组存回它**自己的**缓存，而且必须在分支之前
    //   按会话键存。以前的私聊分支用 state.bot.id 决定存哪 —— 而从群切回私聊时
    //   state.msgs 里装的是**群的消息**，state.bot 还停在上一个私聊角色，于是
    //   群消息被写进了那个角色的私聊缓存：之后点开她，看到的就是群聊的界面。
    const prev = curConvKey();
    if (prev && prev !== '0') {
      if (prev.charAt(0) === 'g') state.groupMsgs[prev.slice(1)] = state.msgs;
      else state.charMsgs[prev] = state.msgs;
    }

    if (type === 'group') {
      const gid = String(id);
      if (!groupById(gid) && !state.groupDetail[gid]) return false;
      state.peer = { type: 'group', id: gid, name: groupName(gid) };
      state.msgs = state.groupMsgs[gid] || (state.groupMsgs[gid] = []);
    } else {
      const cid = Number(id);
      const char = state.characters.find((c) => c.id === cid);
      if (!char) return false;
      state.bot = char;
      state.peer = { type: 'private', id: char.id, name: char.name };
      state.msgs = state.charMsgs[char.id] || (state.charMsgs[char.id] = []);
    }
    state.lastTs = 0;
    state.pendingMentions = [];
    state.replyTo = null;
    state.groupSideHidden = false;
    rebuildMidIndex();
    try {
      localStorage.setItem('vol.peer',
        JSON.stringify({ type: state.peer.type, id: state.peer.id }));
    } catch (e) { /* ignore */ }
    if (state.peer.type === 'private') {
      localStorage.setItem('vol.currentPeer', String(state.peer.id));
    }
    return true;
  }

  // 完整的会话切换：切数据 + 清红点 + 重画 + 按需拉历史
  function selectPeer(type, id) {
    if (state.selectMode) exitSelectMode();
    const isGroupTarget = type === 'group';
    if (!setActivePeer(type, id)) return;
    if (els.searchInput) els.searchInput.value = '';
    const key = curConvKey();
    clearUnread(key);
    applyPeerIdentity();
    applyChatTheme();
    renderConvList();
    renderAll(false);
    if (isGroupTarget) loadGroupDetail(state.peer.id);
    if (isGroupTarget) loadGroupFiles(state.peer.id);
    renderQuoteBar();
    if (!state.loaded[key]) {
      state.loaded[key] = true;
      loadHistoryFor(key);
    } else {
      scrollToBottom(false);
    }
  }

  // 兼容旧调用点（全部走泛化后的 selectPeer）
  function selectCharacter(cid) {
    selectPeer('private', cid);
  }

  async function loadHistoryFor(key) {
    const k = String(key);
    if (k.charAt(0) === 'g') {
      const gid = k.slice(1);
      let rows = [];
      try {
        const h = await call('get_group_msg_history',
          { group_id: gid, count: 80 }, 20000);
        rows = h?.data?.messages || [];
      } catch (e) { /* 历史失败不阻塞聊天 */ }
      if (curConvKey() !== k) return;
      mergeHistory(rows, k);
      return;
    }
    let history = [];
    try {
      const hist = await call('get_friend_msg_history',
        { user_id: Number(k), count: 80 }, 20000);
      history = hist?.data?.messages || [];
    } catch (e) { /* 历史失败不阻塞聊天 */ }
    if (curConvKey() !== k) return;
    mergeHistory(history, k);
  }

  async function syncAllConversations() {
    const cur = curConvKey();
    const jobs = [];
    for (const c of state.characters) {
      const key = String(c.id);
      jobs.push((async () => {
        try {
          const hist = await call('get_friend_msg_history',
            { user_id: c.id, count: key === cur ? 80 : 40 }, 20000);
          mergeHistory(hist?.data?.messages || [], key, { scroll: false });
          state.loaded[key] = true;
        } catch (e) { /* 单个会话失败不影响其他会话 */ }
      })());
    }
    for (const g of state.groups) {
      const key = groupKey(g.group_id);
      jobs.push((async () => {
        try {
          const hist = await call('get_group_msg_history',
            { group_id: g.group_id, count: key === cur ? 80 : 40 }, 20000);
          mergeHistory(hist?.data?.messages || [], key, { scroll: false });
          state.loaded[key] = true;
        } catch (e) { /* 单个会话失败不影响其他会话 */ }
      })());
    }
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
      if (ev.message_type === 'group' || ev.group_id) {
        handleGroupIncoming(ev, isReplay);
      } else if (ev.message_type && ev.message_type !== 'private') {
        return;
      } else {
        handleIncoming(ev, isReplay);
      }
    } else if (ev.post_type === 'message_sent') {
      if (ev.message_type === 'group' || ev.group_id) handleGroupSent(ev, isReplay);
      else handleSent(ev);
    } else if (ev.post_type === 'notice') {
      if (ev.notice_type === 'friend_recall' || ev.notice_type === 'group_recall') {
        handleRecall(ev);
      } else if (ev.notice_type === 'read_state') {
        handleReadState(ev);
      }
    } else if (ev.post_type === 'request') {
      handleGroupRequest(ev);
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
      else if (seg.type === 'at') parts.push(atLabel(d.qq));
      else if (seg.type === 'reply') continue;
      else if (seg.type === 'json') {
        const card = parseShareCard(seg);
        parts.push(card ? `[分享] ${card.title}` : '[分享]');
      } else if (seg.type === 'forward') {
        parts.push(String((seg.data && (seg.data.summary || seg.data.title))
                          || '聊天记录'));
      }
    }
    return parts.join('');
  }

  // 「甩分享」卡片：vol 发的是 OneBot 的 json 段（内容是一段 QQ 卡片同构的
  // JSON）。解析出来就能画成可点卡片；解析不了就退回纯文本，不丢内容。
  function parseShareCard(seg) {
    const raw = seg && seg.data && seg.data.data;
    if (!raw) return null;
    try {
      const obj = typeof raw === 'string' ? JSON.parse(raw) : raw;
      const news = ((obj || {}).meta || {}).news || {};
      if (!news.jumpUrl && !news.title) return null;
      return {
        title: String(news.title || ''),
        desc: String(news.desc || ''),
        url: String(news.jumpUrl || ''),
        tag: String(news.tag || ''),
        preview: String(news.preview || ''),
      };
    } catch (e) { return null; }
  }

  // 合并转发（forward）段里内嵌的聊天记录：OneBot 把每条放在 data.content 里。
  // 有的实现只给 data.id（要再调 get_forward_msg 才拿得到），那种就只能退回提示。
  function forwardItemsOf(seg) {
    const d = (seg && seg.data) || {};
    const raw = d.content || d.messages || [];
    let list = raw;
    if (typeof raw === 'string') {
      try { list = JSON.parse(raw); } catch (e) { list = []; }
    }
    if (!Array.isArray(list)) return [];
    const out = [];
    for (const it of list) {
      if (!it || typeof it !== 'object') continue;
      const sender = it.sender || it.user_name || it.nickname || {};
      const name = typeof sender === 'string' ? sender
        : String(sender.card || sender.nickname || it.nickname || '某人');
      const body = it.content || it.message || it.text || '';
      let text = '';
      if (typeof body === 'string') text = body;
      else if (Array.isArray(body)) {
        text = body.map((s) => {
          if (!s || typeof s !== 'object') return '';
          if (s.type === 'text') return String((s.data || {}).text || '');
          if (s.type === 'image' || s.type === 'mface') return '[图片]';
          if (s.type === 'record') return '[语音]';
          return '';
        }).join('');
      }
      if (text) out.push({ name, text: text.replace(/\s+/g, ' ').slice(0, 60) });
    }
    return out;
  }

  // 从 get_forward_msg 的响应里取条目。兼容 data.messages[*]（Stapxs/NapCat）
  // 与 data.message[*].data（Lagrange）两种形态。
  function forwardItemsFromApi(data) {
    const d = (data && data.data) || data || {};
    let msgs = d.messages;
    if (!Array.isArray(msgs)) {
      msgs = Array.isArray(d.message)
        ? d.message.map((n) => (n && n.data) || {}) : [];
    }
    const out = [];
    for (const it of msgs) {
      if (!it || typeof it !== 'object') continue;
      const sender = it.sender || {};
      const name = String(sender.card || sender.nickname
                          || it.nickname || '某人');
      const body = it.content || it.message || '';
      let text = '';
      if (typeof body === 'string') text = body;
      else if (Array.isArray(body)) text = segsToText(body);
      if (text) out.push({ name, text: text.replace(/\s+/g, ' ').slice(0, 80) });
    }
    return out;
  }

  // QQ 那种展开的「聊天记录」列表
  function makeFwdBox(title, items) {
    const box = document.createElement('div');
    box.className = 'fwd-box';
    const head = document.createElement('div');
    head.className = 'fwd-head';
    head.textContent = title || '聊天记录';
    box.appendChild(head);
    for (const it of items.slice(0, 30)) {
      const line = document.createElement('div');
      line.className = 'fwd-line';
      const who = document.createElement('span');
      who.className = 'fwd-who';
      who.textContent = it.name;
      const tx = document.createElement('span');
      tx.className = 'fwd-text';
      tx.textContent = it.text;
      line.append(who, tx);
      box.appendChild(line);
    }
    return box;
  }

  function makeShareCard(card) {
    const box = document.createElement('a');
    box.className = 'share-card';
    box.href = card.url || '#';
    box.target = '_blank';
    box.rel = 'noreferrer noopener';
    const head = document.createElement('strong');
    head.textContent = card.title || '分享';
    box.appendChild(head);
    if (card.desc) {
      const p = document.createElement('p');
      p.textContent = card.desc;
      box.appendChild(p);
    }
    if (card.tag) {
      const src = document.createElement('span');
      src.className = 'share-src';
      src.textContent = card.tag;
      box.appendChild(src);
    }
    return box;
  }

  function previewOf(msg) {
    if (msg.recalled) return '消息已撤回';
    const t = (msg.text || '').replace(/\s+/g, ' ').trim();
    if (t) return t.length > 42 ? t.slice(0, 42) + '…' : t;
    return '[消息]';
  }

  // ---------------------------------------------------------- 消息模型
  function makeMsg({ dir, segs, text, ts, mid = '', status = 'sent',
                     displaySegs = null, sender = null, system = false }) {
    const key = `m${++state.keySeq}`;
    const t = ts || nowSec();
    return {
      key, dir, segs: displaySegs || segs || [], text: text || '',
      ts: t, mid: String(mid || ''), status, sender, system,
    };
  }

  function addMsg(msg, force = false) {
    if (!force && msg.mid && state.byMid.has(msg.mid)) return null;
    state.msgs.push(msg);
    if (msg.mid) state.byMid.set(msg.mid, msg);
    hideEmptyState();
    // ★ 乱序到达（服务端 time 比最后一条还早，回放/离线补发时常见）：
    //   排回时间序整屏重画，保证「右侧最下面那条」= 左侧预览引用的那条。
    const prev = state.msgs[state.msgs.length - 2];
    if (prev && Number(msg.ts || 0) < Number(prev.ts || 0)) {
      state.msgs.sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0));
      state.lastTs = 0;
      renderAll(true);
    } else {
      appendRow(msg);
    }
    syncConvPreview();
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

  // 合并历史（私聊 / 群聊都用）。key = 会话键（私聊为 String(id)，群聊为 "g"+群号）。
  // 方向判定：私聊按 sender 是否等于会话对象；群里按 sender 是否是「我」。
  function mergeHistory(history, key = curConvKey(), opts = {}) {
    const k = String(key);
    const isCurrent = k === curConvKey();
    const list = isCurrent ? state.msgs : listFor(k);
    const group = k.charAt(0) === 'g';
    const owner = String(state.me.id || '');
    const seen = new Set(list.map((m) => m.mid).filter(Boolean));
    let added = 0;
    for (const raw of (history || [])) {
      const segs = Array.isArray(raw.message) ? raw.message : [];
      const text = segsToText(segs) || String(raw.raw_message || '');
      if (!text && !segs.length) continue;
      const senderId = String(raw.sender?.user_id ?? raw.user_id ?? '');
      const dir = group
        ? (isOwner(senderId) ? 'out' : 'in')
        : (Number(senderId) === Number(k) ? 'in' : 'out');
      const isSystem = group && String(raw.sender?.role || '') === 'system';
      const mid = String(raw.message_id || '');
      if (mid && seen.has(mid)) continue;
      const m = makeMsg({
        dir, segs, text: text || '[消息]',
        ts: Number(raw.time) || 0,
        mid,
        sender: group ? senderOf(raw) : null,
        system: isSystem,
      });
      // 引用回复：服务端把被引用的那条也带出来了（昵称 + 摘要）
      const rq = raw.reply;
      if (rq && (rq.text || rq.name)) {
        m.replyTo = { name: String(rq.name || ''), text: String(rq.text || ''),
                      message_id: String(rq.message_id || '') };
      }
      // 对方的一轮回复可能是多条气泡拼起来的，时间跨度比单条大；
      // 用户消息仍用 20 秒窗口，避免把重复发的同一句话误删。
      // ★ 群里**必须**保留按内容去重：群历史里一条 gmsg 的 message_id 是
      //   `g<id>`，而实时推送/重放事件的 message_id 是随机序号 —— 两套 id
      //   空间对不上，mid 去重失效。刷新页面时「历史 + 最近事件重放」会把
      //   同一批消息各送一份（历史里还是把多条气泡并成一条），不靠内容+时间
      //   去重就会看到重影。短句偶发被吞的代价远小于满屏重影。
      const win = dir === 'in' ? 180 : 20;
      if (coveredByExisting(m, win, list)) continue;
      list.push(m);
      if (mid) seen.add(mid);
      added += 1;
    }
    if (!added) {
      // ★ 即使没新增也要重推预览：否则服务端缓存里的旧 lastMsg 会一直
      //   挂在左侧，和右侧真正的最新消息不一致（实测 bug）。
      syncConvPreview(k);
      if (!isCurrent) recomputeUnread(k);
      return 0;
    }
    list.sort((a, b) => (a.ts - b.ts));
    if (isCurrent) {
      rebuildMidIndex();
      renderAll(false);
    }
    const last = list[list.length - 1];
    if (last) updateConvPreview(last, k);
    if (isCurrent) {
      markRead(k, last?.ts || 0);
      clearUnread(k);
      if (opts.scroll !== false) scrollToBottom(false);
    } else {
      recomputeUnread(k);
    }
    return added;
  }

  function handleIncoming(ev, replay = false) {
    const mid = String(ev.message_id || '');
    const peer = String(ev.user_id || ev.sender?.user_id || '');
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '');
    const msg = makeMsg({
      dir: 'in', segs, text: text || '[消息]',
      ts: Number(ev.time) || nowSec(), mid,
    });

    // ★ 私聊消息只能按「私聊会话键」归档。以前这里拿 state.bot.id 去比，
    //   而在群会话里 state.bot 还停在上一个私聊角色 —— 于是那个角色的
    //   私聊回复会被当成「当前会话的消息」塞进 state.msgs（＝群的消息数组），
    //   表现就是「没进群的人却能在群里说话」。改成按会话键判定。
    const cur = curConvKey();
    if (peer !== cur) {
      if (!peer) return;                     // 没有发送者，没法归档
      const list = listFor(peer);
      if (mid && list.some((m) => m.mid === mid)) return;
      if (replay && coveredByExisting(msg, 180, list)) return;
      list.push(msg);
      list.sort((a, b) => a.ts - b.ts);
      syncConvPreview(peer);
      if (replay) {
        recomputeUnread(peer);
      } else {
        bumpUnread(peer);
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
    const peer = String(ev.user_id || ev.sender?.user_id || '');
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '') || '[消息]';
    const replay = !!ev._replay;
    const cur = curConvKey();

    if (peer !== cur) {
      if (!peer) return;
      const list = listFor(peer);
      if (mid && list.some((m) => m.mid === mid)) return;
      const m = makeMsg({
        dir: 'out', segs, text,
        ts: Number(ev.time) || nowSec(), mid,
      });
      if (replay && coveredByExisting(m, 20, list)) return;
      list.push(m);
      list.sort((a, b) => a.ts - b.ts);
      syncConvPreview(peer);
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

  // ---- 群消息：群里 user_id 是**发送者**（私聊里是会话对象），方向靠
  //      「发送者是不是我」判定，会话身份靠 group_id。
  // 事件里带的引用信息（服务端把我引用的那条也一并推过来了）
  function replyInfoOf(ev) {
    const r = ev && ev.reply;
    if (!r || (!r.text && !r.name)) return null;
    return { name: String(r.name || ''), text: String(r.text || ''),
             message_id: String(r.message_id || '') };
  }

  function groupMsgFromEvent(ev) {
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '');
    const sender = senderOf(ev);
    return makeMsg({
      dir: isOwner(sender.id) ? 'out' : 'in',
      segs, text: text || '[消息]',
      ts: Number(ev.time) || nowSec(),
      mid: String(ev.message_id || ''),
      sender,
      system: String(sender.role || '') === 'system',
      replyTo: replyInfoOf(ev),
    });
  }

  function handleGroupIncoming(ev, replay = false) {
    const gid = String(ev.group_id || '');
    if (!gid) return;
    const key = groupKey(gid);
    const msg = groupMsgFromEvent(ev);
    if (!groupKnown(gid)) {
      // 陌生的群（别的设备新建的）：拉一次群列表把它补上
      loadGroups().then(() => { renderConvList(); renderContactList(); });
    }
    // ★ 系统消息（入群/踢人/改名/公告/文件）意味着**成员或群资料变了** ——
    //   以前只把这条消息画到聊天里，右侧面板要等你切走再切回来才更新。
    if (msg.system) refreshGroupDetailSoon(gid);
    if (key !== curConvKey()) {
      const list = listFor(key);
      if (msg.mid && list.some((m) => m.mid === msg.mid)) return;
      if (replay && coveredByExisting(msg, 20, list)) return;
      list.push(msg);
      list.sort((a, b) => a.ts - b.ts);
      syncConvPreview(key);
      if (replay) recomputeUnread(key);
      else bumpUnread(key);
      return;
    }
    if (msg.mid && state.byMid.has(msg.mid)) return;
    if (replay && coveredByExisting(msg, 20)) return;
    addMsg(msg);
  }

  function handleGroupSent(ev, replay = false) {
    const gid = String(ev.group_id || '');
    if (!gid) return;
    const key = groupKey(gid);
    const segs = segsOf(ev);
    const text = segsToText(segs) || String(ev.raw_message || '') || '[消息]';
    const mid = String(ev.message_id || '');
    const isRep = replay || !!ev._replay;

    if (key !== curConvKey()) {
      const list = listFor(key);
      if (mid && list.some((m) => m.mid === mid)) return;
      const m = makeMsg({
        dir: 'out', segs, text,
        ts: Number(ev.time) || nowSec(), mid,
        sender: senderOf(ev),
        replyTo: replyInfoOf(ev),
      });
      if (isRep && coveredByExisting(m, 20, list)) return;
      list.push(m);
      list.sort((a, b) => a.ts - b.ts);
      syncConvPreview(key);
      return;
    }

    if (mid && state.byMid.has(mid)) return;
    // 本机刚发出的乐观气泡：把服务端正式 id 绑上去
    const recent = state.msgs.find((m) => m.dir === 'out' && !m.mid &&
      m.status === 'pending' && m.text === text && nowSec() - m.ts <= 20);
    if (recent) {
      if (mid) {
        recent.mid = mid;
        state.byMid.set(mid, recent);
      }
      const rq = replyInfoOf(ev);
      if (rq && !recent.replyTo) recent.replyTo = rq;
      if (recent.status !== 'failed') {
        recent.status = 'sent';
        refreshRow(recent);
      }
      return;
    }
    const m = makeMsg({
      dir: 'out', segs, text,
      ts: Number(ev.time) || nowSec(), mid, sender: senderOf(ev),
      replyTo: replyInfoOf(ev),
    });
    if (isRep && coveredByExisting(m, 20)) return;
    addMsg(m);
  }

  // 入群申请（post_type=request）：刷新待审列表，群行亮红点
  function handleGroupRequest(ev) {
    const gid = String(ev.group_id || '');
    if (!gid) return;
    loadGroups().then(() => {
      renderConvList();
      if (isGroup() && String(state.peer.id) === gid) renderGroupSide();
    });
    const who = String(ev.user_id || (ev.comment && ev.comment.name) || '');
    toast(`有人申请加入群聊${who ? '：' + who : ''}`);
  }

  function handleReadState(ev) {
    const peer = String(ev.user_id || ev.target_id || '');
    const ts = Number(ev.read_time || ev.time || 0);
    if (!peer || !ts) return;
    const key = peer;
    if (ts <= Number(state.lastRead[key] || 0)) return;
    state.lastRead[key] = ts;
    saveLastRead();
    if (key !== curConvKey()) {
      recomputeUnread(key);
    } else {
      const meta = convMetaFor(key);
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
    // 群消息撤回：按群会话键找
    const gid = String(ev.group_id || '');
    if (gid && mid.charAt(0) === 'g') {
      const key = groupKey(gid);
      const list = key === curConvKey() ? state.msgs : listFor(key);
      const gm = list.find((m) => m.mid === mid);
      if (!gm || gm.recalled) return;
      gm.recalled = gm.dir === 'out' ? 'me' : 'bot';
      state.selected.delete(gm.key);
      if (key === curConvKey()) {
        refreshRow(gm);
        updateMultiBar();
      }
      const glast = list[list.length - 1];
      if (glast) syncConvPreview(key);
      toast(gm.dir === 'out' ? '你撤回了一条消息' : '对方撤回了一条消息');
      return;
    }
    const peer = String(ev.user_id || ev.target_id || '');
    const key = peer;
    const isCurrent = !key || key === curConvKey();
    const list = isCurrent ? state.msgs : listFor(key);
    const msg = list.find((m) => m.mid === mid);
    if (!msg) return;
    if (msg.recalled) return;
    msg.recalled = msg.dir === 'out' ? 'me' : 'bot';
    state.selected.delete(msg.key);
    if (isCurrent) {
      refreshRow(msg);
      updateMultiBar();
      const last = list[list.length - 1];
      if (last && last.key === msg.key) syncConvPreview(key || curConvKey());
      toast(msg.dir === 'out' ? '你撤回了一条消息' : '对方撤回了一条消息');
    } else {
      const last = list[list.length - 1];
      if (last) syncConvPreview(key);
      recomputeUnread(key);
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
      applyBubbleDecor(bubble, chatThemeFor(themeKey(), msg.dir));
      return bubble;
    }

    for (const seg of segs) {
      const d = seg.data || {};
      if (seg.type === 'text') {
        const raw = String(d.text || '');
        // ★ 文本里以「@某人 」开头的，前面已经画过 at 芯片了 —— 从这里削掉，
        //   否则会重复一遍（用户实测：气泡左边一块暗色芯片 + 又写一遍名字）
        let body = raw;
        const prev = bubble.lastElementChild;
        if (body && prev && prev.classList
            && prev.classList.contains('at-chip')) {
          // ★ 不依赖芯片的显示名（成员列表没加载时 atLabel 会退化成「@QQ号」，
          //   名字对不上就削不掉）—— 前面已经画过一个 at 芯片，这里把紧随其后的
          //   「@某某 」整段丢掉即可。
          body = body.replace(/^\s*@[^\s@]+[\s\u3000]*/, '');
          if (!body.trim() && raw.trim()) body = '';   // 只 @ 人没文字 → 什么都不留
        }
        if (body) appendTextWithLinks(bubble, body);
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
        chip.className = 'face-chip at-chip';
        // 尾巴留一个空格：@ 后面紧跟正文时不该粘成「@橘雪莉雪梨怎么…」
        chip.textContent = atLabel(d.qq) + ' ';
        bubble.appendChild(chip);
      } else if (seg.type === 'record') {
        const chip = document.createElement('span');
        chip.className = 'face-chip';
        chip.textContent = '语音';
        bubble.appendChild(chip);
      } else if (seg.type === 'json') {
        // 「甩分享」卡片：解析得出来就画卡片。
        // ⚠️ 解析不出来时**不要**画「[聊天记录]」—— 那四个字对一条分享毫无
        // 信息量（用户实测：只看到「[聊天记录]」，完全不知道她发了什么）。
        // 退路优先取出里面能读的文字（标题/摘要/链接），实在没有才提示。
        const card = parseShareCard(seg);
        if (card) {
          if (bubble.childNodes.length) bubble.appendChild(document.createElement('br'));
          bubble.appendChild(makeShareCard(card));
        } else {
          const raw = String((seg.data && seg.data.data) || '');
          const chip = document.createElement('span');
          chip.className = 'face-chip';
          chip.textContent = raw
            ? ('[分享] ' + raw.replace(/[{}\[\]"]/g, ' ').trim().slice(0, 40))
            : '[分享]';
          bubble.appendChild(chip);
        }
      } else if (seg.type === 'forward') {
        // 合并转发：有内嵌内容就展开成列表（QQ 同款）；只有 id、内容在服务端
        // 时，画成**可点**的卡片 —— 点一下调 get_forward_msg 取回来再展开。
        // （原来是死占位「[聊天记录]」，用户实测「点不开」。）
        const title = String((seg.data && (seg.data.title || seg.data.summary))
                             || '聊天记录');
        const items = forwardItemsOf(seg);
        if (items.length) {
          if (bubble.childNodes.length) bubble.appendChild(document.createElement('br'));
          bubble.appendChild(makeFwdBox(title, items));
        } else {
          const fid = String((seg.data && (seg.data.id || seg.data.file)) || '');
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'face-chip fwd-chip';
          chip.textContent = fid ? '聊天记录（点击查看）' : '聊天记录（内容不可用）';
          if (fid) {
            chip.addEventListener('click', async () => {
              if (chip.dataset.loaded) return;
              chip.textContent = '聊天记录（加载中…）';
              try {
                const res = await call('get_forward_msg', { id: fid }, 20000);
                const got = forwardItemsFromApi(res);
                if (got.length) {
                  chip.dataset.loaded = '1';
                  if (bubble.childNodes.length) {
                    bubble.appendChild(document.createElement('br'));
                  }
                  bubble.appendChild(makeFwdBox(title, got));
                  chip.remove();
                } else {
                  chip.textContent = '聊天记录（内容不可用）';
                }
              } catch (e) {
                chip.textContent = '聊天记录（加载失败，点我再试）';
              }
            });
          }
          bubble.appendChild(chip);
        }
      }
    }
    if (!bubble.childNodes.length) bubble.textContent = msg.text || '[消息]';
    applyBubbleDecor(bubble, chatThemeFor(themeKey(), msg.dir));
    return bubble;
  }

  function buildRow(msg) {
    const row = document.createElement('div');
    row.className = 'msg-row ' + (msg.dir === 'out' ? 'out' : 'in');
    if (msg.status === 'pending') row.classList.add('pending');
    if (msg.status === 'failed') row.classList.add('failed');
    if (msg.selected || state.selected.has(msg.key)) row.classList.add('selected');
    row.dataset.key = msg.key;
    if (msg.mid) row.dataset.mid = msg.mid;

    // 群里的系统消息（入群/改名/公告/踢人…）：居中提示，不带头像
    if (msg.system) {
      row.className = 'msg-row system';
      const tip = document.createElement('div');
      tip.className = 'system-tip';
      tip.textContent = msg.text || '';
      row.appendChild(tip);
      row.addEventListener('contextmenu', (e) => e.preventDefault());
      return row;
    }

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

    // 头像：群里每条消息都带自己的发送者（头像 + 昵称 + 等级/角色）
    const sender = msg.sender;
    const av = document.createElement('div');
    av.className = 'avatar ' + (msg.dir === 'out' ? 'me-avatar' : 'bot-avatar');
    if (msg.dir === 'out') {
      av.title = state.me.name;
      fillAvatar(av, state.me.name, state.me.id, '我');
    } else if (sender && sender.id) {
      if (sender.role === 'system') {
        av.title = '系统';
        fillAvatar(av, '系统', '', '系');
      } else {
        av.title = sender.name;
        fillAvatar(av, sender.name, sender.id);
      }
    } else if (isGroup()) {
      // ★ 群里 sender 缺失时绝不能借用私聊角色 —— 那会把所有人都画成同一个
      //   头像（实测：刷新进群后所有人头像都变成星野，切换会话后才恢复）。
      av.title = '群成员';
      fillAvatar(av, '群成员', '', '群');
    } else {
      av.title = state.bot.name;
      fillAvatar(av, state.bot.name, state.bot.id);
    }
    // ★ 群里右键别人的头像 → 弹出成员菜单（第一项就是「@ ta」），
    //   和右侧成员列表同一套菜单。自己的头像不弹（不能 @ 自己）。
    av.addEventListener('contextmenu', (e) => {
      if (!isGroup() || state.selectMode) return;
      if (!sender || !sender.id) return;
      const sid = String(sender.id);
      if (sid === String(state.me.id) || isOwner(sid)
          || String(sender.role || '') === 'system') return;
      e.preventDefault();
      e.stopPropagation();
      openMemberMenu(e, { user_id: sid,
                          nickname: sender.name || sid,
                          role: sender.role || 'member' });
    });

    const body = document.createElement('div');
    body.className = 'msg-body';

    // 群聊里每条消息上方显示「昵称 + 等级/角色标签」（像 QQ 群）
    if (sender && !sender.system && (isGroup() || sender.id)) {
      const head = document.createElement('div');
      head.className = 'msg-sender';
      const nm = document.createElement('span');
      nm.className = 'ms-name';
      nm.textContent = sender.name;
      head.appendChild(nm);
      const badge = senderBadge(sender);
      if (badge) head.appendChild(badge);
      body.appendChild(head);
    }

    // 引用回复：气泡上方一条「昵称 + 摘要」的引用块（点了跳到原消息）
    if (msg.replyTo && (msg.replyTo.text || msg.replyTo.name)) {
      const ref = document.createElement('div');
      ref.className = 'quote-ref';
      const nm = document.createElement('span');
      nm.className = 'qr-name';
      nm.textContent = msg.replyTo.name || '消息';
      const tx = document.createElement('span');
      tx.className = 'qr-text';
      tx.textContent = msg.replyTo.text || '';
      ref.append(nm, tx);
      if (msg.replyTo.message_id) {
        ref.addEventListener('click', () => {
          const target = state.msgs.find((x) => x.mid === msg.replyTo.message_id);
          const row2 = target && rowElOf(target);
          if (!row2) { toast('被引用的消息不在当前加载范围'); return; }
          row2.scrollIntoView({ block: 'center', behavior: 'smooth' });
          row2.classList.add('flash');
          setTimeout(() => row2.classList.remove('flash'), 1200);
        });
      }
      body.appendChild(ref);
    }

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

  // 群成员标签：群主 / 管理员 / LV 等级（QQ 群的味道）
  function senderBadge(sender) {
    if (!sender || sender.system) return null;
    const wrap = document.createElement('span');
    wrap.className = 'ms-badges';
    let any = false;
    const role = String(sender.role || '');
    if (role === 'owner' || role === 'admin') {
      const r = document.createElement('em');
      r.className = 'ms-role ' + role;
      r.textContent = role === 'owner' ? '群主' : '管理';
      wrap.appendChild(r);
      any = true;
    }
    const lv = Number(sender.level || 0);
    if (lv > 0) {
      const l = document.createElement('em');
      l.className = 'ms-lv';
      l.textContent = 'LV' + lv;
      wrap.appendChild(l);
      any = true;
    }
    return any ? wrap : null;
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

  // ★ 左侧列表预览的唯一真源 = 该会话里「真正最新的那条消息」。
  //   之前预览有三个写入方（服务端 get_recent_contact 的 lastMsg、
  //   历史合并后的最后一条、实时到达的那一条），彼此不核对 ——
  //   「历史没新增」时（重启/二次同步很常见）服务端的旧 lastMsg 会一直
  //   挂在左侧，于是左侧预览和右侧对话的最新消息对不上（实测 bug）。
  function syncConvPreview(key = curConvKey()) {
    const k = String(key);
    const list = k === curConvKey() ? state.msgs : listFor(k);
    if (!list.length) return;
    let last = list[0];
    for (const m of list) {
      if (Number(m.ts || 0) >= Number(last.ts || 0)) last = m;
    }
    const meta = convMetaFor(k);
    // 群消息预览带上说话人（像 QQ：「小星：今晚吃啥」）
    const who = k.charAt(0) === 'g' && last.dir !== 'out' && last.sender
      ? last.sender.name + '：' : (last.dir === 'out' ? '我：' : '');
    meta.preview = who + previewOf(last);
    meta.ts = last.ts;
    renderConvList();
  }

  function updateConvPreview(_msg, key = curConvKey()) {
    syncConvPreview(key);        // 兼容旧调用点：一律重新推导
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

  function bumpUnread(key = curConvKey()) {
    const meta = convMetaFor(key);
    meta.unread = (meta.unread || 0) + 1;
    state.unread = totalUnread();
    updateBadges();
    renderConvList();
    updateDocTitle();
  }

  function clearUnread(key = curConvKey()) {
    markRead(key, 0);
    const meta = convMetaFor(key);
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
    if (!text.trim() && !state.pendingMentions.length) return;
    if (!state.connected) {
      toast('还没连上，稍等一下再发');
      return;
    }
    els.input.value = '';
    autosize();
    updateSendBtn();
    // 群里 @ 的人转成 at 段一起发（后端靠 at 段判断「@ 了谁」）
    const segs = isGroup() ? composeSegs(text) : [{ type: 'text', data: { text } }];
    // 引用回复：reply 段放在最前面，后端据此把 reply_to 落库。
    // ★ 私聊也允许引用（QQ 私聊里同样能引用某条消息）——原来只在群里给这个入口。
    const quoted = (state.replyTo && state.replyTo.mid) ? state.replyTo : null;
    if (quoted) segs.unshift({ type: 'reply', data: { id: quoted.mid } });
    // ★ QQ 的群引用会**顺手 @ 被引用的那个人**（对方收到提醒、也才知道你在回他）。
    //   这里照做：没手动 @ 过同一个人时，自动补一个 at 段（排在 reply 段之后）。
    //   私聊不加 @（真人私聊不这么干）。
    if (quoted && isGroup()) {
      const tgt = quoteAtTarget(quoted);
      const already = segs.some((s) => s.type === 'at'
        && String(s.data && s.data.qq) === String(tgt && tgt.id));
      if (tgt && !already) {
        segs.splice(1, 0, { type: 'at', data: { qq: atQqOf(tgt.id) } });
      }
    }
    state.pendingMentions = [];
    clearQuote();
    doSend(segs, text, null, quoted);
    els.input.focus();
  }

  // 发送目标参数：私聊 → send_msg + user_id；群聊 → send_group_msg + group_id
  function sendTarget() {
    if (isGroup()) {
      return { action: 'send_group_msg', params: { group_id: state.peer.id } };
    }
    return {
      action: 'send_msg',
      params: { message_type: 'private', user_id: state.bot.id },
    };
  }

  async function doSend(sendSegs, text, displaySegs = null, quoted = null) {
    if (!state.connected) {
      toast('还没连上，稍等一下再发');
      return;
    }
    const t = sendTarget();
    const msg = addMsg(makeMsg({
      dir: 'out', segs: sendSegs, displaySegs,
      text: text || segsToText(displaySegs || sendSegs),
      ts: nowSec(), status: 'pending',
      sender: isGroup()
        ? { id: String(state.me.id), name: state.me.name, role: 'owner',
            level: myGroupLevel() }
        : null,
      replyTo: quoted ? quoteLabelOf(quoted) : null,
    }));
    if (!msg) return;
    try {
      const res = await call(t.action, { ...t.params, message: sendSegs }, 25000);
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
      const t = sendTarget();
      const res = await call(t.action, { ...t.params, message: msg.segs }, 25000);
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
    // ★ 「这个对话可用的表情包」是按私聊角色配的。群聊不该套用上一个私聊
    //   角色（实测会变成橘光的那套），群里的表情面板直接给全集。
    if (isGroup()) return all;
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
    const show = (act, on) => {
      const b = els.ctxMenu.querySelector(`button[data-act="${act}"]`);
      if (b) b.classList.toggle('hidden', !on);
    };
    const inGroup = isGroup();
    show('resend', msg.dir === 'out' && msg.status === 'failed');
    // 群消息撤回后端还没打通（群消息 id 是 g<id>，撤回只认私聊），先隐藏
    show('recall', !!msg.mid && !msg.recalled && !inGroup);
    // 私聊 → 可把这段对话分享/转发到某个群（用户要的「抖进群里」）
    show('shareGroup', !inGroup && !!state.groups.length);
    // 引用回复：群、私聊都支持（有稳定 mid 就能引用）
    show('quote', !msg.system && !msg.recalled && !!msg.mid);
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
    else if (act === 'quote') setQuote(msg);
    else if (act === 'resend') resend(msg);
    else if (act === 'recall') recallMessage(msg);
    else if (act === 'shareGroup') openGroupPickerFor([msg]);
    else if (act === 'delete') {
      const i = state.msgs.findIndex((m) => m.key === msg.key);
      if (i >= 0) state.msgs.splice(i, 1);
      if (msg.mid) state.byMid.delete(msg.mid);
      renderAll(false);
      syncConvPreview();
      toast('已从本机删除（不影响 vol 的记忆）');
    }
  });

  // ---------------------------------------------------------- 多选 / 转发 / 撤回
  function applyRecallLocally(msg, key, silent = false) {
    if (!msg || msg.recalled) return false;
    // 同样按「会话键」定位（撤回只有私聊走这条路，但别再拿 state.bot 当身份）
    const k = String(key || curConvKey());
    const isCurrent = k === curConvKey();
    const list = isCurrent ? state.msgs : listFor(k);
    msg.recalled = msg.dir === 'out' ? 'me' : 'bot';
    state.selected.delete(msg.key);
    if (isCurrent) {
      refreshRow(msg);
      updateMultiBar();
      const last = list[list.length - 1];
      if (last && last.key === msg.key) syncConvPreview(k);
    } else {
      const last = list[list.length - 1];
      if (last) syncConvPreview(k);
      recomputeUnread(k);
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
      pane: (els.chatMain || els.chatPane).getBoundingClientRect(),
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
    const lines = [`【聊天记录】与${curPeerName()}的聊天`];
    for (const m of msgs) {
      const who = m.dir === 'out' ? state.me.name
        : (m.sender ? m.sender.name : curPeerName());
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
    const targets = [];
    // 群聊排前面（转发到群里是用户最想要的），再是其他好友
    for (const g of state.groups) {
      targets.push({ kind: 'group', id: String(g.group_id), name: g.group_name || '群聊' });
    }
    for (const c of state.characters) {
      if (isGroup() || c.id !== Number(state.bot.id)) {
        targets.push({ kind: 'private', id: c.id, name: c.name });
      }
    }
    for (const t of targets) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'forward-item';
      const av = document.createElement('div');
      av.className = 'avatar ' + (t.kind === 'group' ? 'group-avatar' : 'bot-avatar');
      if (t.kind === 'group') fillGroupAvatar(av, t.name, t.id);
      else fillAvatar(av, t.name, t.id);
      const name = document.createElement('span');
      name.textContent = t.name;
      if (t.kind === 'group') {
        const tag = document.createElement('em');
        tag.className = 'forward-tag';
        tag.textContent = '群';
        name.appendChild(tag);
      }
      btn.append(av, name);
      btn.addEventListener('click', () => forwardTo(t));
      els.forwardList.appendChild(btn);
    }
    if (!targets.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '还没有别的聊天对象，先添加一个角色或建个群吧。';
      els.forwardList.appendChild(empty);
    }
    els.forwardMask.classList.remove('hidden');
  }

  function closeForwardModal() {
    els.forwardMask.classList.add('hidden');
    state.forwardMode = '';
  }

  // 把选中的几条消息转发/分享到目标（群或好友）
  async function forwardTo(target) {
    const msgs = selectedMsgs();
    const mode = state.forwardMode;
    if (!msgs.length) { closeForwardModal(); return; }
    const isGrp = target && target.kind === 'group';
    const payloadBase = isGrp
      ? { group_id: String(target.id) }
      : { message_type: 'private', user_id: Number(target.id) };
    const action = isGrp ? 'send_group_msg' : 'send_msg';
    try {
      if (mode === 'merge') {
        await call(action, {
          ...payloadBase,
          message: [{ type: 'text', data: { text: mergedForwardText(msgs) } }],
        }, 25000);
      } else {
        for (const m of msgs) {
          await call(action, { ...payloadBase, message: forwardSegsFor(m) }, 25000);
        }
      }
      toast(`已转发 ${msgs.length} 条给 ${target?.name || '对方'}`);
      closeForwardModal();
      exitSelectMode();
    } catch (e) {
      toast('转发失败：' + (e?.message || e));
    }
  }

  // 右键「分享到群」：选一个群，再把这几条消息转过去（友尽式打小报告的小道具）
  function openGroupPickerFor(msgs) {
    if (!state.groups.length) { toast('还没有群，先建一个群吧'); return; }
    const chosen = msgs.filter((m) => m && !m.recalled);
    if (!chosen.length) return;
    els.forwardMask.classList.remove('hidden');
    els.forwardTitle.textContent = '分享到群';
    state.forwardMode = 'merge';
    els.forwardList.innerHTML = '';
    // 借用转发弹窗的选中集合不方便，这里直接用一次性的消息列表
    const prevSel = state.selected;
    state.selected = new Set(chosen.map((m) => m.key));
    for (const g of state.groups) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'forward-item';
      const av = document.createElement('div');
      av.className = 'avatar group-avatar';
      fillGroupAvatar(av, g.group_name || '群聊', g.group_id);
      const name = document.createElement('span');
      name.textContent = g.group_name || '群聊';
      btn.append(av, name);
      btn.addEventListener('click', async () => {
        await forwardTo({ kind: 'group', id: String(g.group_id),
                          name: g.group_name || '群聊' });
        state.selected = prevSel;
      });
      els.forwardList.appendChild(btn);
    }
    els.forwardMask.addEventListener('click', () => { state.selected = prevSel; },
      { once: true });
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

  // ---------------------------------------------------------- 群聊界面
  // 右侧面板参考 QQ 的群资料页：入群申请 + 群公告 + 群聊成员。
  // 群主能在面板上改名/发公告/开全员禁言/@人/设管理员/踢人。

  function curGroupDetail() {
    return isGroup() ? (state.groupDetail[String(state.peer.id)] || null) : null;
  }

  function renderGroupSide() {
    if (!els.groupSide) return;
    if (!isGroup() || state.groupSideHidden) {
      els.groupSide.classList.add('hidden');
      return;
    }
    els.groupSide.classList.remove('hidden');
    const gid = String(state.peer.id);
    const d = curGroupDetail();
    const name = groupName(gid);
    els.gsName.textContent = name;
    fillGroupAvatar(els.gsAvatar, name, gid);
    if (els.chatAvatar) fillGroupAvatar(els.chatAvatar, name, gid);
    const count = d ? (d.member_count || (d.members || []).length)
                    : ((groupById(gid) || {}).member_count || 0);
    els.gsCount.textContent = `${count} 人` + ((d && d.mute_all) ? ' · 全员禁言中' : '');
    els.gsAnnounce.textContent = ((d && (d.announce || {}).text) || '还没有群公告');
    if (els.chatSub) {
      els.chatSub.textContent = ((d && d.mute_all) ? '全员禁言中 · ' : '') + `${count} 人`;
    }
    renderGroupRequests();
    renderGroupMembers();
    renderGroupFiles();
  }

  function renderGroupRequests() {
    if (!els.gsRequests) return;
    const d = curGroupDetail();
    const reqs = (d && d.pending) || [];
    els.gsRequestCard.classList.toggle('hidden', !reqs.length);
    if (els.gsRequestCount) els.gsRequestCount.textContent = String(reqs.length);
    els.gsRequests.innerHTML = '';
    for (const r of reqs) {
      // ★ 后端库里存的是 uid；用 user_id 兜底（取不到就会把空 uid 发给后端，
      //   结果点同意报「没有这个申请」）
      const uid = String(r.user_id || r.uid || '');
      const name = r.name || uid;
      const row = document.createElement('div');
      row.className = 'gs-req';
      const av = document.createElement('div');
      av.className = 'avatar bot-avatar';
      fillAvatar(av, name, uid);
      const info = document.createElement('div');
      info.className = 'gs-req-info';
      const nm = document.createElement('strong');
      nm.textContent = name;
      const note = document.createElement('span');
      note.textContent = r.note || '想加入这个群';
      info.append(nm, note);
      const acts = document.createElement('div');
      acts.className = 'gs-req-acts';
      const ok = document.createElement('button');
      ok.className = 'btn-primary mini-btn';
      ok.textContent = '同意';
      ok.addEventListener('click', () => resolveJoin(uid, true));
      const no = document.createElement('button');
      no.className = 'ghost mini-btn';
      no.textContent = '拒绝';
      no.addEventListener('click', () => resolveJoin(uid, false));
      acts.append(ok, no);
      row.append(av, info, acts);
      els.gsRequests.appendChild(row);
    }
  }

  async function resolveJoin(uid, approve) {
    try {
      await groupManage('resolve', {
        group_id: state.peer.id, user_id: uid, approve,
      });
      await loadGroups();
      renderConvList();
      await loadGroupDetail(state.peer.id);
      toast(approve ? '已同意入群' : '已拒绝申请');
    } catch (e) { toast('操作失败：' + (e.message || e)); }
  }

  function renderGroupMembers() {
    if (!els.gsMembers) return;
    const d = curGroupDetail();
    const members = (d && d.members) || [];
    const q = ((els.gsMemberSearch && els.gsMemberSearch.value) || '').trim();
    els.gsMembers.innerHTML = '';
    if (els.gsMemberCount) els.gsMemberCount.textContent = String(members.length);
    if (!members.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '成员还没同步过来…';
      els.gsMembers.appendChild(empty);
      return;
    }
    for (const m of members) {
      const name = m.nickname || String(m.user_id);
      if (q && !name.includes(q)) continue;
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'gs-member';
      const av = document.createElement('div');
      av.className = 'avatar';
      if (m.is_me || isOwner(m.user_id)) fillAvatar(av, state.me.name, state.me.id, '我');
      else fillAvatar(av, name, m.user_id);
      const info = document.createElement('div');
      info.className = 'gs-member-info';
      const nm = document.createElement('strong');
      nm.textContent = name;
      if (m.is_me || isOwner(m.user_id)) {
        const me = document.createElement('em');
        me.className = 'ms-role owner';
        me.textContent = '我';
        nm.appendChild(me);
      }
      info.appendChild(nm);
      const sub = document.createElement('span');
      const bits = [];
      if (m.role === 'owner') bits.push('群主');
      else if (m.role === 'admin') bits.push('管理员');
      bits.push('LV' + Number(m.level || 1));
      sub.textContent = bits.join(' · ');
      info.appendChild(sub);
      row.append(av, info);
      if (String(m.role) !== 'owner' && !(m.is_me || isOwner(m.user_id))) {
        const more = document.createElement('span');
        more.className = 'gs-member-more';
        more.innerHTML = '<svg><use href="#i-more"/></svg>';
        row.appendChild(more);
      }
      row.addEventListener('click', (e) => openMemberMenu(e, m));
      els.gsMembers.appendChild(row);
    }
  }

  function openMemberMenu(e, m) {
    e.stopPropagation();
    if (m.role === 'owner' || isOwner(m.user_id)) return;
    state.memberMenuFor = m;
    if (els.mactAdminText) {
      els.mactAdminText.textContent = m.role === 'admin' ? '取消管理员' : '设为管理员';
    }
    els.memberMenu.classList.remove('hidden');
    const rect = els.memberMenu.getBoundingClientRect();
    els.memberMenu.style.left =
      Math.max(8, Math.min(e.clientX, window.innerWidth - rect.width - 8)) + 'px';
    els.memberMenu.style.top =
      Math.max(8, Math.min(e.clientY, window.innerHeight - rect.height - 8)) + 'px';
  }

  if (els.memberMenu) {
    els.memberMenu.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-mact]');
      if (!btn) return;
      const m = state.memberMenuFor;
      const act = btn.dataset.mact;
      els.memberMenu.classList.add('hidden');
      if (!m || !isGroup()) return;
      if (act === 'at') atMember(m);
      else if (act === 'admin') toggleAdmin(m);
      else if (act === 'kick') kickMember(m);
    });
  }

  function addMention(id, name) {
    const sid = String(id);
    if (state.pendingMentions.some((x) => String(x.id) === sid)) return;
    state.pendingMentions.push({ id: sid, name });
  }

  function atMember(m) {
    addMention(m.user_id, m.nickname || String(m.user_id));
    insertAtCursor(`@${m.nickname || m.user_id} `);
    els.input.focus();
  }

  function atAll() {
    addMention('all', '全体成员');
    insertAtCursor('@全体成员 ');
    els.input.focus();
  }

  // @ 的显示名（把 at 段里的 QQ 号换成群名片）
  function atLabel(qq) {
    const s = String(qq);
    if (s === 'all' || s === '-1' || s === '0') return '@全体成员';
    const d = curGroupDetail();
    const m = ((d && d.members) || []).find((x) => String(x.user_id) === s);
    if (m && m.nickname) return '@' + m.nickname;
    // ★ 群详情还没拉到时不要显示「@3901000018」这种 QQ 号 —— 先用角色名兜底
    //   （否则历史消息一进群就是「@一串数字」，用户会以为 @ 坏了）。
    const c = (state.characters || []).find((x) => String(x.id) === s);
    if (c && c.name) return '@' + c.name;
    if (state.me && String(state.me.id) === s) return '@' + state.me.name;
    return '@' + s;
  }

  // 发送时把待发的 at 段拼到最前面（后端靠 at 段判断「@ 了谁」）
  // ★ 必须把输入框里那段「@名字 」剥掉：atMember/atAll 往输入框插的是纯文本
  //   「@橘雪莉 」，如果再原样留在 text 段里，气泡上就会出现**两遍**——
  //   一个 at 芯片 + 文本里的「@橘雪莉」（用户实测：气泡左边一块像空白的
  //   暗色芯片，后面又重复一遍名字）。
  function composeSegs(text) {
    const segs = [];
    let rest = String(text || '');
    for (const m of state.pendingMentions) {
      segs.push({ type: 'at', data: { qq: m.id === 'all' ? 'all' : Number(m.id) } });
      const label = '@' + String(m.name || m.id);
      const i = rest.indexOf(label);
      if (i >= 0) {
        rest = (rest.slice(0, i) + rest.slice(i + label.length)).replace(/^\s+/, '');
      }
    }
    // 只 @ 了人、一个字没说：保留原文，否则后端会当成空消息整条丢掉
    const body = rest.trim() ? rest : String(text || '');
    segs.push({ type: 'text', data: { text: body } });
    return segs;
  }

  async function toggleAdmin(m) {
    try {
      await groupManage('admin', {
        group_id: state.peer.id, user_id: m.user_id, on: m.role !== 'admin',
      });
      toast(m.role === 'admin' ? '已取消管理员' : '已设为管理员');
    } catch (e) { toast('操作失败：' + (e.message || e)); }
  }

  async function kickMember(m) {
    const name = m.nickname || m.user_id;
    if (!window.confirm(`把「${name}」移出群聊？`)) return;
    try {
      await groupManage('kick', { group_id: state.peer.id, user_id: m.user_id });
      await loadGroups();
      renderConvList();
      await loadGroupDetail(state.peer.id);
      toast(`已把 ${name} 移出群聊`);
    } catch (e) { toast('操作失败：' + (e.message || e)); }
  }

  // ---- 引用回复 ----

  function quoteLabelOf(msg) {
    if (!msg) return { name: '', text: '' };
    const name = msg.dir === 'out' ? state.me.name
      : (msg.sender ? msg.sender.name : state.bot.name);
    return { name, text: previewOf(msg) };
  }

  function setQuote(msg) {
    if (!msg || !msg.mid) { toast('这条消息还没消息 ID，无法引用'); return; }
    state.replyTo = msg;
    renderQuoteBar();
    els.input.focus();
  }

  // 引用时该 @ 谁：QQ 的群引用会自动 @ 被引用消息的发送者。
  // 引用自己发的不加 @（不给自己发提醒）；系统消息没有发送者，也不加。
  function quoteAtTarget(msg) {
    if (!msg || msg.system) return null;
    const sid = msg.sender ? String(msg.sender.id || '') : '';
    if (!sid || sid === String(state.me.id) || isOwner(sid)) return null;
    return { id: sid, name: (msg.sender && msg.sender.name) || sid };
  }

  // at 段的 qq 字段：能转数字就转（和手动 @ 的写法保持一致），否则原样
  function atQqOf(id) {
    const s = String(id || '');
    return /^\d+$/.test(s) ? Number(s) : s;
  }

  function clearQuote() {
    state.replyTo = null;
    renderQuoteBar();
  }

  function renderQuoteBar() {
    if (!els.quoteBar) return;
    const q = state.replyTo;
    if (!q) {
      els.quoteBar.classList.add('hidden');
      return;
    }
    const label = quoteLabelOf(q);
    els.qbName.textContent = label.name;
    els.qbText.textContent = label.text;
    els.quoteBar.classList.remove('hidden');
  }

  if (els.qbClose) els.qbClose.addEventListener('click', clearQuote);

  // ---- 群文件 / 群相册 ----

  async function loadGroupFiles(gid) {
    const g = String(gid || '');
    if (!g) return;
    try {
      const res = await apiFetch(
        `/api/groups/files?group_id=${encodeURIComponent(g)}`,
        { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      state.groupFiles[g] = (data && data.files) || [];
      if (isGroup() && String(state.peer.id) === g) renderGroupFiles();
    } catch (e) { /* 老服务端没有这个接口 */ }
  }

  function fileUrl(it) {
    return `/api/groups/file?group_id=${encodeURIComponent(state.peer.id)}`
      + `&file_id=${encodeURIComponent(it.id)}`;
  }

  function fmtSize(n) {
    const v = Number(n || 0);
    if (v >= 1048576) return (v / 1048576).toFixed(1) + ' MB';
    if (v >= 1024) return (v / 1024).toFixed(0) + ' KB';
    return v + ' B';
  }

  function renderGroupFiles() {
    if (!els.gsFiles || !isGroup()) return;
    const items = state.groupFiles[String(state.peer.id)] || [];
    const album = state.groupFileTab === 'album';
    const list = items.filter((it) => (album ? it.kind === 'image' : true));
    if (els.gsFileCount) els.gsFileCount.textContent = String(items.length);
    els.gsFiles.innerHTML = '';
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = album ? '群相册还是空的' : '还没有群文件';
      els.gsFiles.appendChild(empty);
      return;
    }
    if (album) {
      const grid = document.createElement('div');
      grid.className = 'gs-album';
      for (const it of list) {
        if (it.kind !== 'image') continue;
        const img = document.createElement('img');
        img.loading = 'lazy';
        img.alt = it.name;
        img.src = fileUrl(it);
        img.addEventListener('click', () => openLightbox(fileUrl(it)));
        grid.appendChild(img);
      }
      els.gsFiles.appendChild(grid);
      return;
    }
    for (const it of list) {
      const row = document.createElement('div');
      row.className = 'gs-file';
      const ico = document.createElement('span');
      ico.className = 'gs-file-ico';
      ico.innerHTML = `<svg><use href="#i-${it.kind === 'image' ? 'image' : 'folder'}"/></svg>`;
      const info = document.createElement('div');
      info.className = 'gs-file-info';
      const nm = document.createElement('strong');
      nm.textContent = it.name;
      const sub = document.createElement('span');
      sub.textContent = `${fmtSize(it.size)} · ${it.uploader || ''}`;
      info.append(nm, sub);
      const dl = document.createElement('a');
      dl.className = 'gs-file-dl';
      dl.href = fileUrl(it);
      dl.setAttribute('download', it.name);
      dl.title = '下载';
      dl.innerHTML = '<svg><use href="#i-download"/></svg>';
      row.append(ico, info, dl);
      if (it.uploader && it.uploader === state.me.name) {
        const del = document.createElement('button');
        del.className = 'gs-file-del';
        del.title = '删除';
        del.innerHTML = '<svg><use href="#i-trash"/></svg>';
        del.addEventListener('click', () => deleteGroupFile(it));
        row.appendChild(del);
      }
      els.gsFiles.appendChild(row);
    }
  }

  async function uploadGroupFiles(files) {
    if (!isGroup() || !files.length) return;
    // ★ 群号要**先抓下来**：下面每个文件都要 await 一次上传，如果在上传途中
    //   用户切到了别的会话，`state.peer.id` 就变了，后面的文件会被传到别的群。
    const gid = String(state.peer.id);
    let ok = 0;
    for (const f of files) {
      if (f.size > 20 * 1024 * 1024) { toast(`「${f.name}」超过 20MB，跳过`); continue; }
      try {
        const dataUrl = await readDataURL(f);
        const res = await apiFetch('/api/groups/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ group_id: gid, name: f.name, data: dataUrl }),
        });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
        ok += 1;
      } catch (e) {
        toast(`「${f.name}」上传失败：` + (e.message || e));
      }
    }
    if (ok) {
      toast(`已上传 ${ok} 个文件`);
      await loadGroupFiles(gid);
    }
  }

  async function deleteGroupFile(it) {
    if (!window.confirm(`删除群文件「${it.name}」？`)) return;
    const gid = String(state.peer.id);
    try {
      const res = await apiFetch('/api/groups/files/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_id: gid, file_id: it.id }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      toast('已删除');
      await loadGroupFiles(gid);
    } catch (e) { toast('删除失败：' + (e.message || e)); }
  }

  if (els.gsUpload) els.gsUpload.addEventListener('click', () => {
    if (!isGroup()) return;
    els.gsFileInput.value = '';
    els.gsFileInput.click();
  });
  if (els.gsFileInput) els.gsFileInput.addEventListener('change', () => {
    const files = [...(els.gsFileInput.files || [])];
    els.gsFileInput.value = '';
    uploadGroupFiles(files);
  });
  if (els.gsFileTabs) els.gsFileTabs.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-ftab]');
    if (!b) return;
    state.groupFileTab = b.dataset.ftab;
    els.gsFileTabs.querySelectorAll('button').forEach((x) => {
      x.classList.toggle('active', x === b);
    });
    renderGroupFiles();
  });

  // ---- 建群 / 邀请 ----

  function memberPicker(container, opts) {
    container.innerHTML = '';
    const inGroup = new Set((opts.existing || []).map(String));
    const picked = new Set();
    for (const c of state.characters) {
      if (c.id === Number(state.bot.id) && !opts.includeCurrent) continue;
      const cid = String(c.id);
      const already = inGroup.has(cid);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cg-member';
      btn.dataset.cid = cid;
      const av = document.createElement('div');
      av.className = 'avatar bot-avatar';
      fillAvatar(av, c.name, c.id);
      const name = document.createElement('span');
      name.textContent = c.name;
      const tick = document.createElement('i');
      tick.className = 'cg-tick';
      tick.innerHTML = '<svg><use href="#i-check"/></svg>';
      if (already) {
        const tag = document.createElement('em');
        tag.className = 'cg-tag';
        tag.textContent = '已在群';
        btn.append(av, name, tag);
        btn.disabled = true;
      } else {
        btn.append(av, name, tick);
        btn.addEventListener('click', () => {
          if (picked.has(cid)) {
            picked.delete(cid);
            btn.classList.remove('on');
          } else {
            picked.add(cid);
            btn.classList.add('on');
          }
        });
      }
      container.appendChild(btn);
    }
    if (!container.childNodes.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '还没有可邀请的好友。';
      container.appendChild(empty);
    }
    return picked;
  }

  function openCreateGroup() {
    if (!state.characters.length) { toast('先添加一个角色吧'); return; }
    els.cgName.value = '';
    memberPicker(els.cgMembers, { includeCurrent: false });
    els.createGroupMask.classList.remove('hidden');
    setTimeout(() => els.cgName.focus(), 50);
  }

  function closeCreateGroup() {
    els.createGroupMask.classList.add('hidden');
  }

  async function createGroupNow() {
    const name = els.cgName.value.trim();
    if (!name) { toast('先给群起个名字'); els.cgName.focus(); return; }
    const memberIds = [...els.cgMembers.querySelectorAll('.cg-member.on')]
      .map((b) => Number(b.dataset.cid)).filter(Boolean);
    els.cgCreate.disabled = true;
    try {
      const res = await apiFetch('/api/groups/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, members: memberIds }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data || data.ok === false) {
        throw new Error((data && data.error) || '创建失败');
      }
      if (data.group_id) {
        state.groupDetail[String(data.group_id)] = data;
        syncGroupSummary(data);
      }
      await loadGroups();
      closeCreateGroup();
      renderConvList();
      renderContactList();
      if (data.group_id) selectPeer('group', data.group_id);
      toast('群已创建');
    } catch (e) {
      toast('创建失败：' + (e.message || e));
    } finally {
      els.cgCreate.disabled = false;
    }
  }

  async function openInvite() {
    if (!isGroup()) return;
    // ★ 先把群详情拿到手再建选择器 —— 以前详情还在路上时 members 是空的，
    //   于是「已在群」的标记全失，已经在群里的人也会出现在可邀请列表里。
    await loadGroupDetail(state.peer.id, { render: false });
    const d = curGroupDetail();
    if (!d || !(d.members || []).length) {
      toast('成员还没同步过来，稍等一下再点');
      return;
    }
    const existing = (d.members || []).map((m) => String(m.user_id));
    const picked = memberPicker(els.inviteMembers, { existing, includeCurrent: true });
    els.inviteMask.classList.remove('hidden');
    state.invitePicked = picked;
  }

  async function inviteNow() {
    const picked = state.invitePicked;
    els.inviteMask.classList.add('hidden');
    if (!picked || !picked.size) return;
    const d = curGroupDetail();
    const already = new Set(((d && d.members) || []).map((m) => String(m.user_id)));
    const targets = [...picked].filter((uid) => !already.has(String(uid)));
    if (!targets.length) { toast('选的人都已经在群里了'); return; }
    // ★ 群号先抓下来：循环里有 await，切会话后 state.peer.id 会变
    const gid = String(state.peer.id);
    let ok = 0;
    for (const uid of targets) {
      try {
        await groupManage('invite', {
          group_id: gid, user_id: uid,
          name: (state.characters.find((c) => String(c.id) === String(uid)) || {}).name || uid,
        });
        ok += 1;
      } catch (e) {
        toast(`「${uid}」邀请失败：` + (e.message || e));
      }
    }
    await loadGroups();
    await loadGroupDetail(gid);
    renderConvList();
    if (ok) toast(`已邀请 ${ok} 位好友入群`);
  }

  // ---- 群设置 / 公告 ----

  function openGroupSet() {
    if (!isGroup()) return;
    const d = curGroupDetail();
    const gid = String(state.peer.id);
    els.gsSetName.value = (d && d.group_name) || groupName(gid);
    els.gsSetMute.checked = !!(d && d.mute_all);
    els.gsSetSearch.checked = !d || !!d.searchable;
    els.gsSetGid.textContent = gid;
    if (els.gsSetAvatarPreview) {
      fillGroupAvatar(els.gsSetAvatarPreview, groupName(gid), gid);
    }
    renderGroupLimits();
    els.groupSetMask.classList.remove('hidden');
  }

  function closeGroupSet() { els.groupSetMask.classList.add('hidden'); }

  async function saveGroupName() {
    const name = els.gsSetName.value.trim();
    if (!name) { toast('群名不能为空'); return; }
    try {
      await groupManage('rename', { group_id: state.peer.id, name });
      await loadGroups();
      applyPeerIdentity();
      toast('群名已修改');
    } catch (e) { toast('改名失败：' + (e.message || e)); }
  }

  async function toggleGroupMute(on) {
    try {
      await groupManage('mute', { group_id: state.peer.id, on });
      await loadGroups();
      applyPeerIdentity();
      toast(on ? '已开启全员禁言' : '已解除全员禁言');
    } catch (e) {
      els.gsSetMute.checked = !on;
      toast('操作失败：' + (e.message || e));
    }
  }

  async function toggleGroupSearch(on) {
    try {
      await groupManage('searchable', { group_id: state.peer.id, on });
      toast(on ? '已允许被搜索加入' : '已关闭搜索加入');
    } catch (e) {
      els.gsSetSearch.checked = !on;
      toast('操作失败：' + (e.message || e));
    }
  }

  function openAnnounce() {
    if (!isGroup()) return;
    const d = curGroupDetail();
    els.announceInput.value = ((d && (d.announce || {}).text) || '');
    els.announceMask.classList.remove('hidden');
    setTimeout(() => els.announceInput.focus(), 50);
  }

  function closeAnnounce() { els.announceMask.classList.add('hidden'); }

  async function saveAnnounce() {
    const text = els.announceInput.value.trim();
    if (!text) { toast('公告不能为空'); return; }
    try {
      await groupManage('announce', { group_id: state.peer.id, text });
      await loadGroupDetail(state.peer.id);
      closeAnnounce();
      toast('公告已发布，群成员都会看到');
    } catch (e) { toast('发布失败：' + (e.message || e)); }
  }

  // ---- 群界面事件绑定 ----
  function closeGroupSide() {
    els.groupSide.classList.add('hidden');
    els.groupSide.classList.remove('mobile-open');
    state.groupSideHidden = true;
  }
  function toggleGroupSide() {
    if (!isGroup()) return;
    const mobile = window.matchMedia('(max-width: 880px)').matches;
    const open = !els.groupSide.classList.contains('hidden') &&
      (!mobile || els.groupSide.classList.contains('mobile-open'));
    if (open) {
      closeGroupSide();
      return;
    }
    state.groupSideHidden = false;
    els.groupSide.classList.remove('hidden');
    if (mobile) els.groupSide.classList.add('mobile-open');
    renderGroupSide();
  }
  if (els.gsClose) els.gsClose.addEventListener('click', closeGroupSide);
  if (els.chatAvatar) els.chatAvatar.addEventListener('click', toggleGroupSide);
  if (els.gsAnnounceEdit) els.gsAnnounceEdit.addEventListener('click', openAnnounce);
  if (els.gsInvite) els.gsInvite.addEventListener('click', openInvite);
  if (els.gsMemberSearch) els.gsMemberSearch.addEventListener('input', renderGroupMembers);
  if (els.btnGroupAt) els.btnGroupAt.addEventListener('click', () => {
    if (!isGroup()) return;
    els.memberMenu.classList.add('hidden');
    atAll();
  });
  if (els.btnGroupSet) els.btnGroupSet.addEventListener('click', openGroupSet);

  els.cgClose.addEventListener('click', closeCreateGroup);
  els.cgCancel.addEventListener('click', closeCreateGroup);
  els.createGroupMask.addEventListener('click', (e) => {
    if (e.target === els.createGroupMask) closeCreateGroup();
  });
  els.cgCreate.addEventListener('click', createGroupNow);
  els.cgName.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); createGroupNow(); }
  });

  els.inviteClose.addEventListener('click', () => els.inviteMask.classList.add('hidden'));
  els.inviteMask.addEventListener('click', (e) => {
    if (e.target === els.inviteMask) els.inviteMask.classList.add('hidden');
  });
  els.inviteDone.addEventListener('click', inviteNow);

  els.gsSetClose.addEventListener('click', closeGroupSet);
  els.groupSetMask.addEventListener('click', (e) => {
    if (e.target === els.groupSetMask) closeGroupSet();
  });
  els.gsSetSaveName.addEventListener('click', saveGroupName);
  els.gsSetName.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveGroupName(); }
  });
  els.gsSetMute.addEventListener('change', () => toggleGroupMute(els.gsSetMute.checked));
  els.gsSetSearch.addEventListener('change', () => toggleGroupSearch(els.gsSetSearch.checked));
  // ---- 群聊节奏参数（滑杆，像私聊的「热情/好感」）----

  function renderGroupLimits() {
    if (!els.gsLimits || !isGroup()) return;
    const d = curGroupDetail();
    const specs = (d && d.limits) || [];
    els.gsLimits.innerHTML = '';
    if (!specs.length) {
      const empty = document.createElement('p');
      empty.className = 'cs-hint';
      empty.textContent = '参数还没读上来…';
      els.gsLimits.appendChild(empty);
      return;
    }
    for (const it of specs) {
      if (it.kind === 'bool') {
        const row = document.createElement('label');
        row.className = 'setting-row compact';
        const box = document.createElement('div');
        box.innerHTML = `<strong>${it.label}</strong>`;
        const sw = document.createElement('label');
        sw.className = 'switch';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = Number(it.value) > 0;
        cb.addEventListener('change', () => saveGroupLimit(it.key, cb.checked ? 1 : 0));
        const knob = document.createElement('i');
        sw.append(cb, knob);
        row.append(box, sw);
        els.gsLimits.appendChild(row);
        continue;
      }
      const label = document.createElement('label');
      label.className = 'trait-row';
      const nm = document.createElement('span');
      nm.className = 'trait-name';
      nm.textContent = it.label;
      const input = document.createElement('input');
      input.type = 'range';
      input.min = String(it.min);
      input.max = String(it.max);
      input.step = String(it.step || 1);
      input.value = String(it.value);
      input.dataset.limitKey = it.key;
      const val = document.createElement('span');
      val.className = 'trait-val';
      val.textContent = `${it.value}${it.unit || ''}`;
      input.addEventListener('input', () => {
        val.textContent = `${input.value}${it.unit || ''}`;
      });
      // 松手才写后端（拖动时不要连发）
      input.addEventListener('change', () => saveGroupLimit(it.key, Number(input.value)));
      label.append(nm, input, val);
      els.gsLimits.appendChild(label);
    }
  }

  async function saveGroupLimit(key, value) {
    if (!isGroup() || !key) return;
    try {
      await groupManage('limits', {
        group_id: state.peer.id, values: { [key]: value },
      });
      toast('已保存');
    } catch (e) {
      toast('保存失败：' + (e.message || e));
      await loadGroupDetail(state.peer.id);
    }
  }

  if (els.gsSetAvatar) els.gsSetAvatar.addEventListener('click', () => {
    state.avatarTarget = { kind: 'group', id: state.peer.id };
    els.groupAvatarInput.value = '';
    els.groupAvatarInput.click();
  });
  if (els.gsSetAvatarPreview) {
    els.gsSetAvatarPreview.addEventListener('click', () => {
      state.avatarTarget = { kind: 'group', id: state.peer.id };
      els.groupAvatarInput.value = '';
      els.groupAvatarInput.click();
    });
  }
  els.groupAvatarInput.addEventListener('change', () => {
    const f = els.groupAvatarInput.files && els.groupAvatarInput.files[0];
    if (f) startAvatarCrop(f);
  });

  els.announceClose.addEventListener('click', closeAnnounce);
  els.announceCancel.addEventListener('click', closeAnnounce);
  els.announceMask.addEventListener('click', (e) => {
    if (e.target === els.announceMask) closeAnnounce();
  });
  els.announceSave.addEventListener('click', saveAnnounce);

  // ---------------------------------------------------------- 在线状态（QQ 式）
  // 入口在「已连接」左边那颗状态胶囊（桌面）；移动端在顶部自己名字下面。
  // 状态是**主动性的乘数** —— 「Q我吧」会让她更主动地来找你，
  // 「离线 / 隐身」只是安静一点（不是不发），「请勿打扰」才真的完全不主动。
  // 图标一律用平面线性图标（#i-p-<key>），不用 emoji。
  const PRESENCE_FALLBACK = [
    { key: 'online', label: '在线', desc: '随时可以来找我', freq: 1 },
    { key: 'qme', label: 'Q我吧', desc: '我现在有空，来找我聊', freq: 2 },
    { key: 'away', label: '离开', desc: '暂时不在，稍微安静一点', freq: 0.6 },
    { key: 'busy', label: '忙碌', desc: '在忙，消息少一点', freq: 0.4 },
    { key: 'dnd', label: '请勿打扰', desc: '先别来打扰', freq: 0.12, silent: true },
    { key: 'invisible', label: '隐身', desc: '想安静待着，但别断联', freq: 0.35 },
    { key: 'offline', label: '离线', desc: '下线了，留言就好', freq: 0.25 },
  ];

  function presenceList() {
    return (state.presence && state.presence.statuses) || PRESENCE_FALLBACK;
  }

  function presenceIcon(key) {
    return '#i-p-' + (key || 'online');
  }

  // 建一个平面图标（<svg><use href="#i-p-xxx"/></svg>）
  function presenceSvg(key, cls) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    if (cls) svg.setAttribute('class', cls);
    const use = document.createElementNS(NS, 'use');
    use.setAttribute('href', presenceIcon(key));
    svg.appendChild(use);
    return svg;
  }

  function applyPresenceUI() {
    const p = state.presence;
    if (!p) return;
    if (els.railDot) els.railDot.dataset.p = p.status;
    if (els.mobileDot) els.mobileDot.dataset.p = p.status;
    if (els.mobileStatus) els.mobileStatus.textContent = p.label;
    if (els.mobileStatus) {
      const line = els.mobileStatus.closest('.mh-status');
      if (line) line.classList.toggle('ok', p.status === 'online' || p.status === 'qme');
    }
    if (els.railAvatar) els.railAvatar.title = `我（${p.label}）`;
    // 「已连接」左边那颗胶囊：图标 + 文字都跟着状态走
    if (els.presenceChip) {
      els.presenceChip.dataset.p = p.status;
      const use = els.presenceChip.querySelector('use');
      if (use) use.setAttribute('href', presenceIcon(p.status));
      if (els.presenceChipText) els.presenceChipText.textContent = p.label;
      els.presenceChip.title = `在线状态：${p.label}（${p.desc || ''}）`;
    }
  }

  async function loadPresence() {
    try {
      const res = await apiFetch('/api/presence', { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) return;
      state.presence = data;
      applyPresenceUI();
    } catch (e) { /* 静默：在线状态是锦上添花，取不到也不影响聊天 */ }
  }

  async function savePresence(key) {
    if (!key) return;
    try {
      const res = await apiFetch('/api/presence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: key }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      state.presence = out;
      applyPresenceUI();
      toast(out.silent ? `已切换为「${out.label}」· 先安静一会儿`
                       : `已切换为「${out.label}」`);
    } catch (e) {
      toast('切换失败：' + (e?.message || e));
    }
  }

  function openPresenceMenu(anchorEl, mode) {
    closeCtx();
    const cur = state.presence ? state.presence.status : 'online';
    els.presenceMenu.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'pm-head';
    head.textContent = '在线状态';
    els.presenceMenu.appendChild(head);

    for (const s of presenceList()) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pm-item' + (s.key === cur ? ' active' : '');
      b.dataset.p = s.key;
      const ico = presenceSvg(s.key, 'pm-ico');
      const text = document.createElement('span');
      text.className = 'pm-text';
      const label = document.createElement('span');
      label.className = 'pm-label';
      label.textContent = s.label || s.key;
      const desc = document.createElement('span');
      desc.className = 'pm-desc';
      desc.textContent = s.desc || '';
      text.appendChild(label);
      text.appendChild(desc);
      b.appendChild(ico);
      b.appendChild(text);
      if (s.freq != null && s.key !== cur) {
        const freq = document.createElement('span');
        freq.className = 'pm-freq';
        freq.textContent = '×' + s.freq;
        b.appendChild(freq);
      }
      b.addEventListener('click', () => {
        els.presenceMenu.classList.add('hidden');
        savePresence(s.key);
      });
      els.presenceMenu.appendChild(b);
    }

    els.presenceMenu.classList.remove('hidden');
    const a = anchorEl.getBoundingClientRect();
    const r = els.presenceMenu.getBoundingClientRect();
    let px = mode === 'below' ? a.left : a.right + 10;
    let py = mode === 'below' ? a.bottom + 6 : a.top - 6;
    px = Math.max(8, Math.min(px, window.innerWidth - r.width - 8));
    py = Math.max(8, Math.min(py, window.innerHeight - r.height - 8));
    els.presenceMenu.style.left = px + 'px';
    els.presenceMenu.style.top = py + 'px';
  }

  function togglePresenceMenu(anchorEl, mode) {
    if (els.presenceMenu.classList.contains('hidden')) openPresenceMenu(anchorEl, mode);
    else els.presenceMenu.classList.add('hidden');
  }

  if (els.presenceChip) {
    // 入口：主界面「已连接」左边那颗状态胶囊
    els.presenceChip.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePresenceMenu(els.presenceChip, 'below');
    });
  }
  if (els.mobilePresence) {
    els.mobilePresence.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePresenceMenu(els.mobilePresence, 'below');
    });
  }

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
      // ★ 群聊里没有「按对话的气泡设置」——以前这里会打开 state.bot（＝上一个
      //   私聊角色，实测是橘光）的设置页。群里改走群设置。
      if (isGroup()) openGroupSet();
      else openChatSettings();
    } else if (act === 'createGroup') {
      openCreateGroup();
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
        // ★ 原地清空而不是换一个新数组 —— state.msgs 与它所属会话的缓存
        //   是同一个数组，换成新数组会让两边的引用脱钩（切走切回又冒出旧消息）
        state.msgs.length = 0;
        state.byMid.clear();
        renderAll(false);
        syncConvPreview();
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

  function closeAvatarCrop() {
    els.avatarMask.classList.add('hidden');
    const c = state.avatarCrop;
    if (c && c.url) URL.revokeObjectURL(c.url);
    state.avatarCrop = null;
    // 目标也要清掉：否则下一次换别人头像时会误用上一次的目标（比如把群里
    // 的头像存到某个角色身上）
    state.avatarTarget = null;
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
    const tgt = state.avatarTarget;
    const isGrp = !!(tgt && tgt.kind === 'group');
    const key = isGrp ? ('g' + tgt.id) : String(state.bot.id);
    try {
      const res = await apiFetch('/api/avatar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: key, data: dataUrl }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      state.avatars[key] = out.url ||
        `/api/avatar?peer_id=${encodeURIComponent(key)}&v=${Date.now()}`;
      closeAvatarCrop();
      state.avatarTarget = null;
      if (isGrp) {
        renderGroupSide();
        renderConvList();
        renderContactList();
        toast('群头像已更新');
      } else {
        refreshBotAvatars();
        applyFavicon();
        toast('头像已更新');
      }
    } catch (e) {
      toast('头像保存失败：' + (e?.message || e));
    }
  }

  async function resetAvatar() {
    if (!state.bot.id) return;
    const tgt = state.avatarTarget;
    const isGrp = !!(tgt && tgt.kind === 'group');
    const key = isGrp ? ('g' + tgt.id) : String(state.bot.id);
    try {
      const res = await apiFetch('/api/avatar/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: key }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ('HTTP ' + res.status));
      delete state.avatars[key];
      state.avatarTarget = null;
      // 新增角色会恢复成导入时的原头像；星野会回到 QQ 头像
      await loadAvatars();
      if (isGrp) { renderGroupSide(); renderConvList(); renderContactList(); }
      else { refreshBotAvatars(); applyFavicon(); }
      toast('已恢复默认头像');
    } catch (e) {
      toast('恢复失败：' + (e?.message || e));
    }
  }

  function openAvatarPicker() {
    state.avatarTarget = { kind: 'peer', id: state.bot.id };
    els.avatarFileInput.value = '';
    els.avatarFileInput.click();
  }

  els.csAvatarPick.addEventListener('click', openAvatarPicker);
  els.csAvatarPreview.addEventListener('click', openAvatarPicker);
  els.csAvatar.addEventListener('click', openAvatarPicker);
  els.csAvatar.title = '点击更换头像';
  els.csAvatarReset.addEventListener('click', () => {
    state.avatarTarget = { kind: 'peer', id: state.bot.id };
    resetAvatar();
  });
  els.avatarClose.addEventListener('click', closeAvatarCrop);
  els.avatarCancel.addEventListener('click', closeAvatarCrop);
  els.avatarMask.addEventListener('click', (e) => {
    if (e.target === els.avatarMask) closeAvatarCrop();
  });
  // 「重新选择」只重开文件框，**不要**重置 avatarTarget —— 否则换群头像时点它
  // 会把目标换回上一个私聊角色，最后存到角色身上去了
  els.avatarRepick.addEventListener('click', () => {
    els.avatarFileInput.value = '';
    els.avatarFileInput.click();
  });
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
    applyChatSettingsIdentity();   // 打开前再同步一次，绝不显示上一个角色
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
    if (act === 'chatStyle') {
      if (isGroup()) openGroupSet();          // 群里没有按对话的气泡设置
      else openChatSettings();
    } else if (act === 'createGroup') openCreateGroup();
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
    if (els.memberMenu && !els.memberMenu.classList.contains('hidden') &&
        !els.memberMenu.contains(e.target)) {
      els.memberMenu.classList.add('hidden');
    }
    if (!els.moreMenu.classList.contains('hidden') && !els.moreMenu.contains(e.target) &&
        !els.btnMore.contains(e.target)) {
      els.moreMenu.classList.add('hidden');
    }
    if (!els.presenceMenu.classList.contains('hidden') &&
        !els.presenceMenu.contains(e.target) &&
        !(els.presenceChip && els.presenceChip.contains(e.target)) &&
        !(els.mobilePresence && els.mobilePresence.contains(e.target))) {
      els.presenceMenu.classList.add('hidden');
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
      if (!els.createGroupMask.classList.contains('hidden')) { closeCreateGroup(); return; }
      if (!els.inviteMask.classList.contains('hidden')) {
        els.inviteMask.classList.add('hidden'); return;
      }
      if (!els.groupSetMask.classList.contains('hidden')) { closeGroupSet(); return; }
      if (!els.announceMask.classList.contains('hidden')) { closeAnnounce(); return; }
      if (!els.memberMenu.classList.contains('hidden')) {
        els.memberMenu.classList.add('hidden'); return;
      }
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
      if (!els.presenceMenu.classList.contains('hidden')) {
        els.presenceMenu.classList.add('hidden'); return;
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
  // ---- 登录页：背景图 + 「我」的头像 ----
  // 背景默认用站点里的 23.png；用户点「更换背景」选的图存在本机 localStorage，
  // 下次打开直接生效（登录页在连接之前就要好看，不能等 WS）。
  const LS_LOGIN_BG = 'vol.loginBg';

  function applyLoginBg() {
    if (!els.connectBg) return;
    let bg = '';
    try { bg = localStorage.getItem(LS_LOGIN_BG) || ''; } catch (e) { bg = ''; }
    els.connectBg.style.backgroundImage = bg
      ? `url("${bg}")` : 'url("./23.png")';
  }

  function pickLoginBg() {
    els.connectBgInput.value = '';
    els.connectBgInput.click();
  }

  function saveLoginBg(file) {
    if (!file) return;
    if (!/^image\//.test(file.type || '')) { toast('请选择图片文件'); return; }
    if (file.size > 12 * 1024 * 1024) { toast('图片太大（上限 12MB）'); return; }
    const fr = new FileReader();
    fr.onload = () => {
      try { localStorage.setItem(LS_LOGIN_BG, String(fr.result)); } catch (e) { /* 满了就忽略 */ }
      applyLoginBg();
      toast('登录背景已更换');
    };
    fr.onerror = () => toast('读取失败');
    fr.readAsDataURL(file);
  }

  if (els.connectBgPick) els.connectBgPick.addEventListener('click', pickLoginBg);
  if (els.connectBgInput) {
    els.connectBgInput.addEventListener('change', () => {
      const f = els.connectBgInput.files && els.connectBgInput.files[0];
      saveLoginBg(f);
    });
  }

  // 登录页也要显示「我」的头像 —— 用 owner 的 QQ 头像 / 自定义头像
  async function loadLoginIdentity() {
    try {
      const res = await apiFetch('/api/identity', { cache: 'no-store' });
      if (!res.ok) return;
      const d = await res.json();
      if (!d || d.ok === false || !d.owner_id) return;
      state.me.id = Number(d.owner_id);
      state.me.name = d.owner_nickname || state.me.name;
      els.meName.textContent = state.me.name;
      els.mobileName.textContent = state.me.name;
      fillAvatar(els.brandAvatar, state.me.name, state.me.id, '我');
      fillAvatar(els.railAvatar, state.me.name, state.me.id, '我');
    } catch (e) { /* 老服务端没有这个接口 → 保留文字头像 */ }
  }

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
    applyLoginBg();
    loadLoginIdentity();
    connect();
  }

  init();
})();
