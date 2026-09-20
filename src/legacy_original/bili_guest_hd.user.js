// ==UserScript==
// @name         Bili Overdrive HD 解锁画质
// @name:en      Bili Overdrive HD - Unlock Quality
// @namespace    https://github.com/ChrAlpha/bili-overdrive-hd
// @version      1.2.0
// @description  未登录也能看 Bilibili 高画质（最高 1080P）。在文档加载早期改写播放信息，借官方 try_look 试看接口取到 1080P 流并喂给播放器，绕过未登录画质墙。原生画质菜单可真正无刷新切换任意可用分辨率，并在播放器不支持时保进度回退。自动锁最高、记忆偏好。
// @description:en  Watch Bilibili in high quality (up to 1080P) while logged out. Injects the official `try_look` preview streams into the player's playinfo at document-start. The native quality menu switches in place across every available representation, with a resume-preserving fallback when the live player cannot. Auto-locks the highest quality and remembers your choice.
// @author       ChrAlpha
// @match        https://www.bilibili.com/video/*
// @match        https://www.bilibili.com/bangumi/play/*
// @match        https://www.bilibili.com/festival/*
// @match        https://www.bilibili.com/list/*
// @run-at       document-start
// @noframes
// @grant        GM_setValue
// @grant        GM_getValue
// @license      MIT
// @homepageURL  https://github.com/ChrAlpha/bili-overdrive-hd
// ==/UserScript==

/*
 * How it works (and why it's built this way)
 * ------------------------------------------
 * Bilibili gates high quality for logged-out users at TWO layers:
 *
 *   1. Backend: a plain anonymous playurl request only returns up to 480P
 *      (qn=32). BUT the official "试看/试用" parameter `try_look=1` makes the
 *      same anonymous request return real 1080P (qn=80) DASH streams. This is
 *      Bilibili's own preview path — verified reproducibly. (1080P+ / 60fps /
 *      4K / HDR still require login + 大会员; those are a real backend wall.)
 *
 *   2. Frontend: the web player will NOT freely switch *up* to >480P while
 *      logged out. Its optional "试看30秒" action also starts a wall-clock
 *      downgrade timer, while a direct `requestQuality(80)` is denied.
 *
 * The robust way through both layers: the first playinfo is server-side
 * rendered into the page as `window.__playinfo__`. At document-start we install
 * a setter on it; when Bilibili assigns the (480P-capped) object, we do a
 * synchronous `try_look=1` request, swap the 1080P DASH/qualities into that
 * object *before the player ever reads it*, and set `quality` to our target.
 * The player then *initialises* at 1080P — which sidesteps the "switch-up" gate
 * entirely (it's the starting quality, not an up-switch).
 *
 * For in-place SPA navigation (playlist / 番剧 episode switch in the same tab),
 * there is no fresh SSR `__playinfo__`; the player fetches playurl over the
 * network. A `fetch` / `XHR` hook replaces those responses with our own
 * `try_look` result. Our own requests go to the *unsigned* `/x/player/playurl`
 * endpoint, which needs no WBI signature — so we never fight signing.
 *
 * Manual quality selection: the public `requestQuality()` gate still stops
 * logged-out up-switches above 480P. The DASH kernel behind that facade already
 * has every representation injected above, though, and exposes the same
 * `setQualityFor()` primitive used by the native seamless path. We feature-test
 * that live manifest and switch video/audio representations in place. If the
 * live manifest does not contain the target, playback is left untouched. The
 * proven document-start reload path remains a fallback for incompatible or
 * failed kernel APIs.
 */

(function () {
  'use strict';

  /* ------------------------------------------------------------------ *
   * Pure helpers (no browser deps) — also exported for Node unit tests. *
   * ------------------------------------------------------------------ */
  const QN_LABEL = { 16: '360P', 32: '480P', 64: '720P', 80: '1080P', 112: '1080P 高码率', 116: '1080P60', 120: '4K' };

  // Which fallback a target qn has, given our ceiling:
  //   instant — DASH first, public requestQuality remains available (<=480P)
  //   dash    — switch the already-injected DASH representation in place
  //   blocked — above the ceiling try_look can reach (1080P+ / 4K / HDR / 杜比)
  function qnTier(qn, maxQn) {
    const n = Number(qn);
    if (!Number.isFinite(n) || n <= 32) return 'instant';
    if (n <= maxQn) return 'dash';
    return 'blocked';
  }

  function buildDashSwitchPlan(videoEntries, audioEntries, currentQn, targetQn) {
    const current = Number(currentQn);
    const target = Number(targetQn);
    if (!Number.isFinite(current) || !Number.isFinite(target) || !Array.isArray(videoEntries)) return null;
    const videoIds = videoEntries.map((entry) => Number(entry && entry.id)).filter(Number.isFinite);
    if (!videoIds.includes(current) || !videoIds.includes(target)) return null;
    const wantedAudio = target <= 32 ? 30216 : (target < 80 ? 30232 : 30280);
    const audioIds = Array.isArray(audioEntries)
      ? audioEntries.map((entry) => Number(entry && entry.id)).filter(Number.isFinite)
      : [];
    return {
      videoQn: target,
      audioQn: audioIds.includes(wantedAudio) ? wantedAudio : null,
    };
  }

  function dashSwitchErrorStatus(errorCode, currentQn, targetQn) {
    const code = Number(errorCode);
    if (code === 20004) {
      return Number(currentQn) === Number(targetQn) ? 'switched' : 'busy';
    }
    if (code === 20003 || code === 20006 || code === 20008) return 'busy';
    if (code === 20005) return 'timeout';
    return 'failed';
  }

  // Same-page URL with the playback position pinned via Bilibili's ?t= param,
  // preserving every other query param (?p= multi-part, playlist ids, …).
  function buildResumeUrl(href, timeSec) {
    const u = new URL(href);
    u.searchParams.set('t', String(Math.max(0, Math.floor(Number(timeSec) || 0))));
    return u.toString();
  }

  // qn from a menu item's visible label (fallback when data-value is absent).
  function qnFromLabel(text) {
    if (/1080P\s*(高码率|杜比|HDR)/.test(text)) return 112; // > our ceiling; ignore below
    if (/1080P/.test(text)) return 80;
    if (/720P/.test(text)) return 64;
    if (/480P/.test(text)) return 32;
    if (/360P/.test(text)) return 16;
    return null; // 自动 / unknown -> leave memory alone
  }

  // Merge the narrow player setting that prevents background tabs from
  // discarding the video buffer and rebuilding it at the anonymous qn.
  function disableAudioOnlyConfig(raw) {
    const isObject = (value) => value && typeof value === 'object' && !Array.isArray(value);
    let root = {};
    if (raw != null && raw !== '') {
      try { root = JSON.parse(raw); } catch (e) { return null; }
      if (!isObject(root)) return null;
    }
    const dash = root.dash_config == null ? {} : root.dash_config;
    if (!isObject(dash)) return null;
    const audioOnly = dash.audio_only_config == null ? {} : dash.audio_only_config;
    if (!isObject(audioOnly)) return null;
    return JSON.stringify({
      ...root,
      dash_config: {
        ...dash,
        audio_only_config: { ...audioOnly, enabled: false },
      },
    });
  }

  // Give this document a virtual view of the one player setting we need. The
  // origin-wide stored value is never changed, so other tabs and later visits
  // keep their own Bilibili preference.
  function installAudioOnlyReadPolicy(storage, storageProto, key, shouldApply) {
    try {
      const original = storageProto && storageProto.getItem;
      if (typeof original !== 'function') return null;
      const wrapped = function (name) {
        const raw = original.apply(this, arguments);
        if (this !== storage || name !== key) return raw;
        try { if (!shouldApply()) return raw; }
        catch (e) { return raw; }
        const patched = disableAudioOnlyConfig(raw);
        return patched == null ? raw : patched;
      };
      storageProto.getItem = wrapped;
      if (storageProto.getItem !== wrapped) return null;
      let active = true;
      return function restore() {
        if (!active) return;
        active = false;
        try { if (storageProto.getItem === wrapped) storageProto.getItem = original; }
        catch (e) { /* another script owns the method now */ }
      };
    } catch (e) {
      return null;
    }
  }

  // The native trial should only be suppressed while an injected high-quality
  // stream is actually selected or rendered, never after a manual down-switch.
  function isHighPlaybackActive(quality, videoWidth, videoHeight) {
    const pending = Number(quality && quality.newQ);
    const real = Number(quality && quality.realQ);
    const current = Number(quality && quality.nowQ);
    if ((Number.isFinite(pending) && pending > 0 && pending <= 32) ||
        (Number.isFinite(real) && real > 0 && real <= 32) ||
        (Number.isFinite(current) && current > 0 && current <= 32)) return false;
    if (Number.isFinite(real) && real > 32) return true;
    if (Number.isFinite(current) && current > 32) return true;
    const width = Number(videoWidth);
    const height = Number(videoHeight);
    if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
      return Math.min(width, height) > 480;
    }
    return false;
  }

  // Node-only test hook: export the pure helpers and stop before any browser
  // code. This branch never runs in a browser or userscript sandbox.
  if (typeof process !== 'undefined' && process.versions && process.versions.node &&
      typeof module !== 'undefined' && module.exports) {
    module.exports = {
      qnTier,
      buildResumeUrl,
      qnFromLabel,
      disableAudioOnlyConfig,
      installAudioOnlyReadPolicy,
      isHighPlaybackActive,
      buildDashSwitchPlan,
      dashSwitchErrorStatus,
    };
    return;
  }

  // Top frame only; the player lives in the main document. @noframes covers
  // this too, but be defensive.
  if (typeof window === 'undefined' || window.top !== window.self) return;
  window.__mabaoBiliOverdriveLoaded = true;

  /* ------------------------------------------------------------------ *
   * Config.                                                             *
   * ------------------------------------------------------------------ */
  const CONFIG = {
    // Hard ceiling. try_look only unlocks up to 1080P (qn 80). 1080P+ (112),
    // 1080P60 (116), 4K (120), HDR/Dolby need login + 大会员 — unreachable.
    maxQn: 80,
    storeNs: 'biliOverdriveHd',
    toast: true, // brief "已解锁 1080P" hint when injection succeeds
    debug: false,
  };

  // Quality codes, low -> high, that we ever target.
  const QN_LADDER = [16, 32, 64, 80];

  const LOGIN_UI_SELECTORS = [
    '.bili-mini-mask', '.bili-mini-content-wp', '.bili-mini-login-right-wp',
    '.bili-mini-customer-title', '.bili-mini-close-icon',
    '[role="dialog"][class*="login"]', '[class*="login-mask"]',
    '[class*="login-panel"]', '[class*="login-popover"]',
    '.bpx-player-toast-confirm-login',
    '.bpx-player-toast-wrap:has(.bpx-player-toast-confirm-login)',
  ];

  /* ------------------------------------------------------------------ *
   * Logged-in users already get >=1080P natively — stand down so we     *
   * never interfere with their account / 大会员 streams.                 *
   * ------------------------------------------------------------------ */
  // The embedded local profile can retain a stale DedeUserID without a valid
  // login session. Always use the anonymous preview path in this application.

  // Patch the page's real objects, not the userscript sandbox's view.
  const win = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;
  const diagnostics = {
    fetchIntercepts: 0, xhrIntercepts: 0, lastUrl: '', apiCode: null,
    hasDash: false, pickedQn: 0, initialStateIntercepts: 0, error: '',
  };
  win.__mabaoBiliDiagnostics = diagnostics;

  // Single-instance guard: a sentinel on <html> is shared across sandbox
  // realms and always writable, so double-installs (e.g. HD + another fork)
  // can't both run.
  try {
    const root = document.documentElement;
    if (root) {
      if (root.hasAttribute('data-bili-overdrive-hd')) return;
      root.setAttribute('data-bili-overdrive-hd', '1');
    }
  } catch (e) { /* ignore */ }

  /* ------------------------------------------------------------------ *
   * Storage — GM_setValue/GM_getValue with a localStorage fallback.     *
   * (Same shape as the sibling speed script.)                           *
   * ------------------------------------------------------------------ */
  const store = {
    get(key, def) {
      try {
        if (typeof GM_getValue === 'function') {
          const v = GM_getValue(CONFIG.storeNs + '.' + key);
          return v === undefined ? def : v;
        }
      } catch (e) { /* ignore */ }
      try {
        const raw = localStorage.getItem(CONFIG.storeNs + '.' + key);
        return raw == null ? def : JSON.parse(raw);
      } catch (e) { return def; }
    },
    set(key, val) {
      try {
        if (typeof GM_setValue === 'function') {
          GM_setValue(CONFIG.storeNs + '.' + key, val);
          return;
        }
      } catch (e) { /* ignore */ }
      try {
        localStorage.setItem(CONFIG.storeNs + '.' + key, JSON.stringify(val));
      } catch (e) { /* ignore */ }
    },
  };

  const log = (...a) => { if (CONFIG.debug) try { console.log('[BOD-HD]', ...a); } catch (e) {} };

  // This local build is deliberately pinned to the highest anonymous stream.
  function targetQn() {
    return CONFIG.maxQn;
  }

  store.set('qn', CONFIG.maxQn);

  function installLoginUiPolicy() {
    const styleId = 'mabao-local-login-ui-policy';
    const installStyle = () => {
      if (document.getElementById(styleId)) return;
      const host = document.head || document.documentElement;
      if (!host) return;
      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = LOGIN_UI_SELECTORS.join(',') +
        '{display:none!important;visibility:hidden!important;pointer-events:none!important}';
      host.appendChild(style);
    };
    const clean = () => {
      installStyle();
      document.querySelectorAll(LOGIN_UI_SELECTORS.join(',')).forEach((node) => {
        if (!node.hasAttribute('data-mabao-hidden-login')) {
          node.setAttribute('data-mabao-hidden-login', 'true');
        }
      });
    };
    const observe = () => {
      if (!document.documentElement) return;
      clean();
      new MutationObserver(clean).observe(document.documentElement, {
        childList: true, subtree: true, attributes: true,
        attributeFilter: ['class', 'style', 'hidden'],
      });
    };
    if (document.documentElement) observe();
    else document.addEventListener('DOMContentLoaded', observe, { once: true });
    document.addEventListener('fullscreenchange', clean, true);
    win.addEventListener('resize', clean, { passive: true });
  }

  // Bilibili normally removes the video buffer after a hidden-tab timeout and
  // rebuilds it at the anonymous qn when the tab returns. For this document
  // only, expose that built-in optimization as disabled whenever HD is the
  // target; the bounded quality guard below handles later player rebuilds.
  try {
    const storage = win.localStorage;
    const PageObject = win.Object || Object;
    installAudioOnlyReadPolicy(
      storage,
      PageObject.getPrototypeOf(storage),
      'bilibili_player_kv_config',
      () => targetQn() > 32,
    );
  } catch (e) { /* keep the normal player path if storage is unavailable */ }

  let injectedHighQn = 0;
  let replacementRequestGeneration = 0;
  function setInjectedHighQn(qn) {
    const n = Number(qn);
    injectedHighQn = Number.isFinite(n) && n > 32 ? n : 0;
    win.__mabaoInjectedHighQn = injectedHighQn;
  }

  /* ------------------------------------------------------------------ *
   * Pure-ish helpers around the playurl API.                            *
   * ------------------------------------------------------------------ */
  const XHR = win.XMLHttpRequest || window.XMLHttpRequest;

  const isBangumi = () => location.pathname.indexOf('/bangumi/play/') === 0;
  const isUgcPlayurl = (u) => /\/x\/player\/(wbi\/)?playurl/.test(u);
  const isPgcPlayurl = (u) => /\/pgc\/player\/web\/playurl/.test(u);

  // Sentinel marking our *own* requests so the net hook doesn't re-intercept
  // them (infinite-loop guard).
  const OWN_FLAG = '_bohd';

  // Pull the cid out of a DASH stream's media URL, e.g.
  //   .../upgcxcode/99/91/137649199/137649199_da2-1-100023.m4s  -> 137649199
  function cidFromDash(data) {
    try {
      const v = (data.dash && data.dash.video && data.dash.video[0]) || null;
      const bu = v ? (v.baseUrl || v.base_url || (v.backupUrl && v.backupUrl[0]) || '') : '';
      const m = bu.match(/upgcxcode\/\d+\/\d+\/(\d+)\//) || bu.match(/\/(\d{6,})[_/]/);
      return m ? m[1] : null;
    } catch (e) { return null; }
  }

  function bvidFromLocation() {
    const m = location.pathname.match(/\/(BV[0-9A-Za-z]+)/) ||
      (location.search.match(/[?&]bvid=(BV[0-9A-Za-z]+)/) || []);
    return m ? (m[1] || m[0].split('=')[1]) : null;
  }

  function epidFromLocation() {
    const m = location.pathname.match(/\/ep(\d+)/) || location.search.match(/[?&]ep_id=(\d+)/);
    return m ? m[1] : null;
  }

  // Build an unsigned try_look playurl URL. The non-WBI / pgc endpoints accept
  // anonymous requests with just a Referer + UA (the page provides both), so we
  // never need to compute a WBI signature.
  function buildHiUrl({ bvid, avid, cid, epid }, pgc, qn) {
    const base = pgc
      ? 'https://api.bilibili.com/pgc/player/web/playurl'
      : 'https://api.bilibili.com/x/player/playurl';
    const q = new URLSearchParams();
    if (pgc) { if (epid) q.set('ep_id', epid); } else { if (bvid) q.set('bvid', bvid); }
    if (!pgc && !bvid && avid) q.set('avid', avid);
    if (cid) q.set('cid', cid);
    q.set('qn', String(qn || CONFIG.maxQn));
    q.set('fnval', '4048');
    q.set('fnver', '0');
    q.set('fourk', '1');
    q.set('try_look', '1');
    q.set(OWN_FLAG, '1');
    return base + '?' + q.toString();
  }

  function parsePlayurlParams(url) {
    let sp;
    try { sp = new URL(url, location.href).searchParams; } catch (e) { return {}; }
    return {
      bvid: sp.get('bvid'),
      avid: sp.get('avid') || sp.get('aid'),
      cid: sp.get('cid'),
      epid: sp.get('ep_id'),
    };
  }

  function getData(json) { return json && (json.data || json.result); }

  // Highest streamable id that we're allowed to start at: present in the DASH
  // list, <= our target, and <= ceiling.
  function pickStartQn(data, want) {
    try {
      const ids = (data.dash && data.dash.video) ? data.dash.video.map((v) => v.id) : [];
      const cap = Math.min(want || CONFIG.maxQn, CONFIG.maxQn);
      const ok = ids.filter((id) => id <= cap);
      return ok.length ? Math.max.apply(null, ok) : (ids.length ? Math.max.apply(null, ids) : data.quality);
    } catch (e) { return data.quality; }
  }

  // Does this hi-quality payload actually beat what we already have?
  function hasHigher(hiData, origData) {
    try {
      const hi = (hiData.dash && hiData.dash.video) ? Math.max.apply(null, hiData.dash.video.map((v) => v.id)) : 0;
      const cur = (origData && origData.dash && origData.dash.video) ? Math.max.apply(null, origData.dash.video.map((v) => v.id)) : 0;
      const hiStart = pickStartQn(hiData, CONFIG.maxQn);
      const currentStart = Number(origData && origData.quality) || 0;
      return hi > cur || hiStart > currentStart;
    } catch (e) { return false; }
  }

  // Swap the stream-bearing fields of `dst` with `hi`, and set the starting
  // quality. Everything else in `dst` (session, resume info, …) is preserved.
  function mergeHi(dst, hi, want) {
    dst.dash = hi.dash;
    dst.accept_quality = hi.accept_quality;
    dst.accept_description = hi.accept_description;
    if (hi.support_formats) dst.support_formats = hi.support_formats;
    dst.quality = pickStartQn(hi, want);
    return dst;
  }

  // Synchronous fetch — used inside the __playinfo__ setter so the 1080P data
  // is ready *before* the player reads it (we must win that race). Anonymous;
  // no credentials needed for try_look.
  function syncGetJson(url) {
    try {
      const x = new XHR();
      x.open('GET', url, false);
      x.send(null);
      if (x.status >= 200 && x.status < 300) return JSON.parse(x.responseText);
    } catch (e) { log('syncGet failed', e); }
    return null;
  }

  /* ------------------------------------------------------------------ *
   * Layer 1 — inject 1080P into the SSR __playinfo__ at document-start.  *
   * ------------------------------------------------------------------ */
  function installPlayinfoHook() {
    let real;
    try {
      Object.defineProperty(win, '__playinfo__', {
        configurable: true,
        get() { return real; },
        set(v) {
          try {
            const d = getData(v);
            if (d && d.dash) {
              setInjectedHighQn(0);
              const pgc = isBangumi();
              const cid = cidFromDash(d);
              const want = targetQn();
              const preparedQn = pickStartQn(d, want);
              if (Number(d.quality) >= want && preparedQn >= want) {
                d.quality = preparedQn;
                setInjectedHighQn(d.quality);
                scheduleToast(d.quality);
              } else {
                const url = buildHiUrl({
                  bvid: bvidFromLocation(),
                  cid: cid,
                  epid: epidFromLocation(),
                }, pgc, CONFIG.maxQn);
                const hi = cid ? getData(syncGetJson(url)) : null;
                if (hi && hasHigher(hi, d)) {
                  mergeHi(d, hi, want);
                  setInjectedHighQn(d.quality);
                  log('injected SSR playinfo', d.quality, d.accept_quality);
                  scheduleToast(d.quality);
                } else {
                  log('no higher stream available for SSR playinfo', { cid: cid, hi: !!hi });
                }
              }
            }
          } catch (e) { log('playinfo setter error', e); }
          real = v;
        },
      });
    } catch (e) { log('failed to hook __playinfo__', e); }
  }

  function installInitialStateHook() {
    let state;
    const existingState = win.__INITIAL_STATE__;
    try {
      Object.defineProperty(win, '__INITIAL_STATE__', {
        configurable: true,
        get() { return state; },
        set(value) {
          state = value;
          diagnostics.initialStateIntercepts += 1;
          try {
            const videoData = value && value.videoData;
            const bvid = (value && value.bvid) || (videoData && videoData.bvid) || null;
            const page = Math.max(1, Number(new URLSearchParams(location.search).get('p')) || 1);
            const pages = videoData && Array.isArray(videoData.pages) ? videoData.pages : [];
            const cid = (value && value.cid) || (pages[page - 1] && pages[page - 1].cid) ||
              (videoData && videoData.cid) || null;
            if (!bvid || !cid) return;
            const url = buildHiUrl({ bvid: bvid, cid: cid }, false, CONFIG.maxQn);
            diagnostics.lastUrl = url;
            const high = syncGetJson(url);
            const data = getData(high);
            diagnostics.apiCode = Number(high && high.code);
            diagnostics.hasDash = !!(data && data.dash);
            if (!data || !data.dash) return;
            data.quality = pickStartQn(data, CONFIG.maxQn);
            diagnostics.pickedQn = data.quality;
            if (data.quality >= CONFIG.maxQn) {
              setInjectedHighQn(data.quality);
              win.__playinfo__ = high;
            }
          } catch (error) {
            diagnostics.error = String(error && (error.message || error));
          }
        },
      });
      if (existingState !== undefined) {
        win.__INITIAL_STATE__ = existingState;
        const recoveryKey = CONFIG.storeNs + '.documentStartRecovery.' + location.pathname;
        if (win.player && sessionStorage.getItem(recoveryKey) !== '1') {
          sessionStorage.setItem(recoveryKey, '1');
          setTimeout(() => location.reload(), 0);
        }
      }
    } catch (error) {
      diagnostics.error = String(error && (error.message || error));
    }
  }

  /* ------------------------------------------------------------------ *
   * Layer 2 — replace playurl responses for in-place SPA navigation     *
   * (playlist next / 番剧 episode switch in the same tab).              *
   * ------------------------------------------------------------------ */

  // Fetch our own try_look payload, shaped like a real API response, with the
  // starting quality forced to our target. Returns a JSON string or null.
  async function buildReplacementBody(origUrl, origFetch) {
    const generation = ++replacementRequestGeneration;
    setInjectedHighQn(0);
    const pgc = isPgcPlayurl(origUrl);
    const want = targetQn();
    const url = buildHiUrl(parsePlayurlParams(origUrl), pgc, CONFIG.maxQn);
    diagnostics.lastUrl = url;
    try {
      const resp = await origFetch(url, { credentials: 'omit' });
      const json = await resp.json();
      const d = getData(json);
      diagnostics.apiCode = Number(json && json.code);
      diagnostics.hasDash = !!(d && d.dash);
      if (!d || !d.dash) return null;
      d.quality = pickStartQn(d, want);
      diagnostics.pickedQn = d.quality;
      if (generation === replacementRequestGeneration) setInjectedHighQn(d.quality);
      return JSON.stringify(json);
    } catch (e) {
      diagnostics.error = String(e && (e.message || e));
      log('replacement fetch failed', e);
      return null;
    }
  }

  function installFetchHook() {
    const origFetch = win.fetch;
    if (typeof origFetch !== 'function') return;
    win.fetch = function (input, init) {
      let url = '';
      try { url = (typeof input === 'string') ? input : (input && input.url) || ''; } catch (e) {}
      if (url && url.indexOf(OWN_FLAG + '=1') === -1 && (isUgcPlayurl(url) || isPgcPlayurl(url))) {
        diagnostics.fetchIntercepts += 1;
        return buildReplacementBody(url, origFetch).then((body) => {
          if (body == null) return origFetch(input, init);
          log('replaced fetch playurl response');
          return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } });
        });
      }
      return origFetch(input, init);
    };
  }

  // XHR shim: take over playurl requests, serve our own try_look body, and
  // expose it through the standard responseText/response getters so the player
  // reads our enriched data. Falls back to a normal request on any error.
  function installXhrHook() {
    const proto = (win.XMLHttpRequest && win.XMLHttpRequest.prototype) || null;
    if (!proto || proto.__bohdPatched) return;
    proto.__bohdPatched = true;
    const origOpen = proto.open;
    const origSend = proto.send;
    const origFetch = win.fetch; // for our own replacement fetch

    proto.open = function (method, url) {
      try {
        if (typeof url === 'string' && url.indexOf(OWN_FLAG + '=1') === -1 &&
            (isUgcPlayurl(url) || isPgcPlayurl(url))) {
          diagnostics.xhrIntercepts += 1;
          this.__bohdUrl = url;
        } else {
          this.__bohdUrl = null;
        }
      } catch (e) { this.__bohdUrl = null; }
      return origOpen.apply(this, arguments);
    };

    proto.send = function (body) {
      const self = this;
      const target = self.__bohdUrl;
      if (!target || typeof origFetch !== 'function') return origSend.apply(self, arguments);

      buildReplacementBody(target, origFetch).then((text) => {
        if (text == null) { origSend.call(self, body); return; }
        try {
          const def = (name, value) => Object.defineProperty(self, name, { configurable: true, get: () => value });
          def('responseText', text);
          def('response', (self.responseType === 'json') ? JSON.parse(text) : text);
          def('status', 200);
          def('statusText', 'OK');
          def('readyState', 4);
          def('responseURL', target);
          log('replaced XHR playurl response');
          const fire = (type) => { try { self.dispatchEvent(new Event(type)); } catch (e) {} };
          if (typeof self.onreadystatechange === 'function') { try { self.onreadystatechange(new Event('readystatechange')); } catch (e) {} }
          fire('readystatechange');
          fire('load');
          fire('loadend');
        } catch (e) { log('XHR shim failed, falling back', e); origSend.call(self, body); }
      }, () => origSend.call(self, body));
    };
  }

  /* ------------------------------------------------------------------ *
   * Quality selection — make the native menu really switch for logged-  *
   * out users.                                                          *
   *   • Every available qn: switch the live DASH video/audio tracks.     *
   *   • <=480P keeps requestQuality as a legacy-player fallback.         *
   *   • A missing target keeps playing; incompatible cores may reload.  *
   *   • 1080P+ (112) and up: genuinely 大会员-only; not reachable.       *
   * ------------------------------------------------------------------ */
  const RESUME_NS = CONFIG.storeNs + '.resume';
  const DASH_SWITCH_TIMEOUT_MS = 25000;
  let qualitySwitchInFlight = null;
  let audioSwitchInFlight = null;

  function qualitySwitchBusy() {
    return !!(qualitySwitchInFlight || audioSwitchInFlight);
  }

  // qn a menu <li> targets: prefer the stable data-value, fall back to label.
  function qnFromItem(item) {
    const dv = item.getAttribute && item.getAttribute('data-value');
    if (dv != null && dv !== '') {
      const n = Number(dv);
      if (Number.isFinite(n)) return n; // 0 == 自动
    }
    return qnFromLabel((item.textContent || '').trim());
  }

  function readPlayback() {
    try {
      const v = win.player && typeof win.player.mediaElement === 'function' ? win.player.mediaElement() : null;
      if (v) return { t: v.currentTime || 0, paused: !!v.paused };
    } catch (e) { /* ignore */ }
    return { t: 0, paused: false };
  }

  function saveResume(t, paused) {
    try {
      sessionStorage.setItem(RESUME_NS, JSON.stringify({
        path: location.pathname, t: Math.floor(t || 0), paused: !!paused, exp: Date.now() + 60000,
      }));
    } catch (e) { /* ignore */ }
  }

  // After a switch-reload, ?t= usually restores the position; this is the
  // belt-and-suspenders fallback (e.g. pages that ignore ?t=).
  function applyResume() {
    let info;
    try { info = JSON.parse(sessionStorage.getItem(RESUME_NS) || 'null'); } catch (e) { return; }
    if (!info || info.path !== location.pathname || Date.now() > info.exp) return;
    try { sessionStorage.removeItem(RESUME_NS); } catch (e) { /* ignore */ }
    let n = 0;
    const timer = setInterval(() => {
      const p = win.player;
      const v = p && typeof p.mediaElement === 'function' ? p.mediaElement() : null;
      if (v && v.readyState >= 1) {
        if (info.t > 1 && Math.abs((v.currentTime || 0) - info.t) > 2) {
          try { v.currentTime = info.t; } catch (e) { /* ignore */ }
        }
        if (info.paused) { try { v.pause(); } catch (e) { /* ignore */ } }
        clearInterval(timer);
      }
      if (++n > 40) clearInterval(timer); // ~20s ceiling
    }, 500);
  }

  // Do not expose login, trial, or paid-account prompts in the quality menu.
  function relabelMenu(root) {
    const items = (root || document).querySelectorAll('.bpx-player-ctrl-quality-menu-item');
    items.forEach((item) => {
      const qn = qnFromItem(item);
      const badge = item.querySelector('.bpx-player-ctrl-quality-badge');
      if (qn != null && qn <= CONFIG.maxQn && badge) {
        badge.textContent = '';
        badge.style.setProperty('display', 'none', 'important');
      } else if (qn != null && qn > CONFIG.maxQn) {
        item.style.setProperty('display', 'none', 'important');
      }
    });
  }

  function coreQualityQn(core, type) {
    const index = core.getQualityFor(type);
    return Number(core.getQualityNumberFromQualityIndex(index, type));
  }

  function reloadForQuality(qn) {
    const pb = readPlayback();
    saveResume(pb.t, pb.paused);
    showToast('当前播放器需重新载入，正在切到 ' + (QN_LABEL[qn] || (qn + 'P')) + '…');
    try { location.href = buildResumeUrl(location.href, pb.t); }
    catch (e) { location.reload(); }
  }

  async function switchDashQuality(qn) {
    if (audioSwitchInFlight) return { status: 'busy' };
    let player;
    let core;
    let video;
    try {
      player = win.player;
      core = player && typeof player.__core === 'function' ? player.__core() : null;
      video = player && typeof player.mediaElement === 'function' ? player.mediaElement() : null;
      if (!core || !video ||
          typeof core.getQualityList !== 'function' ||
          typeof core.getQualityFor !== 'function' ||
          typeof core.getQualityNumberFromQualityIndex !== 'function' ||
          typeof core.setAutoSwitchQualityFor !== 'function' ||
          typeof core.setQualityFor !== 'function') {
        return { status: 'unavailable' };
      }
    } catch (e) {
      return { status: 'unavailable' };
    }

    let plan;
    let currentVideoQn;
    let currentAudioQn;
    let videoAuto;
    let audioAuto;
    try {
      currentVideoQn = coreQualityQn(core, 'video');
      currentAudioQn = coreQualityQn(core, 'audio');
      const videoEntries = core.getQualityList('video');
      plan = buildDashSwitchPlan(
        videoEntries,
        core.getQualityList('audio'),
        currentVideoQn,
        qn,
      );
      if (!plan) {
        const target = Number(qn);
        const hasCurrent = Array.isArray(videoEntries) &&
          videoEntries.some((entry) => Number(entry && entry.id) === currentVideoQn);
        const hasTarget = Array.isArray(videoEntries) &&
          videoEntries.some((entry) => Number(entry && entry.id) === target);
        return {
          status: !hasTarget ? 'unsupported' : (!hasCurrent ? 'busy' : 'unavailable'),
        };
      }
      const quality = player.getQuality && player.getQuality();
      const nowQ = Number(quality && quality.nowQ);
      const newQ = Number(quality && quality.newQ);
      const nowA = Number(quality && quality.nowA);
      const newA = Number(quality && quality.newA);
      if ((Number.isFinite(nowQ) && Number.isFinite(newQ) && nowQ !== newQ) ||
          (Number.isFinite(nowA) && Number.isFinite(newA) && nowA !== newA)) {
        return { status: 'busy' };
      }
      videoAuto = core.getAutoSwitchQualityFor && core.getAutoSwitchQualityFor('video');
      audioAuto = core.getAutoSwitchQualityFor && core.getAutoSwitchQualityFor('audio');
    } catch (e) {
      return { status: 'unavailable' };
    }

    const pageUrl = location.href;
    const restoreAuto = () => {
      try {
        if (typeof videoAuto === 'boolean') core.setAutoSwitchQualityFor('video', videoAuto);
        if (typeof audioAuto === 'boolean') core.setAutoSwitchQualityFor('audio', audioAuto);
      } catch (e) { /* old core may already be disposed */ }
    };

    let videoTask;
    let audioTask = null;
    try {
      core.setAutoSwitchQualityFor('video', false);
      videoTask = currentVideoQn === plan.videoQn
        ? Promise.resolve(null)
        : Promise.resolve(core.setQualityFor('video', plan.videoQn, 20));
      if (plan.audioQn != null && currentAudioQn !== plan.audioQn) {
        core.setAutoSwitchQualityFor('audio', false);
        audioTask = Promise.resolve(core.setQualityFor('audio', plan.audioQn, 20));
        let audioMonitor = null;
        let audioTimeout = null;
        let trackedAudioTask;
        const audioSettled = audioTask.then(
          () => ({ type: 'settled' }),
          (error) => ({ type: 'failed', error }),
        );
        const audioCoreChanged = new Promise((resolve) => {
          audioMonitor = setInterval(() => {
            try {
              const livePlayer = win.player;
              const liveCore = livePlayer && typeof livePlayer.__core === 'function'
                ? livePlayer.__core()
                : null;
              if (liveCore !== core) resolve({ type: 'core-changed' });
            } catch (error) {
              resolve({ type: 'core-changed' });
            }
          }, 250);
        });
        const audioTimedOut = new Promise((resolve) => {
          audioTimeout = setTimeout(
            () => resolve({ type: 'timeout' }),
            DASH_SWITCH_TIMEOUT_MS,
          );
        });
        trackedAudioTask = Promise.race([audioSettled, audioCoreChanged, audioTimedOut])
          .then((outcome) => {
            if (outcome.type === 'failed') log('DASH audio switch failed', outcome.error);
            if (outcome.type === 'timeout') log('DASH audio switch timed out', plan.audioQn);
          })
          .finally(() => {
            clearInterval(audioMonitor);
            clearTimeout(audioTimeout);
            if (audioSwitchInFlight === trackedAudioTask) audioSwitchInFlight = null;
          });
        audioSwitchInFlight = trackedAudioTask;
      }
    } catch (e) {
      restoreAuto();
      return { status: 'failed', error: e };
    }

    let monitor = null;
    let timeout = null;
    let sourceChanged = false;
    const settled = videoTask.then(
      (value) => ({ type: 'settled', result: { status: 'fulfilled', value } }),
      (reason) => ({ type: 'settled', result: { status: 'rejected', reason } }),
    );
    const changed = new Promise((resolve) => {
      monitor = setInterval(() => {
        try {
          const livePlayer = win.player;
          const liveCore = livePlayer && typeof livePlayer.__core === 'function'
            ? livePlayer.__core()
            : null;
          const liveVideo = livePlayer && typeof livePlayer.mediaElement === 'function'
            ? livePlayer.mediaElement()
            : null;
          if (location.href !== pageUrl ||
              livePlayer !== player ||
              liveCore !== core ||
              liveVideo !== video) {
            if (liveCore !== core) {
              resolve({ type: 'canceled' });
            } else {
              sourceChanged = true;
            }
          }
        } catch (e) {
          resolve({ type: 'canceled' });
        }
      }, 250);
    });
    const timedOut = new Promise((resolve) => {
      timeout = setTimeout(() => resolve({ type: 'timeout' }), DASH_SWITCH_TIMEOUT_MS);
    });
    const outcome = await Promise.race([settled, changed, timedOut]);
    clearInterval(monitor);
    clearTimeout(timeout);

    if (outcome.type === 'canceled') {
      return { status: 'canceled' };
    }
    if (outcome.type === 'timeout') {
      if (sourceChanged) return { status: 'canceled' };
      try {
        if (coreQualityQn(core, 'video') === plan.videoQn) {
          return { status: 'switched', paused: !!video.paused };
        }
      } catch (e) { /* fall through to the safe timeout path */ }
      restoreAuto();
      log('DASH quality switch timed out', qn);
      return { status: 'timeout' };
    }

    if (sourceChanged) return { status: 'canceled' };
    const videoResult = outcome.result;
    if (videoResult.status === 'rejected') {
      let renderedQn = null;
      try { renderedQn = coreQualityQn(core, 'video'); } catch (e) { /* use the error code below */ }
      const status = renderedQn === plan.videoQn
        ? 'switched'
        : dashSwitchErrorStatus(
          videoResult.reason && videoResult.reason.code,
          renderedQn,
          plan.videoQn,
        );
      if (status === 'switched') return { status: 'switched', paused: !!video.paused };
      restoreAuto();
      log('DASH video switch failed', videoResult.reason);
      return { status: status, error: videoResult.reason };
    }
    try {
      if (win.player !== player || player.__core() !== core || player.mediaElement() !== video) {
        return { status: 'canceled' };
      }
      if (coreQualityQn(core, 'video') !== plan.videoQn) {
        restoreAuto();
        return { status: 'failed' };
      }
    } catch (e) {
      return { status: 'canceled' };
    }
    return { status: 'switched', paused: !!video.paused };
  }

  function switchQuality(qn) {
    const tier = qnTier(qn, CONFIG.maxQn);
    if (qualitySwitchBusy()) {
      showToast('画质切换中，请稍候…');
      return;
    }

    store.set('qn', qn);
    showToast('正在切到 ' + (QN_LABEL[qn] || (qn + 'P')) + '…');
    qualitySwitchInFlight = (async () => {
      try {
        const result = await switchDashQuality(qn);
        if (result.status === 'switched') {
          showToast(
            result.paused
              ? '已选择 ' + (QN_LABEL[qn] || (qn + 'P')) + '，继续播放后生效'
              : '已切到 ' + (QN_LABEL[qn] || (qn + 'P')),
          );
        } else if (result.status === 'unsupported') {
          showToast((QN_LABEL[qn] || (qn + 'P')) + ' 当前视频不可用，已保持播放');
        } else if (result.status === 'unavailable' || result.status === 'failed') {
          if (tier === 'instant') {
            const player = win.player;
            if (!player || typeof player.requestQuality !== 'function') throw new Error('quality API unavailable');
            await Promise.resolve(player.requestQuality(qn));
            showToast('已切到 ' + (QN_LABEL[qn] || (qn + 'P')));
          } else {
            reloadForQuality(qn);
          }
        } else if (result.status === 'busy') {
          showToast('播放器正在切换画质，请稍后重试');
        } else if (result.status === 'timeout') {
          showToast('无刷新切换超时，已保留当前播放');
        }
      } catch (e) {
        log('DASH quality switch error', e);
        if (tier === 'instant') {
          showToast('画质切换失败，已保持当前播放');
        } else {
          reloadForQuality(qn);
        }
      } finally {
        qualitySwitchInFlight = null;
      }
    })();
  }

  function installQualityControl() {
    // Keep the badges honest as the player (re)renders its menu. Coalesce the
    // player's frequent subtree mutations into at most one relabel per frame.
    let relabelPending = false;
    function scheduleRelabel() {
      if (relabelPending) return;
      relabelPending = true;
      requestAnimationFrame(() => { relabelPending = false; relabelMenu(); });
    }
    try {
      const target = document.querySelector('.bpx-player-container') || document.body;
      if (target) {
        new MutationObserver(scheduleRelabel).observe(target, { childList: true, subtree: true });
      }
    } catch (e) { /* ignore */ }
    relabelMenu();

    document.addEventListener('click', (e) => {
      const path = typeof e.composedPath === 'function' ? e.composedPath() : [e.target];
      let item = null;
      for (const el of path) {
        if (el && el.classList && el.classList.contains('bpx-player-ctrl-quality-menu-item')) { item = el; break; }
      }
      if (!item) return;
      const qn = qnFromItem(item);

      // 自动: clear the pin, let the native (free) handler run -> auto-locks max.
      if (qn == null || qn === 0) {
        if (qualitySwitchBusy()) {
          e.preventDefault(); e.stopImmediatePropagation();
          showToast('画质切换中，请稍候…');
          return;
        }
        store.set('qn', 'auto');
        return;
      }

      if (qnTier(qn, CONFIG.maxQn) === 'blocked') {
        e.preventDefault(); e.stopImmediatePropagation();
        showToast((QN_LABEL[qn] || (qn + 'P')) + ' 需大会员');
        return;
      }

      // Take over the click so the native 「登录即享」 login popup never fires,
      // then drive the switch ourselves (in-place or via reload).
      e.preventDefault(); e.stopImmediatePropagation();
      log('quality chosen', qn);
      switchQuality(qn);
    }, true);
  }

  let manifestBootstrapInFlight = null;
  let manifestBootstrapLastAttempt = 0;
  function bootstrapHighestManifest() {
    const now = Date.now();
    if (manifestBootstrapInFlight || now - manifestBootstrapLastAttempt < 8000) {
      return manifestBootstrapInFlight;
    }
    manifestBootstrapLastAttempt = now;
    manifestBootstrapInFlight = (async () => {
      try {
        const bvid = bvidFromLocation();
        if (!bvid || typeof win.fetch !== 'function') return;
        const viewResponse = await win.fetch(
          'https://api.bilibili.com/x/web-interface/view?bvid=' + encodeURIComponent(bvid),
          { credentials: 'omit' },
        );
        const viewJson = await viewResponse.json();
        const view = viewJson && viewJson.data;
        const page = Math.max(1, Number(new URLSearchParams(location.search).get('p')) || 1);
        const pages = view && Array.isArray(view.pages) ? view.pages : [];
        const cid = (pages[page - 1] && pages[page - 1].cid) || (view && view.cid);
        if (!cid) return;
        const highUrl = buildHiUrl({ bvid: bvid, cid: cid }, false, CONFIG.maxQn);
        diagnostics.lastUrl = highUrl;
        const highResponse = await win.fetch(highUrl, { credentials: 'omit' });
        const highJson = await highResponse.json();
        const high = getData(highJson);
        diagnostics.apiCode = Number(highJson && highJson.code);
        diagnostics.hasDash = !!(high && high.dash);
        if (!high || !high.dash) return;
        const picked = pickStartQn(high, CONFIG.maxQn);
        diagnostics.pickedQn = picked;
        if (picked < CONFIG.maxQn) return;

        const player = win.player;
        const core = player && typeof player.__core === 'function' ? player.__core() : null;
        if (!core || typeof core.updateSource !== 'function') return;
        const playback = readPlayback();
        if (typeof core.setDefaultQualityFor === 'function') {
          core.setDefaultQualityFor('video', CONFIG.maxQn);
          core.setDefaultQualityFor('audio', 30280);
        }
        await Promise.resolve(core.updateSource(high.dash));
        setInjectedHighQn(picked);
        const video = player && typeof player.mediaElement === 'function'
          ? player.mediaElement() : null;
        if (video && playback.t > 1) video.currentTime = playback.t;
        if (video && playback.paused) video.pause();
        await switchDashQuality(CONFIG.maxQn);
      } catch (error) {
        diagnostics.error = String(error && (error.message || error));
      }
    })().finally(() => { manifestBootstrapInFlight = null; });
    return manifestBootstrapInFlight;
  }

  function installHighestQualityGuard() {
    let lastAttempt = 0;
    const ensure = () => {
      const now = Date.now();
      if (now - lastAttempt < 4000 || qualitySwitchBusy()) return;
      try {
        const player = win.player;
        const quality = player && typeof player.getQuality === 'function'
          ? player.getQuality() : null;
        const video = player && typeof player.mediaElement === 'function'
          ? player.mediaElement() : null;
        const core = player && typeof player.__core === 'function' ? player.__core() : null;
        const available = core && typeof core.getQualityList === 'function'
          ? core.getQualityList('video').map((entry) => Number(entry && entry.id))
          : [];
        if (available.includes(CONFIG.maxQn) && injectedHighQn < CONFIG.maxQn) {
          setInjectedHighQn(CONFIG.maxQn);
          diagnostics.pickedQn = CONFIG.maxQn;
        }
        const current = Number(quality && (quality.realQ || quality.nowQ)) || 0;
        if (injectedHighQn < CONFIG.maxQn) {
          bootstrapHighestManifest();
          return;
        }
        if (!video || video.paused || current >= CONFIG.maxQn) return;
        lastAttempt = now;
        switchQuality(CONFIG.maxQn);
      } catch (e) { /* retry on the next bounded check */ }
    };
    document.addEventListener('play', ensure, true);
    document.addEventListener('loadedmetadata', ensure, true);
    document.addEventListener('fullscreenchange', ensure, true);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) ensure();
    });
    setInterval(ensure, 4000);
    setTimeout(ensure, 1800);
  }

  // The native "试看30秒" action starts a wall-clock timer that later forces
  // qn 16. When our high-quality stream is already injected, stop that action
  // before the player enters trial state. This never switches or retries.
  function installTrialGuard() {
    document.addEventListener('click', (e) => {
      const path = typeof e.composedPath === 'function' ? e.composedPath() : [e.target];
      const trial = path.find((el) =>
        el && el.classList && el.classList.contains('bpx-player-toast-confirm-login'));
      if (!trial) return;
      let quality = null;
      let video = null;
      try {
        const player = win.player;
        quality = player && typeof player.getQuality === 'function' ? player.getQuality() : null;
        video = player && typeof player.mediaElement === 'function' ? player.mediaElement() : null;
      } catch (err) { /* leave the native action alone if state is unavailable */ }
      const container = trial.closest && trial.closest('.bpx-player-container');
      if (!container || !video || !container.contains(video) ||
          !isHighPlaybackActive(quality, video.videoWidth, video.videoHeight)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      const liveQn = Number(quality && (quality.realQ || quality.nowQ)) || injectedHighQn;
      log('blocked native timed trial', liveQn);
      trial.style.setProperty('display', 'none', 'important');
    }, true);
  }

  /* ------------------------------------------------------------------ *
   * Toast — a tiny "已解锁 1080P" confirmation (Shadow DOM, isolated).   *
   * ------------------------------------------------------------------ */
  let toastPending = 0;
  function scheduleToast(qn) {
    if (!CONFIG.toast) return;
    toastPending = qn;
  }
  // Render a brief centred toast (Shadow DOM, style-isolated). `msg` is always
  // one of our own constant strings, never user/page input.
  function showToast(msg) {
    if (!CONFIG.toast) return;
    try {
      const host = document.createElement('div');
      host.style.cssText = 'all:initial;position:fixed;left:50%;top:12%;transform:translateX(-50%);z-index:2147483647;pointer-events:none;';
      const sh = host.attachShadow({ mode: 'open' });
      sh.innerHTML =
        '<div style="padding:8px 18px;border-radius:10px;background:rgba(0,0,0,.78);color:#fff;' +
        'font:700 16px/1.4 -apple-system,\'Segoe UI\',\'Microsoft YaHei\',sans-serif;letter-spacing:1px;' +
        'opacity:0;transition:opacity .2s;">' + msg + '</div>';
      (document.body || document.documentElement).appendChild(host);
      const box = sh.firstChild;
      requestAnimationFrame(() => { box.style.opacity = '1'; });
      setTimeout(() => { box.style.opacity = '0'; setTimeout(() => host.remove(), 300); }, 1600);
    } catch (e) { /* ignore */ }
  }
  function flushToast() {
    if (!toastPending) return;
    const qn = toastPending; toastPending = 0;
    showToast('已解锁 ' + (QN_LABEL[qn] || (qn + 'P')));
  }

  /* ------------------------------------------------------------------ *
   * Bootstrap.                                                          *
   * ------------------------------------------------------------------ */
  // Network layer first, at document-start, before any page script runs.
  installTrialGuard();
  installLoginUiPolicy();
  installPlayinfoHook();
  installInitialStateHook();
  installFetchHook();
  installXhrHook();

  // UI wiring needs the DOM.
  function ready() {
    installQualityControl();
    installHighestQualityGuard();
    applyResume();
    flushToast();
    // The toast may be scheduled by an SSR injection that ran before <body>
    // existed; poll briefly to surface it once the page is alive.
    let n = 0;
    const t = setInterval(() => { flushToast(); if (++n > 20) clearInterval(t); }, 500);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ready, { once: true });
  } else {
    ready();
  }
})();
