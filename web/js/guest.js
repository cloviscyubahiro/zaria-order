/* Guest ordering app. */
(function () {
  'use strict';

  var el = Z.el, clear = Z.clear, $ = Z.$, money = Z.money;

  var state = {
    venue: {}, vendors: [], tables: [], announcements: [],
    table: '', tableToken: '',
    mode: 'TABLE',                             // TABLE | PICKUP | BOTH
    menu: null,
    cart: Z.store.get('zc_cart', {}),          // vendorId -> { itemId -> {qty, name, price} }
    groups: Z.store.get('zc_groups', []),      // recent order group keys
    pollTimer: null,
    liveTimer: null,
    tickerSig: ''
  };

  /* ================= boot ================= */

  function boot() {
    var params = new URLSearchParams(location.search);
    var token = params.get('t') || '';
    if (token) state.tableToken = token;

    Z.api('GET', '/api/bootstrap' + (token ? '?t=' + encodeURIComponent(token) : ''))
      .then(function (data) {
        state.venue = data.venue;
        state.vendors = data.vendors;
        state.tables = data.tables;
        state.announcements = data.announcements;
        state.mode = data.venue.service_mode || 'TABLE';

        if (state.mode === 'PICKUP') {
          // Standing event: there is no table to remember, and a stale one from
          // a previous night must not ride along on tonight's orders.
          state.table = '';
          state.tableToken = '';
          Z.store.del('zc_table');
          Z.store.del('zc_table_token');
        } else if (data.table && data.table.code) {
          state.table = data.table.code;
          Z.store.set('zc_table', data.table.code);
          Z.store.set('zc_table_token', token);
          // Drop the token from the address bar so a shared screenshot of the
          // URL does not carry the table signature around the venue.
          history.replaceState({}, '', location.pathname);
        } else {
          state.table = Z.store.get('zc_table', '') || '';
          state.tableToken = Z.store.get('zc_table_token', '') || '';
          if (data.table && data.table.error) Z.toast(data.table.error, true);
        }

        state.tickerSig = JSON.stringify(state.announcements);
        renderTicker();
        renderTable();
        renderVendors();
        renderCartBar();
        track('page_view');
        startLivePolling();

        if (state.groups.length) $('#ordersBtn').classList.remove('hidden');
      })
      .catch(function (err) {
        clear($('#vendorGrid'));
        $('#vendorGrid').appendChild(el('p', { className: 'empty', text: err.message }));
      });
  }

  /* ================= live updates ================= */

  function startLivePolling() {
    if (state.liveTimer) return;
    state.liveTimer = setInterval(pollLive, 25000);
    // Coming back to the page after a while is exactly when the screen is most
    // likely to be stale, so refresh then too.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) pollLive();
    });
  }

  function pollLive() {
    if (document.hidden) return;
    Z.api('GET', '/api/live').then(function (data) {
      var modeChanged = data.venue.service_mode !== state.mode;
      var signature = JSON.stringify(data.announcements);

      state.venue.ordering_enabled = data.venue.ordering_enabled;
      state.venue.notice = data.venue.notice;
      state.mode = data.venue.service_mode;
      state.vendors = data.vendors;

      if (state.mode === 'PICKUP' && state.table) {
        state.table = '';
        state.tableToken = '';
        Z.store.del('zc_table');
        Z.store.del('zc_table_token');
      }

      // Rebuilding the ticker restarts its scroll animation, so only do it when
      // the notices have actually changed.
      if (signature !== state.tickerSig) {
        state.announcements = data.announcements;
        state.tickerSig = signature;
        renderTicker();
      }
      if (modeChanged) renderTable();
      if (!$('#viewHome').classList.contains('hidden')) renderVendors();
    }).catch(function () { /* a dropped poll must never disturb the screen */ });
  }

  function track(kind, vendorId) {
    Z.api('POST', '/api/track', {
      kind: kind, vendor_id: vendorId || null, table_code: state.table
    }).catch(function () { /* analytics must never break ordering */ });
  }

  /* ================= ticker ================= */

  function renderTicker() {
    var bar = $('#ticker'), trackEl = $('#tickerTrack');
    clear(trackEl);
    if (!state.announcements.length) { bar.classList.add('hidden'); return; }
    bar.classList.remove('hidden');

    function buildRun() {
      var frag = document.createDocumentFragment();
      state.announcements.forEach(function (a) {
        var cls = 'ticker__tag';
        if (a.kind === 'DISCOUNT') cls += ' ticker__tag--discount';
        else if (a.kind === 'SOLD_OUT') cls += ' ticker__tag--sold';
        else if (a.kind === 'EVENT') cls += ' ticker__tag--event';
        var label = a.kind === 'SOLD_OUT' ? 'Sold out'
          : a.kind === 'DISCOUNT' ? 'Offer'
          : a.kind === 'EVENT' ? 'Tonight' : 'Notice';

        frag.appendChild(el('span', { className: 'ticker__item' }, [
          el('span', { className: cls, text: label }),
          a.vendor_name ? el('span', { className: 'ticker__who', text: a.vendor_name }) : null,
          el('span', { text: a.body })
        ]));
      });
      return frag;
    }
    // Two identical runs so the -50% translate loops seamlessly.
    trackEl.appendChild(buildRun());
    trackEl.appendChild(buildRun());
  }

  /* ================= table ================= */

  function renderTable() {
    var chip = $('#tableChip'), val = $('#tableValue'), bar = $('#tableBar');

    if (state.mode === 'PICKUP') {
      bar.classList.add('hidden');
      chip.classList.add('hidden');
      $('#heroSub').textContent =
        'Four kitchens in the container park. Order here, then collect at the ' +
        'kitchen when your code is called. Pay when you collect.';
      return;
    }

    bar.classList.remove('hidden');
    if (state.table) {
      chip.classList.remove('hidden');
      $('#tableChipCode').textContent = state.table;
      val.textContent = state.table;
      val.classList.remove('tablebar__value--none');
    } else {
      chip.classList.add('hidden');
      val.textContent = state.mode === 'BOTH'
        ? 'Standing — collect at the kitchen'
        : 'Not set — tap Change';
      val.classList.add('tablebar__value--none');
    }
  }

  function fillTableSelect(select, includeBlank) {
    clear(select);
    if (includeBlank) {
      select.appendChild(el('option', {
        text: state.mode === 'BOTH'
          ? 'No table — I will collect it'
          : 'Select your table…',
        attrs: { value: '' }
      }));
    }
    var zones = {};
    state.tables.forEach(function (t) { (zones[t.zone || 'Tables'] = zones[t.zone || 'Tables'] || []).push(t); });
    Object.keys(zones).forEach(function (zone) {
      var group = el('optgroup', { attrs: { label: zone } });
      zones[zone].forEach(function (t) {
        group.appendChild(el('option', { text: t.code, attrs: { value: t.code } }));
      });
      select.appendChild(group);
    });
    select.value = state.table || '';
  }

  /* ================= vendors ================= */

  function renderVendors() {
    var grid = $('#vendorGrid');
    clear(grid);
    if (!state.vendors.length) {
      grid.appendChild(el('p', { className: 'empty', text: 'No kitchens are listed right now.' }));
      return;
    }

    state.vendors.forEach(function (v) {
      var badges = [];
      if (v.external_url) badges.push(el('span', { className: 'vcard__badge vcard__badge--ext', text: 'Website' }));
      else if (!v.accepts_orders) badges.push(el('span', { className: 'vcard__badge vcard__badge--ext', text: 'Order at kiosk' }));
      else if (!v.is_open) badges.push(el('span', { className: 'vcard__badge vcard__badge--off', text: 'Closed' }));
      if (v.top_discount) badges.push(el('span', { className: 'vcard__badge vcard__badge--disc', text: '−' + v.top_discount + '%' }));

      var kids = [
        el('span', { className: 'vcard__kind', text: v.kind }),
        el('span', { className: 'vcard__name', text: v.name }),
        el('span', { className: 'vcard__desc', text: v.tagline }),
        el('span', { className: 'vcard__foot' }, badges.concat([
          el('span', { className: 'go', text: v.external_url ? 'Open ↗' : 'See menu →' })
        ]))
      ];

      var node;
      if (v.external_url) {
        node = el('a', {
          className: 'vcard',
          style: { '--accent': v.accent },
          attrs: { href: v.external_url, target: '_blank', rel: 'noopener noreferrer' }
        }, kids);
      } else {
        node = el('button', {
          className: 'vcard', style: { '--accent': v.accent }, attrs: { type: 'button' },
          on: { click: function () { openMenu(v); } }
        }, kids);
      }
      grid.appendChild(node);
    });
  }

  /* ================= menu ================= */

  function show(viewId) {
    ['viewHome', 'viewMenu', 'viewTrack'].forEach(function (id) {
      $('#' + id).classList.toggle('hidden', id !== viewId);
    });
    window.scrollTo(0, 0);
  }

  function openMenu(vendor) {
    track('vendor_view', vendor.id);
    Z.api('GET', '/api/menu/' + encodeURIComponent(vendor.slug)).then(function (data) {
      state.menu = data;
      var v = data.vendor;
      document.documentElement.style.setProperty('--accent', v.accent);
      $('#menuName').textContent = v.name;
      $('#menuName').style.setProperty('--accent', v.accent);
      $('#menuTag').textContent = v.tagline || '';

      var best = 0;
      (data.discounts || []).forEach(function (d) { best = Math.max(best, d.percent); });
      var disc = $('#menuDisc');
      if (best) { disc.textContent = 'Up to ' + best + '% off tonight'; disc.classList.remove('hidden'); }
      else disc.classList.add('hidden');

      renderMenuBody(data);
      show('viewMenu');
    }).catch(function (err) { Z.toast(err.message, true); });
  }

  function renderMenuBody(data) {
    var body = $('#menuBody'), jump = $('#menuJump');
    clear(body); clear(jump);

    var cats = data.categories.slice();
    if (data.uncategorised && data.uncategorised.length) {
      cats.push({ id: 0, name: 'More', note: '', items: data.uncategorised });
    }
    if (!cats.length) {
      body.appendChild(el('p', { className: 'empty', text: 'This kitchen has not published a menu yet.' }));
      return;
    }

    cats.forEach(function (cat, idx) {
      jump.appendChild(el('button', {
        className: idx === 0 ? 'is-on' : '', text: cat.name,
        attrs: { type: 'button' },
        on: {
          click: function (e) {
            var target = document.getElementById('cat-' + cat.id);
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            Array.prototype.forEach.call(jump.children, function (b) { b.classList.remove('is-on'); });
            e.currentTarget.classList.add('is-on');
          }
        }
      }));

      var block = el('section', { className: 'catblock', attrs: { id: 'cat-' + cat.id } }, [
        el('h2', { className: 'catblock__name', text: cat.name }),
        cat.note ? el('p', { className: 'catblock__note', text: cat.note }) : null
      ]);

      cat.items.forEach(function (item) { block.appendChild(itemRow(item, data.vendor)); });
      body.appendChild(block);
    });
  }

  function itemRow(item, vendor) {
    var tags = (item.tags || []).map(function (t) {
      return el('span', { className: 'tag tag--' + t, text: t });
    });

    var priceBox = el('div', { className: 'mitem__price money' }, [
      item.discount_percent ? el('span', { className: 'mitem__was money', text: money(item.base_price_rwf) }) : null,
      document.createTextNode(money(item.price_rwf))
    ]);

    var right = el('div', { className: 'mitem__right' }, [priceBox]);

    if (!item.is_available) {
      right.appendChild(el('span', { className: 'mitem__out', text: 'Sold out' }));
    } else if (vendor.accepts_orders && vendor.is_open) {
      right.appendChild(qtyControl(vendor, item));
    }

    return el('div', {
      className: 'mitem' + (item.is_available ? '' : ' mitem--out')
    }, [
      el('div', { className: 'mitem__main' }, [
        el('div', { className: 'mitem__name', text: item.name }),
        item.description ? el('p', { className: 'mitem__desc', text: item.description }) : null,
        tags.length ? el('div', { className: 'mitem__tags' }, tags) : null
      ]),
      right
    ]);
  }

  function qtyControl(vendor, item) {
    var current = cartQty(vendor.id, item.id);
    if (!current) {
      return el('button', {
        className: 'addbtn', text: 'Add', attrs: { type: 'button' },
        on: { click: function (e) { setQty(vendor, item, 1); replaceControl(e.currentTarget, vendor, item); } }
      });
    }
    var label = el('span', { text: String(current) });
    var box = el('div', { className: 'qty' }, [
      el('button', {
        text: '−', attrs: { type: 'button', 'aria-label': 'Remove one' },
        on: { click: function (e) { bump(e, vendor, item, -1); } }
      }),
      label,
      el('button', {
        text: '+', attrs: { type: 'button', 'aria-label': 'Add one' },
        on: { click: function (e) { bump(e, vendor, item, 1); } }
      })
    ]);
    return box;
  }

  function replaceControl(node, vendor, item) {
    var fresh = qtyControl(vendor, item);
    node.parentNode.replaceChild(fresh, node);
  }

  function bump(e, vendor, item, delta) {
    var next = cartQty(vendor.id, item.id) + delta;
    setQty(vendor, item, next);
    var holder = e.currentTarget.parentNode;
    replaceControl(holder, vendor, item);
  }

  /* ================= cart ================= */

  function cartQty(vendorId, itemId) {
    var bucket = state.cart[vendorId];
    return (bucket && bucket.items && bucket.items[itemId]) ? bucket.items[itemId].qty : 0;
  }

  function setQty(vendor, item, qty) {
    qty = Math.max(0, Math.min(20, qty));
    var bucket = state.cart[vendor.id] || (state.cart[vendor.id] = {
      vendor_name: vendor.name, vendor_accent: vendor.accent, items: {}
    });
    if (!bucket.items) bucket.items = {};
    if (qty === 0) delete bucket.items[item.id];
    else bucket.items[item.id] = {
      qty: qty, name: item.name, price: item.price_rwf,
      base: item.base_price_rwf, discount: item.discount_percent
    };
    if (!Object.keys(bucket.items).length) delete state.cart[vendor.id];
    Z.store.set('zc_cart', state.cart);
    renderCartBar();
  }

  function cartSummary() {
    var count = 0, total = 0, saved = 0, groups = [];
    Object.keys(state.cart).forEach(function (vid) {
      var bucket = state.cart[vid];
      var lines = [];
      Object.keys(bucket.items || {}).forEach(function (iid) {
        var line = bucket.items[iid];
        count += line.qty;
        total += line.price * line.qty;
        saved += Math.max(0, (line.base || line.price) - line.price) * line.qty;
        lines.push({ id: iid, line: line });
      });
      if (lines.length) groups.push({ vendorId: vid, bucket: bucket, lines: lines });
    });
    return { count: count, total: total, saved: saved, groups: groups };
  }

  function renderCartBar() {
    var s = cartSummary();
    var bar = $('#cartBar');
    bar.classList.toggle('is-on', s.count > 0);
    $('#cartCount').textContent = Z.plural(s.count, 'item');
    $('#cartTotal').textContent = money(s.total);
  }

  function renderCart() {
    var body = $('#cartBody');
    clear(body);
    var s = cartSummary();

    if (!s.count) {
      body.appendChild(el('p', { className: 'empty', text: 'Your basket is empty.' }));
      return;
    }

    s.groups.forEach(function (g) {
      var group = el('div', { className: 'cartgroup' }, [
        el('div', {
          className: 'cartgroup__head', text: g.bucket.vendor_name,
          style: { '--accent': g.bucket.vendor_accent }
        })
      ]);

      g.lines.forEach(function (entry) {
        var line = entry.line;
        var label = el('span', { text: String(line.qty) });
        group.appendChild(el('div', { className: 'cartline' }, [
          el('div', { className: 'cartline__main', style: { flex: '1 1 auto' } }, [
            el('div', { className: 'cartline__name', text: line.name }),
            el('div', { className: 'cartline__meta money', text: money(line.price) + ' each' })
          ]),
          el('div', { className: 'qty' }, [
            el('button', {
              text: '−', attrs: { type: 'button', 'aria-label': 'Remove one' },
              on: { click: function () { adjustStored(g.vendorId, entry.id, -1); } }
            }),
            label,
            el('button', {
              text: '+', attrs: { type: 'button', 'aria-label': 'Add one' },
              on: { click: function () { adjustStored(g.vendorId, entry.id, 1); } }
            })
          ]),
          el('div', { className: 'money', style: { 'min-width': '84px', 'text-align': 'right', 'font-weight': '700' },
            text: money(line.price * line.qty) })
        ]));
      });

      body.appendChild(group);
    });

    body.appendChild(totalsBlock(s));
    body.appendChild(el('button', {
      className: 'btn btn--block', text: 'Continue', attrs: { type: 'button' },
      style: { 'margin-top': '18px' },
      on: { click: openCheckout }
    }));
    body.appendChild(el('button', {
      className: 'btn btn--ghost btn--block', text: 'Empty basket', attrs: { type: 'button' },
      style: { 'margin-top': '10px' },
      on: {
        click: function () {
          state.cart = {}; Z.store.set('zc_cart', state.cart);
          renderCartBar(); renderCart(); Z.closeSheet('cartSheet');
        }
      }
    }));
  }

  function totalsBlock(s) {
    var rows = [
      el('div', { className: 'totals__row' }, [
        el('span', { text: 'Items' }), el('span', { className: 'money', text: String(s.count) })
      ])
    ];
    if (s.saved > 0) {
      rows.push(el('div', { className: 'totals__row totals__row--save' }, [
        el('span', { text: 'Discount' }),
        el('span', { className: 'money', text: '− ' + money(s.saved) })
      ]));
    }
    rows.push(el('div', { className: 'totals__row totals__row--big' }, [
      el('span', { text: 'To pay on delivery' }),
      el('span', { className: 'money', text: money(s.total) })
    ]));
    return el('div', { className: 'totals' }, rows);
  }

  function adjustStored(vendorId, itemId, delta) {
    var bucket = state.cart[vendorId];
    if (!bucket || !bucket.items[itemId]) return;
    var next = Math.max(0, Math.min(20, bucket.items[itemId].qty + delta));
    if (next === 0) delete bucket.items[itemId];
    else bucket.items[itemId].qty = next;
    if (!Object.keys(bucket.items).length) delete state.cart[vendorId];
    Z.store.set('zc_cart', state.cart);
    renderCartBar();
    renderCart();
  }

  /* ================= checkout ================= */

  function openCheckout() {
    var s = cartSummary();
    if (!s.count) return;
    track('order_start');

    var tableField = $('#fTableField');
    if (state.mode === 'PICKUP') {
      tableField.classList.add('hidden');
    } else {
      tableField.classList.remove('hidden');
      $('#fTableLabel').textContent =
        state.mode === 'BOTH' ? 'Table number (if you are seated)' : 'Table number';
      fillTableSelect($('#fTable'), true);
    }
    $('#collectNote').classList.toggle('hidden', state.mode === 'TABLE');

    $('#fName').value = Z.store.get('zc_name', '') || '';
    $('#fPhone').value = Z.store.get('zc_phone', '') || '';
    clear($('#checkoutTotals'));
    $('#checkoutTotals').appendChild(totalsBlock(s));
    ['eTable', 'eName', 'ePhone'].forEach(function (id) { $('#' + id).classList.add('hidden'); });

    Z.closeSheet('cartSheet');
    Z.openSheet('checkoutSheet');
  }

  function placeOrder() {
    var btn = $('#placeBtn');
    var s = cartSummary();
    if (!s.count) return;

    ['eTable', 'eName', 'ePhone'].forEach(function (id) { $('#' + id).classList.add('hidden'); });

    // Which table this order is for. In BOTH mode an empty choice is a real
    // answer ("I am standing"), so it must not fall back to a remembered table.
    var chosen = '';
    if (state.mode === 'TABLE') chosen = $('#fTable').value || state.table || '';
    else if (state.mode === 'BOTH') chosen = $('#fTable').value || '';

    // The signed token only proves the table it was scanned at. If the guest
    // has since picked a different one, sending it would silently override
    // their choice, because the server trusts a valid signature over free text.
    var token = (chosen && chosen === state.table) ? (state.tableToken || '') : '';

    var payload = {
      table_token: token,
      table_code: chosen,
      name: $('#fName').value,
      phone: $('#fPhone').value,
      note: $('#fNote').value,
      cart: s.groups.map(function (g) {
        return {
          vendor_id: Number(g.vendorId),
          lines: g.lines.map(function (e) { return { item_id: Number(e.id), qty: e.line.qty }; })
        };
      })
    };

    btn.disabled = true;
    btn.textContent = 'Sending…';

    Z.api('POST', '/api/orders', payload).then(function (data) {
      Z.store.set('zc_name', payload.name);
      Z.store.set('zc_phone', payload.phone);
      state.groups.unshift(data.group_key);
      state.groups = state.groups.slice(0, 10);
      Z.store.set('zc_groups', state.groups);

      state.cart = {};
      Z.store.set('zc_cart', state.cart);
      renderCartBar();

      $('#ordersBtn').classList.remove('hidden');
      Z.closeSheet('checkoutSheet');
      Z.toast('Sent. The kitchen will confirm shortly.');
      openTracking();
    }).catch(function (err) {
      var map = { table_code: 'eTable', name: 'eName', phone: 'ePhone' };
      var target = map[err.field];
      if (target) {
        var node = $('#' + target);
        node.textContent = err.message;
        node.classList.remove('hidden');
      } else {
        Z.toast(err.message, true);
      }
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = 'Send order';
    });
  }

  /* ================= tracking ================= */

  var STEPS = ['PENDING', 'ACCEPTED', 'READY', 'DELIVERED', 'PAID'];
  var STEP_LABEL = { PENDING: 'Sent', ACCEPTED: 'Cooking', READY: 'Ready', DELIVERED: 'Delivered', PAID: 'Paid' };

  function openTracking() {
    show('viewTrack');
    refreshTracking();
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(refreshTracking, 12000);
  }

  function stopTracking() {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function refreshTracking() {
    if (!state.groups.length) return;
    Promise.all(state.groups.slice(0, 3).map(function (key) {
      return Z.api('GET', '/api/orders/group/' + encodeURIComponent(key))
        .then(function (d) { return d.orders; })
        .catch(function () { return []; });
    })).then(function (lists) {
      var all = [];
      lists.forEach(function (l) { all = all.concat(l); });
      renderTracking(all);
    });
  }

  function renderTracking(list) {
    var body = $('#trackBody');
    clear(body);
    if (!list.length) {
      body.appendChild(el('p', { className: 'empty', text: 'No orders yet.' }));
      return;
    }

    list.sort(function (a, b) { return (a.placed_at < b.placed_at) ? 1 : -1; });

    list.forEach(function (o) {
      var idx = STEPS.indexOf(o.status);
      var dead = (o.status === 'REJECTED' || o.status === 'CANCELLED');

      var steps = el('div', { className: 'steps' }, STEPS.map(function (s, i) {
        var cls = 'step';
        if (dead) cls += i === 0 ? ' is-bad' : '';
        else if (i <= idx) cls += ' is-on';
        return el('div', { className: cls });
      }));

      var labels = el('div', { className: 'steplabels' }, STEPS.map(function (s) {
        return el('span', { text: STEP_LABEL[s] });
      }));

      var lines = o.items.map(function (it) {
        return el('div', { className: 'cartline', style: { padding: '9px 0' } }, [
          el('div', { style: { flex: '1 1 auto' } }, [
            el('div', { className: 'cartline__name', text: it.qty + ' × ' + it.name_snapshot })
          ]),
          el('div', { className: 'money', style: { 'font-weight': '700' }, text: money(it.line_total_rwf) })
        ]);
      });

      var actions = [];
      if (o.status === 'PENDING') {
        actions.push(el('button', {
          className: 'btn btn--ghost btn--sm', text: 'Withdraw', attrs: { type: 'button' },
          on: {
            click: function () {
              Z.api('POST', '/api/orders/' + encodeURIComponent(o.public_code) + '/cancel')
                .then(function () { Z.toast('Order withdrawn.'); refreshTracking(); })
                .catch(function (e) { Z.toast(e.message, true); });
            }
          }
        }));
      }

      var payLine = null;
      if (o.status === 'READY' || o.status === 'DELIVERED') {
        var who = o.table_code ? 'the runner' : 'the kitchen';
        payLine = el('div', { className: 'paynote' }, [
          el('strong', {
            text: (o.table_code ? 'Pay now: ' : 'Collect with code ' + o.short_code + '. Pay ')
              + money(o.total_rwf) + '. '
          }),
          document.createTextNode(o.momo_code
            ? 'Cash, or MoMo code ' + o.momo_code + '.'
            : 'Cash or MoMo to ' + who + '.')
        ]);
      }

      body.appendChild(el('div', { className: 'card trackcard', style: { '--accent': o.vendor_accent } }, [
        el('div', { className: 'trackcard__head' }, [
          el('span', { className: 'trackcard__vendor', text: o.vendor_name }),
          el('span', { className: 'pill pill--' + o.status, text: o.status.toLowerCase() }),
          el('span', { className: 'trackcard__code', text: o.short_code })
        ]),
        el('p', { className: 'small muted', style: { margin: '0 0 4px' },
          text: (o.table_code ? 'Table ' + o.table_code : 'Collect at the kitchen — code ' + o.short_code)
            + ' · placed ' + Z.timeAgo(o.placed_at) }),
        dead && o.cancel_reason
          ? el('p', { className: 'small', style: { color: '#FF9B94' }, text: o.cancel_reason })
          : null,
        steps, labels,
        el('div', { style: { 'margin-top': '14px' } }, lines),
        el('div', { className: 'totals' }, [
          el('div', { className: 'totals__row totals__row--big' }, [
            el('span', { text: 'Total' }),
            el('span', { className: 'money', text: money(o.total_rwf) })
          ])
        ]),
        payLine,
        actions.length ? el('div', { style: { 'margin-top': '14px' } }, actions) : null
      ]));
    });
  }

  /* ================= wiring ================= */

  Z.wireSheet('cartSheet', 'cartClose');
  Z.wireSheet('checkoutSheet', 'checkoutClose');
  Z.wireSheet('tableSheet', 'tableClose');

  $('#viewCartBtn').addEventListener('click', function () { renderCart(); Z.openSheet('cartSheet'); });
  $('#placeBtn').addEventListener('click', placeOrder);
  $('#menuBack').addEventListener('click', function () { show('viewHome'); });
  $('#trackBack').addEventListener('click', function () { stopTracking(); show('viewHome'); });
  $('#ordersBtn').addEventListener('click', openTracking);

  $('#changeTableBtn').addEventListener('click', function () {
    fillTableSelect($('#fTablePick'), true);
    Z.openSheet('tableSheet');
  });
  $('#tableSave').addEventListener('click', function () {
    var picked = $('#fTablePick').value;
    if (!picked) { Z.toast('Pick a table first.', true); return; }
    state.table = picked;
    state.tableToken = '';           // manual pick is not a signed token
    Z.store.set('zc_table', picked);
    Z.store.del('zc_table_token');
    renderTable();
    Z.closeSheet('tableSheet');
    Z.toast('Table set to ' + picked + '.');
  });

  $('#joinLink').addEventListener('click', function () {
    // The server counts the click on redirect; nothing to do here.
  });

  boot();
})();
