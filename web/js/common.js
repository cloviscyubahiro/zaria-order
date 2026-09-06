/* Shared helpers. Everything that touches user or vendor text builds DOM with
   textContent — no innerHTML with data, anywhere, in any of the three apps.
   That is what keeps a vendor's discount text from becoming a script tag. */
(function (global) {
  'use strict';

  var csrf = '';

  function setCsrf(token) { csrf = token || ''; }
  function getCsrf() { return csrf; }

  function api(method, path, body) {
    var opts = {
      method: method,
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    if (method !== 'GET' && method !== 'HEAD' && csrf) {
      opts.headers['X-CSRF-Token'] = csrf;
    }
    /* A two-argument then() so this only sees the network failing — the browser
       says "Failed to fetch", which tells nobody anything. Errors thrown by the
       success handler below (a real 400/403 from the server) pass straight
       through and keep the server's own wording. */
    return fetch(path, opts).then(null, function () {
      var err = new Error('Cannot reach the ordering server. Check that it is '
        + 'still running on the venue computer, then try again.');
      err.offline = true;
      throw err;
    }).then(function (res) {
      var ct = res.headers.get('Content-Type') || '';
      var parse = ct.indexOf('application/json') >= 0
        ? res.json().catch(function () { return {}; })
        : Promise.resolve({});
      return parse.then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || ('Request failed (' + res.status + ')'));
          err.status = res.status;
          err.field = data.field || '';
          throw err;
        }
        return data;
      });
    });
  }

  /* ---------- DOM ---------- */

  function el(tag, opts, kids) {
    var node = document.createElement(tag);
    opts = opts || {};
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);
    if (opts.attrs) {
      Object.keys(opts.attrs).forEach(function (k) {
        if (opts.attrs[k] !== null && opts.attrs[k] !== undefined) {
          node.setAttribute(k, String(opts.attrs[k]));
        }
      });
    }
    if (opts.style) {
      Object.keys(opts.style).forEach(function (k) { node.style.setProperty(k, opts.style[k]); });
    }
    if (opts.on) {
      Object.keys(opts.on).forEach(function (k) { node.addEventListener(k, opts.on[k]); });
    }
    (kids || []).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
    });
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function $(sel, root) { return (root || document).querySelector(sel); }

  /* ---------- Formatting ---------- */

  function money(n) {
    var v = Math.round(Number(n) || 0);
    return v.toLocaleString('en-US') + ' RWF';
  }

  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : (many || one + 's'));
  }

  function timeAgo(iso) {
    if (!iso) return '';
    var then = new Date(iso.indexOf('Z') < 0 && iso.indexOf('+') < 0 ? iso + 'Z' : iso);
    var secs = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
    return Math.floor(secs / 86400) + 'd ago';
  }

  function clock(iso) {
    if (!iso) return '';
    var d = new Date(iso.indexOf('Z') < 0 && iso.indexOf('+') < 0 ? iso + 'Z' : iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  /* ---------- Toast ---------- */

  var toastTimer = null;
  function toast(message, bad) {
    var node = document.getElementById('toast');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('toast--bad', !!bad);
    node.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.classList.remove('is-on'); }, bad ? 4200 : 2400);
  }

  /* ---------- Sheets ---------- */

  function openSheet(id) {
    var s = document.getElementById(id);
    if (s) { s.classList.add('is-on'); document.body.style.overflow = 'hidden'; }
  }
  function closeSheet(id) {
    var s = document.getElementById(id);
    if (s) { s.classList.remove('is-on'); document.body.style.overflow = ''; }
  }
  function wireSheet(id, closeBtnId) {
    var sheet = document.getElementById(id);
    if (!sheet) return;
    sheet.addEventListener('click', function (e) {
      if (e.target === sheet) closeSheet(id);
    });
    if (closeBtnId) {
      var btn = document.getElementById(closeBtnId);
      if (btn) btn.addEventListener('click', function () { closeSheet(id); });
    }
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var open = document.querySelector('.sheet.is-on');
      if (open) closeSheet(open.id);
    }
  });

  /* ---------- Storage (tolerates private mode) ---------- */

  var store = {
    get: function (k, fallback) {
      try {
        var raw = localStorage.getItem(k);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set: function (k, v) {
      try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* full or blocked */ }
    },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
  };

  global.Z = {
    api: api, setCsrf: setCsrf, getCsrf: getCsrf,
    el: el, clear: clear, $: $,
    money: money, plural: plural, timeAgo: timeAgo, clock: clock,
    toast: toast, openSheet: openSheet, closeSheet: closeSheet, wireSheet: wireSheet,
    store: store
  };
})(window);
