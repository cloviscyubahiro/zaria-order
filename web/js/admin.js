/* Admin dashboard. */
(function () {
  'use strict';

  var el = Z.el, clear = Z.clear, $ = Z.$, money = Z.money;
  var state = { tab: 'overview', days: 7, dash: null, settings: {} };

  /* ================= session ================= */

  function start() {
    Z.api('GET', '/api/admin/me').then(onSession).catch(function (e) {
      $('#loginView').classList.remove('hidden');
      $('#shell').classList.add('hidden');
      /* A dead server and an expired session both land here, but they need
         different actions. Say which one it is instead of showing a bare
         login box that will fail again the moment it is used. */
      if (e && e.offline) {
        var err = $('#lErr');
        err.textContent = e.message;
        err.classList.remove('hidden');
      }
    });
  }

  function onSession(data) {
    Z.setCsrf(data.csrf);
    $('#loginView').classList.add('hidden');
    $('#shell').classList.remove('hidden');
    $('#navWho').textContent = data.user.display;
    $('#pwBanner').classList.toggle('hidden', !data.user.must_change);
    loadDashboard();
  }

  function login() {
    var btn = $('#loginBtn'), err = $('#lErr');
    err.classList.add('hidden');
    btn.disabled = true; btn.textContent = 'Signing in…';
    Z.api('POST', '/api/admin/login', {
      username: $('#lUser').value.trim(), password: $('#lPass').value
    }).then(function (d) {
      Z.setCsrf(d.csrf);
      $('#lPass').value = '';
      return Z.api('GET', '/api/admin/me').then(onSession);
    }).catch(function (e) {
      err.textContent = e.message; err.classList.remove('hidden');
    }).finally(function () {
      btn.disabled = false; btn.textContent = 'Sign in';
    });
  }

  /* ================= tabs ================= */

  var PANES = {
    overview: 'paneOverview', orders: 'paneOrders', vendors: 'paneVendors',
    tables: 'paneTables', notices: 'paneNotices', settings: 'paneSettings'
  };

  function switchTab(name) {
    state.tab = name;
    Array.prototype.forEach.call(document.querySelectorAll('.nav .tab'), function (b) {
      b.classList.toggle('is-on', b.getAttribute('data-tab') === name);
    });
    Object.keys(PANES).forEach(function (k) {
      $('#' + PANES[k]).classList.toggle('hidden', k !== name);
    });
    if (name === 'overview') loadDashboard();
    if (name === 'orders') loadOrders();
    if (name === 'vendors') loadVendors();
    if (name === 'tables') loadTables();
    if (name === 'notices') loadAnnouncements();
    if (name === 'settings') loadSettings();
  }

  /* ================= overview ================= */

  function loadDashboard() {
    Z.api('GET', '/api/admin/dashboard?days=' + state.days).then(function (d) {
      state.dash = d;
      renderStats(d);
      renderVendorBars(d);
      renderCommunity(d);
      renderDays(d);
      renderTopItems(d);
      renderTables(d);
      renderPayments(d);
      renderHours(d);
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  function renderStats(d) {
    var box = $('#statGrid');
    clear(box);
    var m = d.money, t = d.traffic;
    [
      ['Revenue collected', money(m.revenue), 'ok', m.paid_orders + ' paid orders'],
      ['Still to collect', money(m.outstanding), m.outstanding ? 'warn' : '', 'Delivered or in progress'],
      ['Average order', money(m.avg_order_rwf), '', ''],
      ['Discounts given', money(m.discounts_given), '', 'Off the paid orders'],
      ['Visitors', String(t.visitors), '', t.page_views + ' screen opens'],
      ['Ordered', t.order_conversion + '%', '', 'of visitors placed an order'],
      ['Rejected / cancelled', String((m.rejected || 0) + (m.cancelled || 0)),
        ((m.rejected || 0) + (m.cancelled || 0)) ? 'warn' : '', 'Watch this during events'],
      ['Time to accept', d.timing.accept_minutes + ' min', '', 'Then ' + d.timing.cook_minutes + ' min to ready']
    ].forEach(function (r) {
      box.appendChild(el('div', { className: 'stat' }, [
        el('div', { className: 'stat__label', text: r[0] }),
        el('div', { className: 'stat__value' + (r[2] ? ' stat__value--' + r[2] : ''), text: r[1] }),
        r[3] ? el('div', { className: 'stat__sub', text: r[3] }) : null
      ]));
    });
  }

  function bars(container, rows, formatter) {
    clear(container);
    if (!rows.length) {
      container.appendChild(el('p', { className: 'small muted', text: 'Nothing yet.' }));
      return;
    }
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; })) || 1;
    rows.forEach(function (r) {
      container.appendChild(el('div', { className: 'bar' }, [
        el('div', { className: 'bar__label', text: r.label }),
        el('div', { className: 'bar__track' }, [
          el('div', {
            className: 'bar__fill',
            style: {
              width: Math.max(2, Math.round(100 * r.value / max)) + '%',
              background: r.color ? ('linear-gradient(90deg,' + r.color + ',' + r.color + ')') : ''
            }
          })
        ]),
        el('div', { className: 'bar__value', text: formatter(r.value) })
      ]));
    });
  }

  function renderVendorBars(d) {
    bars($('#vendorBars'), d.by_vendor.map(function (v) {
      return { label: v.name, value: v.revenue, color: v.accent };
    }), money);
  }

  function renderCommunity(d) {
    var box = $('#communityStats');
    clear(box);
    var t = d.traffic;
    [
      ['Joined the group (taps)', String(t.whatsapp_unique), 'ok', 'unique people in this period'],
      ['All-time taps', String(t.whatsapp_all_time), '', 'since the system started'],
      ['Share of visitors', t.whatsapp_conversion + '%', '', 'who tapped the invite']
    ].forEach(function (r) {
      box.appendChild(el('div', { className: 'stat' }, [
        el('div', { className: 'stat__label', text: r[0] }),
        el('div', { className: 'stat__value' + (r[2] ? ' stat__value--' + r[2] : ''), text: r[1] }),
        el('div', { className: 'stat__sub', text: r[3] })
      ]));
    });
  }

  function renderDays(d) {
    var box = $('#daySparks'), labels = $('#dayLabels');
    clear(box); clear(labels);
    if (!d.by_day.length) {
      box.appendChild(el('p', { className: 'small muted', text: 'No orders yet.' }));
      return;
    }
    var max = Math.max.apply(null, d.by_day.map(function (r) { return r.revenue; })) || 1;
    d.by_day.forEach(function (row) {
      box.appendChild(el('div', {
        className: 'spark',
        style: { height: Math.max(3, Math.round(100 * row.revenue / max)) + '%' },
        attrs: { title: row.day + ' · ' + money(row.revenue) + ' · ' + row.orders + ' orders' }
      }));
      labels.appendChild(el('span', { text: row.day.slice(5) }));
    });
  }

  function table(node, headers, rows) {
    clear(node);
    var thead = el('thead', {}, [el('tr', {}, headers.map(function (h) {
      return el('th', { text: h.label, className: h.num ? 'num' : '' });
    }))]);
    var tbody = el('tbody', {}, rows.map(function (r) {
      return el('tr', {}, r.map(function (cell, i) {
        return el('td', {
          text: cell === null || cell === undefined ? '' : String(cell),
          className: headers[i] && headers[i].num ? 'num' : ''
        });
      }));
    }));
    node.appendChild(thead);
    node.appendChild(tbody);
    if (!rows.length) {
      tbody.appendChild(el('tr', {}, [
        el('td', { text: 'Nothing yet.', className: 'muted', attrs: { colspan: String(headers.length) } })
      ]));
    }
  }

  function renderTopItems(d) {
    table($('#topItems'),
      [{ label: 'Item' }, { label: 'Kitchen' }, { label: 'Sold', num: true }, { label: 'Revenue', num: true }],
      d.top_items.map(function (r) { return [r.name, r.vendor, r.qty, money(r.revenue)]; }));
  }

  function renderTables(d) {
    table($('#tableTable'),
      [{ label: 'Table' }, { label: 'Orders', num: true }, { label: 'Revenue', num: true }],
      d.by_table.map(function (r) { return [r.table_code, r.orders, money(r.revenue)]; }));
  }

  function renderPayments(d) {
    var label = { CASH: 'Cash', MOMO: 'MoMo', CARD: 'Card', OTHER: 'Other', UNSPECIFIED: 'Not recorded' };
    table($('#payTable'),
      [{ label: 'Method' }, { label: 'Orders', num: true }, { label: 'Revenue', num: true }],
      d.payment_mix.map(function (r) { return [label[r.method] || r.method, r.orders, money(r.revenue)]; }));
  }

  function renderHours(d) {
    bars($('#hourBars'), d.by_hour.map(function (r) {
      // placed_at is stored UTC; Kigali is UTC+2 year round.
      var h = (parseInt(r.hour, 10) + 2) % 24;
      return { label: String(h).padStart(2, '0') + ':00', value: r.orders };
    }), function (v) { return v + ' orders'; });
  }

  /* ================= orders ================= */

  function loadOrders() {
    var status = $('#statusSel').value;
    Z.api('GET', '/api/admin/orders?limit=150' + (status ? '&status=' + status : ''))
      .then(function (d) {
        table($('#ordersTable'),
          [{ label: 'Time' }, { label: 'Code' }, { label: 'Kitchen' }, { label: 'Table' },
           { label: 'Guest' }, { label: 'Status' }, { label: 'Total', num: true }, { label: 'Paid by' }],
          d.orders.map(function (o) {
            return [
              Z.clock(o.placed_at), o.short_code, o.vendor_name, o.table_code || '—',
              o.customer_name || '—', o.status.toLowerCase(), money(o.total_rwf),
              o.payment_method || '—'
            ];
          }));
      }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= vendors ================= */

  function loadVendors() {
    Z.api('GET', '/api/admin/vendors').then(function (d) {
      var box = $('#vendorList');
      clear(box);
      d.vendors.forEach(function (v) {
        var users = v.users.map(function (u) {
          return el('div', { className: 'rowitem' + (u.is_active ? '' : ' rowitem--off') }, [
            el('div', { className: 'rowitem__main' }, [
              el('div', { className: 'rowitem__name', text: u.username }),
              el('div', {
                className: 'rowitem__meta',
                text: (u.last_login ? 'Last in ' + Z.timeAgo(u.last_login) : 'Never signed in') +
                      (u.must_change ? ' · still on first password' : '')
              })
            ]),
            el('div', { className: 'rowitem__actions' }, [
              el('button', {
                className: 'btn btn--ghost btn--sm', text: 'Reset password', attrs: { type: 'button' },
                on: {
                  click: function () {
                    if (!window.confirm('Reset the password for ' + u.username + '?')) return;
                    Z.api('POST', '/api/admin/vendor-users/' + u.id + '/reset').then(function (r) {
                      window.alert('New one-time password for ' + u.username + ':\n\n' + r.temp_password +
                                   '\n\nThey must change it at first sign-in.');
                      loadVendors();
                    }).catch(function (e) { Z.toast(e.message, true); });
                  }
                }
              }),
              el('button', {
                className: 'btn btn--sm ' + (u.is_active ? 'btn--danger' : 'btn--ok'),
                text: u.is_active ? 'Disable' : 'Enable', attrs: { type: 'button' },
                on: {
                  click: function () {
                    Z.api('PATCH', '/api/admin/vendor-users/' + u.id, { is_active: !u.is_active })
                      .then(loadVendors).catch(function (e) { Z.toast(e.message, true); });
                  }
                }
              })
            ])
          ]);
        });

        var newUser = el('div', { className: 'inline', style: { 'margin-top': '10px' } }, [
          el('div', { className: 'field' }, [
            el('label', { text: 'New login for this kitchen' }),
            el('input', { className: 'input', attrs: { type: 'text', maxlength: '40', placeholder: 'username', id: 'nu' + v.id } })
          ]),
          el('button', {
            className: 'btn btn--sm', text: 'Create', attrs: { type: 'button' },
            on: {
              click: function () {
                var input = document.getElementById('nu' + v.id);
                var name = (input.value || '').trim();
                if (!name) { Z.toast('Enter a username.', true); return; }
                Z.api('POST', '/api/admin/vendor-users', {
                  vendor_id: v.id, username: name, display: v.name
                }).then(function (r) {
                  input.value = '';
                  window.alert('Login created.\n\nUsername: ' + r.username +
                               '\nOne-time password: ' + r.temp_password +
                               '\n\nHand this over in person. It cannot be shown again.');
                  loadVendors();
                }).catch(function (e) { Z.toast(e.message, true); });
              }
            }
          })
        ]);

        box.appendChild(el('div', { className: 'card', style: { 'margin-bottom': '16px' } }, [
          el('div', { className: 'catgroup__head' }, [
            el('span', { className: 'catgroup__name', text: v.name, style: { color: v.accent } }),
            el('span', { className: 'small muted', text: v.kind }),
            el('span', { style: { 'margin-left': 'auto' }, className: 'rowitem__actions' }, [
              el('button', {
                className: 'btn btn--sm ' + (v.is_open ? 'btn--ok' : 'btn--danger'),
                text: v.is_open ? 'Open' : 'Closed', attrs: { type: 'button' },
                on: {
                  click: function () {
                    Z.api('PATCH', '/api/admin/vendors/' + v.id, { is_open: !v.is_open })
                      .then(loadVendors).catch(function (e) { Z.toast(e.message, true); });
                  }
                }
              }),
              el('button', {
                className: 'btn btn--sm ' + (v.accepts_orders ? 'btn--ok' : 'btn--ghost'),
                text: v.accepts_orders ? 'Takes orders' : 'Menu only', attrs: { type: 'button' },
                on: {
                  click: function () {
                    Z.api('PATCH', '/api/admin/vendors/' + v.id, { accepts_orders: !v.accepts_orders })
                      .then(loadVendors).catch(function (e) { Z.toast(e.message, true); });
                  }
                }
              })
            ])
          ])
        ].concat(users, [newUser])));
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= tables + QR ================= */

  function loadWifi() {
    Z.api('GET', '/api/admin/settings').then(function (d) {
      $('#setSsid').value = d.settings.wifi_ssid || '';
      $('#setWifiPw').value = d.settings.wifi_password || '';
      var box = $('#wifiPreview');
      clear(box);
      if (!d.settings.wifi_ssid) {
        box.appendChild(el('p', { className: 'small muted', text: 'No network saved yet.' }));
        return;
      }
      box.appendChild(el('div', { className: 'qrcard', style: { 'max-width': '190px' } }, [
        el('img', {
          // Cache-bust so a saved change shows immediately rather than
          // leaving the old network on screen.
          attrs: { src: '/api/admin/qr/wifi?v=' + Date.now(), alt: 'Wi-Fi join code' }
        }),
        el('div', { className: 'qrcard__code', text: d.settings.wifi_ssid }),
        el('div', { style: { 'font-size': '11px', opacity: '.7' }, text: 'Scan to join' })
      ]));
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  function loadTables() {
    loadWifi();
    Z.api('GET', '/api/admin/tables').then(function (d) {
      var grid = $('#qrGrid');
      clear(grid);
      $('#tableCount').textContent = d.tables.length
        ? d.tables.length + ' table' + (d.tables.length === 1 ? '' : 's') + ' set up'
        : '';
      if (!d.tables.length) {
        grid.appendChild(el('p', {
          className: 'empty',
          text: 'No tables. Add some above, or leave it empty and set '
              + 'Settings → "How guests get their order" to Standing.'
        }));
        return;
      }
      d.tables.forEach(function (t) {
        var card = el('div', { className: 'qrcard' }, [
          el('img', {
            attrs: {
              src: '/api/admin/qr?code=' + encodeURIComponent(t.code),
              alt: 'QR code for table ' + t.code, loading: 'lazy'
            }
          }),
          el('div', { className: 'qrcard__code', text: t.code }),
          el('div', { style: { 'font-size': '11px', opacity: '.7' }, text: t.zone || '' }),
          el('button', {
            className: 'qrcard__del', text: 'Remove', attrs: { type: 'button' },
            on: {
              click: function () {
                if (!window.confirm('Remove table ' + t.code + '?')) return;
                Z.api('DELETE', '/api/admin/tables/' + t.id)
                  .then(function () { loadTables(); })
                  .catch(function (e) { Z.toast(e.message, true); });
              }
            }
          })
        ]);
        grid.appendChild(card);
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= notices ================= */

  function loadAnnouncements() {
    Z.api('GET', '/api/admin/announcements').then(function (d) {
      var box = $('#annList');
      clear(box);
      if (!d.announcements.length) {
        box.appendChild(el('p', { className: 'empty', text: 'Nothing posted.' }));
        return;
      }
      d.announcements.forEach(function (a) {
        box.appendChild(el('div', { className: 'rowitem' + (a.is_active ? '' : ' rowitem--off') }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: a.body }),
            el('div', {
              className: 'rowitem__meta',
              text: (a.audience === 'VENDORS'
                      ? 'To the kitchens'
                      : (a.vendor_name || 'Venue-wide') + ' · ' + a.kind)
                    + ' · ' + Z.timeAgo(a.created_at)
            })
          ]),
          el('div', { className: 'rowitem__actions' }, [
            el('button', {
              className: 'btn btn--sm ' + (a.is_active ? 'btn--danger' : 'btn--ok'),
              text: a.is_active ? 'Take down' : 'Put back', attrs: { type: 'button' },
              on: {
                click: function () {
                  Z.api('PATCH', '/api/admin/announcements/' + a.id, { is_active: !a.is_active })
                    .then(loadAnnouncements).catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
        ]));
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  /* ================= settings ================= */

  function loadKiosks() {
    Z.api('GET', '/api/admin/kiosks').then(function (d) {
      state.kioskHere = !!d.this_machine_registered;
      var btn = $('#kioskBtn');
      btn.textContent = d.this_machine_registered ? 'Registered' : 'Register';
      btn.className = 'btn btn--sm ' + (d.this_machine_registered ? 'btn--ok' : '');
      btn.disabled = d.this_machine_registered || !d.on_venue_network;
      $('#kioskHint').textContent = d.this_machine_registered
        ? 'This machine can order without hitting the per-guest limits.'
        : (d.on_venue_network
            ? 'Press Register on the machine guests will order from.'
            : 'You are on the public address. Open admin on the kiosk itself to register it.');

      var box = $('#kioskList');
      clear(box);
      if (!d.kiosks.length) {
        box.appendChild(el('p', { className: 'small muted', text: 'No kiosks registered.' }));
        return;
      }
      d.kiosks.forEach(function (k) {
        box.appendChild(el('div', { className: 'rowitem' }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: k.label }),
            el('div', { className: 'rowitem__meta', text: 'added ' + Z.timeAgo(k.created_at) })
          ]),
          el('div', { className: 'rowitem__actions' }, [
            el('button', {
              className: 'btn btn--sm btn--danger', text: 'Remove',
              attrs: { type: 'button' },
              on: {
                click: function () {
                  Z.api('DELETE', '/api/admin/blocklist/' + k.id)
                    .then(loadKiosks)
                    .catch(function (e) { Z.toast(e.message, true); });
                }
              }
            })
          ])
        ]));
      });
    }).catch(function (e) { Z.toast(e.message, true); });
  }

  function loadSettings() {
    loadKiosks();
    Z.api('GET', '/api/admin/settings').then(function (d) {
      state.settings = d.settings;
      $('#setName').value = d.settings.venue_name || '';
      $('#setWa').value = d.settings.whatsapp_url || '';
      $('#setBase').value = d.settings.public_base_url || '';
      $('#setNotice').value = d.settings.venue_notice || '';
      $('#setMode').value = d.service_mode || 'TABLE';

      $('#setIpCap').value = (d.limits && d.limits.orders_per_shared_ip_hour) || 400;
      $('#setDeviceCap').value = (d.limits && d.limits.orders_per_device_hour) || 20;
      state.staffNetwork = d.staff_network || 'ANY';
      state.onVenueNetwork = !!d.on_venue_network;
      var lanOnly = state.staffNetwork === 'LAN_ONLY';
      var netBtn = $('#staffNetToggle');
      netBtn.textContent = lanOnly ? 'On' : 'Off';
      netBtn.className = 'btn btn--sm ' + (lanOnly ? 'btn--ok' : '');
      $('#staffNetHint').textContent = lanOnly
        ? 'Sign-in works only from Zaria Wi-Fi. The login pages are not reachable from the internet.'
        : (state.onVenueNetwork
            ? 'Anyone who finds the address can reach the login pages. Turn this on once the public address is live.'
            : 'You are on the public address right now, so this cannot be turned on from here — it would lock you out. Use the venue address.');
      var on = d.settings.ordering_enabled !== '0';
      var btn = $('#orderingToggle');
      btn.textContent = on ? 'On' : 'Paused';
      btn.className = 'btn btn--sm ' + (on ? 'btn--ok' : 'btn--danger');
      $('#retentionNote').textContent =
        'Guest names and phone numbers are scrubbed automatically ' + d.retention_days +
        ' days after an order. Money and item records are kept for reporting. ' +
        'Limits in force: ' + d.limits.open_orders_per_table + ' open orders per table, ' +
        d.limits.orders_per_device_hour + ' orders per phone per hour.';
    }).catch(function (e) { Z.toast(e.message, true); });
    loadBlocklist();
  }

  function loadBlocklist() {
    Z.api('GET', '/api/admin/blocklist').then(function (d) {
      var box = $('#blockList');
      clear(box);
      if (!d.entries.length) {
        box.appendChild(el('p', { className: 'small muted', text: 'Nobody is blocked.' }));
        return;
      }
      d.entries.forEach(function (b) {
        box.appendChild(el('div', { className: 'rowitem' }, [
          el('div', { className: 'rowitem__main' }, [
            el('div', { className: 'rowitem__name', text: b.kind + ' · ' + b.value.slice(0, 14) + '…' }),
            el('div', { className: 'rowitem__meta', text: (b.reason || 'No reason given') + ' · ' + Z.timeAgo(b.created_at) })
          ]),
          el('button', {
            className: 'btn btn--ghost btn--sm', text: 'Unblock', attrs: { type: 'button' },
            on: {
              click: function () {
                Z.api('DELETE', '/api/admin/blocklist/' + b.id)
                  .then(loadBlocklist).catch(function (e) { Z.toast(e.message, true); });
              }
            }
          })
        ]));
      });
    }).catch(function () {});
  }

  /* ================= wiring ================= */

  $('#loginBtn').addEventListener('click', login);
  $('#lPass').addEventListener('keydown', function (e) { if (e.key === 'Enter') login(); });
  $('#lUser').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('#lPass').focus(); });

  $('#logoutBtn').addEventListener('click', function () {
    Z.api('POST', '/api/admin/logout').finally(function () { location.reload(); });
  });

  Array.prototype.forEach.call(document.querySelectorAll('.nav .tab'), function (b) {
    b.addEventListener('click', function () { switchTab(b.getAttribute('data-tab')); });
  });

  $('#rangeSel').addEventListener('change', function () {
    state.days = Number($('#rangeSel').value);
    loadDashboard();
  });
  $('#csvBtn').addEventListener('click', function () {
    window.location.href = '/api/admin/export.csv?days=' + state.days;
  });
  $('#ordersRefresh').addEventListener('click', loadOrders);
  $('#statusSel').addEventListener('change', loadOrders);

  $('#addTablesBtn').addEventListener('click', function () {
    Z.api('POST', '/api/admin/tables', {
      codes: $('#tCodes').value, zone: $('#tZone').value
    }).then(function (r) {
      Z.toast('Added ' + r.added + ' table(s).');
      $('#tCodes').value = '';
      loadTables();
    }).catch(function (e) { Z.toast(e.message, true); });
  });
  $('#replaceTablesBtn').addEventListener('click', function () {
    var codes = $('#tCodes').value.trim();
    var what = codes
      ? 'Replace the whole table list with "' + codes + '"?'
      : 'Remove every table? Guests will not be asked for one.';
    if (!window.confirm(what + '\n\nPast orders keep their table number.')) return;
    Z.api('PUT', '/api/admin/tables', {
      codes: codes, zone: $('#tZone').value, confirm: true
    }).then(function (r) {
      Z.toast(r.total ? 'Table list is now ' + r.total + ' table(s).' : 'All tables removed.');
      $('#tCodes').value = '';
      loadTables();
    }).catch(function (e) { Z.toast(e.message, true); });
  });
  $('#saveWifiBtn').addEventListener('click', function () {
    var pw = $('#setWifiPw').value;
    Z.api('POST', '/api/admin/settings', {
      wifi_ssid: $('#setSsid').value.trim(),
      wifi_password: pw,
      wifi_security: pw ? 'WPA' : 'nopass'
    }).then(function () { Z.toast('Wi-Fi saved.'); loadWifi(); })
      .catch(function (e) { Z.toast(e.message, true); });
  });
  $('#printBtn').addEventListener('click', function () { window.print(); });

  $('#aAudience').addEventListener('change', function () {
    var staff = $('#aAudience').value === 'VENDORS';
    $('#aHint').textContent = staff
      ? 'Only the kitchens see this, on their order screen. Guests never do.'
      : 'This scrolls across every guest’s screen within about half a minute.';
    $('#aBody').placeholder = staff
      ? 'Concert tonight — please post your offers'
      : 'Doors at 7pm · Kitchens close at 11pm';
    $('#aKind').disabled = staff;
  });

  $('#addAnnBtn').addEventListener('click', function () {
    var audience = $('#aAudience').value;
    Z.api('POST', '/api/admin/announcements', {
      audience: audience,
      kind: $('#aKind').value,
      body: $('#aBody').value.trim(),
      priority: 60
    }).then(function () {
      Z.toast(audience === 'VENDORS' ? 'Sent to the kitchens.' : 'Posted for guests.');
      $('#aBody').value = '';
      loadAnnouncements();
    }).catch(function (e) { Z.toast(e.message, true); });
  });

  $('#saveSettingsBtn').addEventListener('click', function () {
    Z.api('POST', '/api/admin/settings', {
      venue_name: $('#setName').value.trim(),
      whatsapp_url: $('#setWa').value.trim(),
      public_base_url: $('#setBase').value.trim(),
      venue_notice: $('#setNotice').value.trim(),
      service_mode: $('#setMode').value,
      orders_per_shared_ip_hour: $('#setIpCap').value.trim(),
      orders_per_device_hour: $('#setDeviceCap').value.trim()
    }).then(function () { Z.toast('Settings saved.'); }).catch(function (e) { Z.toast(e.message, true); });
  });

  $('#kioskBtn').addEventListener('click', function () {
    var label = window.prompt('Name this kiosk (e.g. "Entrance PC")', 'Kiosk');
    if (label === null) return;
    Z.api('POST', '/api/admin/kiosks', { label: label })
      .then(function () { Z.toast('Kiosk registered.'); loadKiosks(); })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#staffNetToggle').addEventListener('click', function () {
    var lanOnly = state.staffNetwork === 'LAN_ONLY';
    if (!lanOnly && !state.onVenueNetwork) {
      Z.toast('Do this from the venue address, or you will lock yourself out.', true);
      return;
    }
    Z.api('POST', '/api/admin/settings', { staff_network: lanOnly ? 'ANY' : 'LAN_ONLY' })
      .then(function () {
        Z.toast(lanOnly ? 'Staff sign-in open again.' : 'Staff sign-in limited to the venue.');
        loadSettings();
      })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#orderingToggle').addEventListener('click', function () {
    var on = state.settings.ordering_enabled !== '0';
    Z.api('POST', '/api/admin/settings', { ordering_enabled: on ? '0' : '1' })
      .then(function () { Z.toast(on ? 'Ordering paused.' : 'Ordering resumed.'); loadSettings(); })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#addBlockBtn').addEventListener('click', function () {
    Z.api('POST', '/api/admin/blocklist', {
      order_code: $('#bCode').value.trim(), kind: $('#bKind').value, reason: 'Blocked from admin'
    }).then(function () { Z.toast('Blocked.'); $('#bCode').value = ''; loadBlocklist(); })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#purgeBtn').addEventListener('click', function () {
    Z.api('POST', '/api/admin/purge-pii')
      .then(function (r) { Z.toast('Scrubbed ' + r.purged + ' old order(s).'); })
      .catch(function (e) { Z.toast(e.message, true); });
  });

  $('#pwBannerBtn').addEventListener('click', function () { switchTab('settings'); $('#pCur').focus(); });
  $('#savePwBtn').addEventListener('click', function () {
    var err = $('#pErr');
    err.classList.add('hidden');
    Z.api('POST', '/api/admin/password', { current: $('#pCur').value, new: $('#pNew').value })
      .then(function () {
        Z.toast('Password changed.');
        $('#pCur').value = ''; $('#pNew').value = '';
        $('#pwBanner').classList.add('hidden');
      })
      .catch(function (e) { err.textContent = e.message; err.classList.remove('hidden'); });
  });

  start();
})();
