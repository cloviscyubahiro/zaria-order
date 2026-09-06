/* Vendor console. */
(function () {
  'use strict';

  var el = Z.el, clear = Z.clear, $ = Z.$, money = Z.money;

  var state = {
    vendor: null, user: null, menu: null, orders: [],
    editingItem: null, editingCat: null, timer: null, tab: 'orders',
    briefingSig: null
  };

  /* ================= session ================= */

  function start() {
    Z.api('GET', '/api/vendor/me').then(onSession).catch(function (e) {
      $('#loginView').classList.remove('hidden');
      $('#shell').classList.add('hidden');
      /* Same reason as admin: a kitchen must not be left guessing whether it
         was signed out or the venue computer stopped. */
      if (e && e.offline) {
        var err = $('#lErr');
        err.textContent = e.message;
        err.classList.remove('hidden');
      }
    });
  }

  function onSession(data) {
    Z.setCsrf(data.csrf);
    state.vendor = data.vendor;
    state.user = data.user;
    $('#loginView').classList.add('hidden');
    $('#shell').classList.remove('hidden');
    $('#navVendor').textContent = data.vendor.name;
    $('#navWho').textContent = data.user.display;
    document.documentElement.style.setProperty('--gold', data.vendor.accent || '#C9A063');
    $('#pwBanner').classList.toggle('hidden', !data.user.must_change);
    renderShopToggles();
    loadOrders();
    startPolling();
  }

  function login() {
    var btn = $('#loginBtn'), err = $('#lErr');
    err.classList.add('hidden');
    btn.disabled = true; btn.textContent = 'Signing in…';
    Z.api('POST', '/api/vendor/login', {
      username: $('#lUser').value.trim(), password: $('#lPass').value
    }).then(function (data) {
      Z.setCsrf(data.csrf);
      $('#lPass').value = '';
      return Z.api('GET', '/api/vendor/me').then(onSession);
    }).catch(function (e) {
      err.textContent = e.message; err.classList.remove('hidden');
    }).finally(function () {
      btn.disabled = false; btn.textContent = 'Sign in';
    });
  }

  function startPolling() {
    clearInterval(state.timer);
    state.timer = setInterval(function () {
      if (state.tab === 'orders' && !document.hidden) loadOrders(true);
    }, 10000);
  }

  /* ================= tabs ================= */

  function switchTab(name) {
    state.tab = name;
    Array.prototype.forEach.call(document.querySelectorAll('.nav .tab'), function (b) {
      b.classList.toggle('is-on', b.getAttribute('data-tab') === name);
    });
    var panes = { orders: 'paneOrders', menu: 'paneMenu', offers: 'paneOffers',
                  notices: 'paneNotices', shop: 'paneShop' };
    Object.keys(panes).forEach(function (k) {
      $('#' + panes[k]).classList.toggle('hidden', k !== name);
    });
    if (name === 'orders') loadOrders();
    if (name === 'menu') loadMenu();
    if (name === 'offers') loadDiscounts();
    if (name === 'notices') loadAnnouncements();
  }

  /* ================= orders ================= */

  function loadOrders(quiet) {
    Z.api('GET', '/api/vendor/orders?scope=open').then(function (data) {
      state.orders = data.orders;
      renderTickets();
      renderBriefing(data.briefing || []);
      return Z.api('GET', '/api/vendor/summary');
    }).then(renderStats)
      .catch(function (e) { if (!quiet) Z.toast(e.message, true); });
  }

  function renderBriefing(items) {
    var box = $('#briefing');
    // Rebuilding on every ten-second poll would fight the reader, so only
    // redraw when the messages have actually changed.
    var sig = items.map(function (a) { return a.id; }).join(',');
    if (sig === state.briefingSig) return;
    state.briefingSig = sig;

    clear(box);
    if (!items.length) return;
    items.forEach(function (a) {
      box.appendChild(el('div', { className: 'brief' }, [
        el('div', { className: 'brief__from', text: 'From Zaria management' }),
        el('div', { className: 'brief__body', text: a.body }),
        el('div', { className: 'brief__when', text: Z.timeAgo(a.created_at) })
      ]));
    });
  }

  function renderStats(s) {
    var box = $('#orderStats');
    clear(box);
    var pending = state.orders.filter(function (o) { return o.status === 'PENDING'; }).length;
    [
      ['Waiting for you', String(pending), pending ? 'warn' : 'ok', 'Tap Accept to start'],
      ['Orders today', String(s.orders || 0), '', ''],
      ['Collected today', money(s.collected || 0), 'ok', ''],
      ['Still to collect', money(s.outstanding || 0), (s.outstanding ? 'warn' : ''), 'Delivered but not paid']
    ].forEach(function (row) {
      box.appendChild(el('div', { className: 'stat' }, [
        el('div', { className: 'stat__label', text: row[0] }),
        el('div', { className: 'stat__value' + (row[2] ? ' stat__value--' + row[2] : ''), text: row[1] }),
        row[3] ? el('div', { className: 'stat__sub', text: row[3] }) : null
      ]));
    });
  }

  function minutesSince(iso) {
    if (!iso) return 0;
    var d = new Date(iso.indexOf('Z') < 0 && iso.indexOf('+') < 0 ? iso + 'Z' : iso);
    return Math.floor((Date.now() - d.getTime()) / 60000);
  }

  function renderTickets() {
    var grid = $('#ticketGrid');
    clear(grid);
    if (!state.orders.length) {
      grid.appendChild(el('p', { className: 'empty', text: 'No open orders. New ones appear here automatically.' }));
      return;
    }

    state.orders.forEach(function (o) {
      var age = minutesSince(o.placed_at);
      var lines = el('ul', { className: 'ticket__lines' }, o.items.map(function (it) {
        return el('li', {}, [
          el('span', { className: 'ticket__qty', text: it.qty + '×' }),
          el('span', { text: it.name_snapshot })
        ]);
      }));

      var actions = el('div', { className: 'ticket__actions' }, buttonsFor(o));

      grid.appendChild(el('div', { className: 'ticket ticket--' + o.status }, [
        el('div', { className: 'ticket__top' }, [
          el('span', { className: 'ticket__code', text: o.short_code }),
          el('span', {
            className: 'ticket__table' + (o.table_code ? '' : ' ticket__table--pickup'),
            text: o.table_code ? 'Table ' + o.table_code : 'Collect at counter'
          }),
          el('span', {
            className: 'ticket__age' + (age >= 15 && o.status !== 'PAID' ? ' ticket__age--late' : ''),
            text: age + 'm'
          })
        ]),
        el('div', {
          className: 'ticket__who',
          text: (o.customer_name || 'Guest') + (o.customer_phone ? ' · ' + o.customer_phone : '')
        }),
        lines,
        o.note ? el('div', { className: 'ticket__note', text: o.note }) : null,
        el('div', { className: 'ticket__total' }, [
          el('span', { className: 'pill pill--' + o.status, text: o.status.toLowerCase() }),
          el('b', { className: 'money', text: money(o.total_rwf) })
        ]),
        actions
      ]));
    });
  }

  function buttonsFor(o) {
    function act(label, status, cls, extra) {
      return el('button', {
        className: 'btn btn--sm' + (cls ? ' ' + cls : ''), text: label, attrs: { type: 'button' },
        on: { click: function () { move(o, status, extra); } }
      });
    }
    if (o.status === 'PENDING') {
      return [act('Accept', 'ACCEPTED', 'btn--ok'), act('Reject', 'REJECTED', 'btn--danger')];
    }
    if (o.status === 'ACCEPTED') {
      return [act('Ready', 'READY', 'btn--ok'), act('Cancel', 'CANCELLED', 'btn--ghost')];
    }
    if (o.status === 'READY') {
      return [act('Delivered', 'DELIVERED'), act('Cancel', 'CANCELLED', 'btn--ghost')];
    }
    if (o.status === 'DELIVERED') {
      return [
        act('Paid cash', 'PAID', 'btn--ok', { payment_method: 'CASH' }),
        act('Paid MoMo', 'PAID', 'btn--ok', { payment_method: 'MOMO' })
      ];
    }
    return [];
  }

  function move(order, status, extra) {
    var body = { status: status };
    if (extra) Object.keys(extra).forEach(function (k) { body[k] = extra[k]; });
    if (status === 'REJECTED' || status === 'CANCELLED') {
      var why = window.prompt('Reason (the guest will see this):', 'Sold out');
      if (why === null) return;
      body.note = why;
    }
    Z.api('POST', '/api/vendor/orders/' + order.id + '/status', body)
      .then(function () { Z.toast('Order ' + order.short_code + ' → ' + status.toLowerCase() + '.'); loadOrders(); })
      .catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= menu ================= */

  function loadMenu() {
    Z.api('GET', '/api/vendor/menu').then(function (data) {
      state.menu = data;
      renderMenu();
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  function renderMenu() {
    var box = $('#menuEditor');
    clear(box);
    var cats = state.menu.categories.slice();
    if (state.menu.uncategorised && state.menu.uncategorised.length) {
      cats.push({ id: null, name: 'Not in a section', note: '', items: state.menu.uncategorised, is_active: 1 });
    }
    if (!cats.length) {
      box.appendChild(el('p', { className: 'empty', text: 'No sections yet. Start with “+ Section”.' }));
      return;
    }

    cats.forEach(function (cat) {
      var head = el('div', { className: 'catgroup__head' }, [
        el('span', { className: 'catgroup__name', text: cat.name }),
        cat.note ? el('span', { className: 'small muted', text: cat.note }) : null,
        el('span', { style: { 'margin-left': 'auto' }, className: 'rowitem__actions' },
          cat.id === null ? [] : [
            el('button', {
              className: 'btn btn--ghost btn--sm', text: 'Rename', attrs: { type: 'button' },
              on: { click: function () { openCat(cat); } }
            }),
            el('button', {
              className: 'btn btn--ghost btn--sm', text: 'Delete', attrs: { type: 'button' },
              on: {
                click: function () {
                  if (!window.confirm('Delete the section "' + cat.name + '"?')) return;
                  Z.api('DELETE', '/api/vendor/categories/' + cat.id)
                    .then(function () { Z.toast('Section deleted.'); loadMenu(); })
                    .catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
      ]);

      var group = el('div', { className: 'catgroup' }, [head]);

      cat.items.forEach(function (item) {
        var meta = money(item.price_rwf);
        if (item.discount_percent) meta += '  (was ' + money(item.base_price_rwf) + ')';
        if (!item.is_active) meta += '  · removed';

        group.appendChild(el('div', {
          className: 'rowitem' + (item.is_available && item.is_active ? '' : ' rowitem--off')
        }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: item.name }),
            el('div', { className: 'rowitem__meta', text: meta }),
            item.description ? el('div', { className: 'rowitem__meta', text: item.description }) : null
          ]),
          el('div', { className: 'rowitem__actions' }, [
            el('button', {
              className: 'btn btn--sm ' + (item.is_available ? 'btn--ghost' : 'btn--ok'),
              text: item.is_available ? 'Sold out' : 'Back on',
              attrs: { type: 'button' },
              on: {
                click: function () {
                  Z.api('PATCH', '/api/vendor/items/' + item.id, { is_available: !item.is_available })
                    .then(function () { loadMenu(); })
                    .catch(function (e) { Z.toast(e.message, true); });
                }
              }
            }),
            el('button', {
              className: 'btn btn--ghost btn--sm', text: 'Edit', attrs: { type: 'button' },
              on: { click: function () { openItem(item); } }
            }),
            el('button', {
              className: 'btn btn--ghost btn--sm', text: 'Remove', attrs: { type: 'button' },
              on: {
                click: function () {
                  if (!window.confirm('Remove "' + item.name + '" from the menu?')) return;
                  Z.api('DELETE', '/api/vendor/items/' + item.id)
                    .then(function () { Z.toast('Removed.'); loadMenu(); })
                    .catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
        ]));
      });

      if (!cat.items.length) {
        group.appendChild(el('p', { className: 'small muted', text: 'Nothing in this section yet.' }));
      }
      box.appendChild(group);
    });
  }

  function categoryOptions(select, selected) {
    clear(select);
    select.appendChild(el('option', { text: 'No section', attrs: { value: '' } }));
    (state.menu ? state.menu.categories : []).forEach(function (c) {
      select.appendChild(el('option', { text: c.name, attrs: { value: String(c.id) } }));
    });
    select.value = selected === null || selected === undefined ? '' : String(selected);
  }

  function openItem(item) {
    state.editingItem = item || null;
    $('#itemSheetTitle').textContent = item ? 'Edit item' : 'New item';
    $('#iName').value = item ? item.name : '';
    $('#iPrice').value = item ? (item.base_price_rwf !== undefined ? item.base_price_rwf : item.price_rwf) : '';
    $('#iDesc').value = item ? (item.description || '') : '';
    $('#iTags').value = item && item.tags && item.tags.length ? item.tags[0] : '';
    categoryOptions($('#iCat'), item ? item.category_id : (state.menu.categories[0] || {}).id);
    ['iNameErr', 'iPriceErr'].forEach(function (id) { $('#' + id).classList.add('hidden'); });
    Z.openSheet('itemSheet');
  }

  function saveItem() {
    var payload = {
      name: $('#iName').value.trim(),
      price_rwf: Number($('#iPrice').value),
      description: $('#iDesc').value.trim(),
      category_id: $('#iCat').value ? Number($('#iCat').value) : null,
      tags: $('#iTags').value ? [$('#iTags').value] : []
    };
    ['iNameErr', 'iPriceErr'].forEach(function (id) { $('#' + id).classList.add('hidden'); });

    var call = state.editingItem
      ? Z.api('PATCH', '/api/vendor/items/' + state.editingItem.id, payload)
      : Z.api('POST', '/api/vendor/items', payload);

    call.then(function () {
      Z.closeSheet('itemSheet');
      Z.toast('Saved.');
      loadMenu();
    }).catch(function (e) {
      var map = { name: 'iNameErr', price_rwf: 'iPriceErr' };
      var t = map[e.field];
      if (t) { $('#' + t).textContent = e.message; $('#' + t).classList.remove('hidden'); }
      else Z.toast(e.message, true);
    });
  }

  function openCat(cat) {
    state.editingCat = cat || null;
    $('#catSheetTitle').textContent = cat ? 'Rename section' : 'New section';
    $('#cName').value = cat ? cat.name : '';
    $('#cNote').value = cat ? (cat.note || '') : '';
    $('#cNameErr').classList.add('hidden');
    Z.openSheet('catSheet');
  }

  function saveCat() {
    var payload = { name: $('#cName').value.trim(), note: $('#cNote').value.trim() };
    var call = state.editingCat
      ? Z.api('PATCH', '/api/vendor/categories/' + state.editingCat.id, payload)
      : Z.api('POST', '/api/vendor/categories', payload);
    call.then(function () {
      Z.closeSheet('catSheet'); Z.toast('Saved.'); loadMenu();
    }).catch(function (e) {
      if (e.field === 'name') { $('#cNameErr').textContent = e.message; $('#cNameErr').classList.remove('hidden'); }
      else Z.toast(e.message, true);
    });
  }

  /* ================= discounts ================= */

  function loadDiscounts() {
    if (!state.menu) {
      Z.api('GET', '/api/vendor/menu').then(function (d) { state.menu = d; loadDiscounts(); });
      return;
    }
    Z.api('GET', '/api/vendor/discounts').then(function (data) {
      var box = $('#discList');
      clear(box);
      if (!data.discounts.length) {
        box.appendChild(el('p', { className: 'empty', text: 'No offers yet.' }));
        return;
      }
      data.discounts.forEach(function (d) {
        var what = d.scope === 'vendor' ? 'Everything'
          : d.scope === 'category' ? sectionName(d.target_id)
          : itemName(d.target_id);
        box.appendChild(el('div', { className: 'rowitem' + (d.is_active ? '' : ' rowitem--off') }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: d.percent + '% off · ' + what }),
            el('div', { className: 'rowitem__meta', text: (d.label || 'No label') + ' · started ' + Z.timeAgo(d.created_at) })
          ]),
          el('div', { className: 'rowitem__actions' }, [
            el('button', {
              className: 'btn btn--sm ' + (d.is_active ? 'btn--danger' : 'btn--ok'),
              text: d.is_active ? 'Stop' : 'Start again', attrs: { type: 'button' },
              on: {
                click: function () {
                  Z.api('PATCH', '/api/vendor/discounts/' + d.id, { is_active: !d.is_active })
                    .then(function () { loadDiscounts(); loadMenu(); })
                    .catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
        ]));
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  function sectionName(id) {
    var c = (state.menu.categories || []).filter(function (x) { return x.id === id; })[0];
    return c ? c.name : 'a section';
  }
  function itemName(id) {
    var found = 'an item';
    (state.menu.categories || []).forEach(function (c) {
      c.items.forEach(function (i) { if (i.id === id) found = i.name; });
    });
    return found;
  }

  function fillDiscountTargets() {
    var scope = $('#dScope').value;
    var wrap = $('#dTargetWrap'), sel = $('#dTarget');
    wrap.classList.toggle('hidden', scope === 'vendor');
    if (scope === 'vendor' || !state.menu) return;
    clear(sel);
    if (scope === 'category') {
      state.menu.categories.forEach(function (c) {
        sel.appendChild(el('option', { text: c.name, attrs: { value: String(c.id) } }));
      });
    } else {
      state.menu.categories.forEach(function (c) {
        var g = el('optgroup', { attrs: { label: c.name } });
        c.items.forEach(function (i) {
          g.appendChild(el('option', { text: i.name, attrs: { value: String(i.id) } }));
        });
        sel.appendChild(g);
      });
    }
  }

  /* ================= announcements ================= */

  function loadAnnouncements() {
    Z.api('GET', '/api/vendor/announcements').then(function (data) {
      // Repeat the briefing here: this is the page a kitchen opens to act on it.
      var brief = $('#briefingNotices');
      clear(brief);
      (data.briefing || []).forEach(function (a) {
        brief.appendChild(el('div', { className: 'brief' }, [
          el('div', { className: 'brief__from', text: 'From Zaria management' }),
          el('div', { className: 'brief__body', text: a.body }),
          el('div', { className: 'brief__when', text: Z.timeAgo(a.created_at) })
        ]));
      });

      var box = $('#annList');
      clear(box);
      if (!data.announcements.length) {
        box.appendChild(el('p', { className: 'empty', text: 'Nothing posted yet.' }));
        return;
      }
      data.announcements.forEach(function (a) {
        box.appendChild(el('div', { className: 'rowitem' + (a.is_active ? '' : ' rowitem--off') }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: a.body }),
            el('div', { className: 'rowitem__meta', text: a.kind + ' · ' + Z.timeAgo(a.created_at) })
          ]),
          el('div', { className: 'rowitem__actions' }, [
            el('button', {
              className: 'btn btn--sm ' + (a.is_active ? 'btn--danger' : 'btn--ok'),
              text: a.is_active ? 'Take down' : 'Put back', attrs: { type: 'button' },
              on: {
                click: function () {
                  Z.api('PATCH', '/api/vendor/announcements/' + a.id, { is_active: !a.is_active })
                    .then(loadAnnouncements).catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
        ]));
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= shop ================= */

  function renderShopToggles() {
    var v = state.vendor;
    var openBtn = $('#openToggle'), accBtn = $('#acceptToggle');
    openBtn.textContent = v.is_open ? 'Open' : 'Closed';
    openBtn.className = 'btn btn--sm ' + (v.is_open ? 'btn--ok' : 'btn--danger');
    accBtn.textContent = v.accepts_orders ? 'On' : 'Off';
    accBtn.className = 'btn btn--sm ' + (v.accepts_orders ? 'btn--ok' : 'btn--danger');
    $('#sMomo').value = v.momo_code || '';
  }

  function setShopState(patch) {
    Z.api('POST', '/api/vendor/state', patch).then(function () {
      return Z.api('GET', '/api/vendor/me');
    }).then(function (d) {
      state.vendor = d.vendor;
      renderShopToggles();
      Z.toast('Saved.');
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= wiring ================= */

  Z.wireSheet('itemSheet', 'itemClose');
  Z.wireSheet('catSheet', 'catClose');

  $('#loginBtn').addEventListener('click', login);
  $('#lPass').addEventListener('keydown', function (e) { if (e.key === 'Enter') login(); });
  $('#lUser').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('#lPass').focus(); });

  $('#logoutBtn').addEventListener('click', function () {
    Z.api('POST', '/api/vendor/logout').finally(function () { location.reload(); });
  });

  Array.prototype.forEach.call(document.querySelectorAll('.nav .tab'), function (b) {
    b.addEventListener('click', function () { switchTab(b.getAttribute('data-tab')); });
  });

  $('#refreshBtn').addEventListener('click', function () { loadOrders(); });
  $('#addItemBtn').addEventListener('click', function () { openItem(null); });
  $('#addCatBtn').addEventListener('click', function () { openCat(null); });
  $('#itemSave').addEventListener('click', saveItem);
  $('#catSave').addEventListener('click', saveCat);

  $('#dScope').addEventListener('change', fillDiscountTargets);
  $('#addDiscBtn').addEventListener('click', function () {
    var payload = {
      scope: $('#dScope').value,
      percent: Number($('#dPercent').value),
      label: $('#dLabel').value.trim()
    };
    if (payload.scope !== 'vendor') payload.target_id = Number($('#dTarget').value);
    Z.api('POST', '/api/vendor/discounts', payload).then(function () {
      Z.toast('Offer is live.'); $('#dLabel').value = ''; loadDiscounts(); loadMenu();
    }).catch(function (e) { Z.toast(e.message, true); });
  });

  $('#addAnnBtn').addEventListener('click', function () {
    var body = $('#aBody').value.trim();
    Z.api('POST', '/api/vendor/announcements', { kind: $('#aKind').value, body: body })
      .then(function () { Z.toast('Posted.'); $('#aBody').value = ''; loadAnnouncements(); })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#openToggle').addEventListener('click', function () { setShopState({ is_open: !state.vendor.is_open }); });
  $('#acceptToggle').addEventListener('click', function () { setShopState({ accepts_orders: !state.vendor.accepts_orders }); });
  $('#saveMomoBtn').addEventListener('click', function () { setShopState({ momo_code: $('#sMomo').value.trim() }); });

  $('#pwBannerBtn').addEventListener('click', function () { switchTab('shop'); $('#pCur').focus(); });
  $('#savePwBtn').addEventListener('click', function () {
    var err = $('#pErr');
    err.classList.add('hidden');
    Z.api('POST', '/api/vendor/password', { current: $('#pCur').value, new: $('#pNew').value })
      .then(function () {
        Z.toast('Password changed.');
        $('#pCur').value = ''; $('#pNew').value = '';
        $('#pwBanner').classList.add('hidden');
      })
      .catch(function (e) { err.textContent = e.message; err.classList.remove('hidden'); });
  });

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && state.tab === 'orders') loadOrders(true);
  });

  start();
})();
