/* ========================================================================
 * BizTools4Openclaw Admin Panel — client-side logic
 *  - Menu/routing helpers
 *  - Permission-based UI visibility
 *  - T19: Spider task creation, detail monitoring
 *  - T20: Compliance review workflow
 *  - T21: Funnel dashboard + 6 stage lists + opportunity timeline
 * ====================================================================== */

(function () {
  "use strict";

  /* ---------------------------------------------------------------------- *
   * 1) Bootstrap: read init JSON (injected by server)
   * ---------------------------------------------------------------------- */
  var initEl = document.getElementById("admin-init-json");
  var init = { permissions: [], activeKey: "", menuGroups: [], username: "guest", role: "" };
  try { if (initEl) init = JSON.parse(initEl.textContent); } catch (e) { /* ignore */ }

  var admin = {
    init: init,
    permissionSet: {},
    api: function (path, method, body) {
      var opts = { method: method || "GET", headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
      if (body && method && method !== "GET") opts.body = JSON.stringify(body);
      return fetch(path, opts).then(function (r) { return r.json(); });
    }
  };

  // Build permission set
  if (init.permissions && init.permissions.length) {
    for (var i = 0; i < init.permissions.length; i++) admin.permissionSet[init.permissions[i]] = true;
  }

  // Apply permission-based button/element hiding (elements with data-requires-permission)
  function applyPermissionVisibility() {
    var els = document.querySelectorAll("[data-requires-permission]");
    for (var i = 0; i < els.length; i++) {
      var perm = els[i].getAttribute("data-requires-permission");
      if (!admin.permissionSet[perm]) els[i].style.display = "none";
    }
  }

  /* ---------------------------------------------------------------------- *
   * 2) DOM helpers
   * ---------------------------------------------------------------------- */
  function byId(id) { return document.getElementById(id); }
  function setText(id, val) { var el = byId(id); if (el) el.textContent = (val == null ? "-" : String(val)); }
  function setHTML(id, html) { var el = byId(id); if (el) el.innerHTML = html; }
  function safe(v, def) { return (v === undefined || v === null) ? (def == null ? "-" : def) : v; }
  function escapeHTML(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------------------------------------------------------------------- *
   * 3) T21 / Data Center — Summary metrics loader
   * ---------------------------------------------------------------------- */
  admin.loadDataCenterSummary = function () {
    admin.api("/api/admin/data_center/summary").then(function (resp) {
      var d = (resp && resp.data) || {};
      setText("v-total-leads", safe(d.total_leads, 0));
      setText("v-high-intent", safe(d.high_intent_count, 0));
      setText("v-pending-followup", safe(d.pending_followup, 0));
      setText("v-won", safe(d.won_count, 0));
      setText("v-today-added", safe(d.today_added, 0));
      setText("v-trend", safe(d.trend_label, ""));
    }).catch(function (e) { console.error("[summary]", e); });
  };

  /* ---------------------------------------------------------------------- *
   * 4) T21 — Funnel chart renderer (6 stages)
   * ---------------------------------------------------------------------- */
  admin.loadFunnelChart = function () {
    admin.api("/api/admin/data_center/funnel").then(function (resp) {
      var stages = (resp && resp.data && resp.data.stages) || [];
      renderFunnelChart("funnel-chart", stages);
    }).catch(function (e) { console.error("[funnel]", e); });
  };

  function renderFunnelChart(containerId, stages) {
    var el = byId(containerId);
    if (!el) return;
    if (!stages.length) { el.innerHTML = '<div class="empty-inline">No funnel data available.</div>'; return; }

    var max = 0;
    for (var i = 0; i < stages.length; i++) if (stages[i].count > max) max = stages[i].count;

    var html = '<div class="funnel-stacked">';
    for (var j = 0; j < stages.length; j++) {
      var s = stages[j];
      var ratio = max > 0 ? (s.count / max) * 100 : 0;
      var conv = (s.conversion !== undefined && s.conversion !== null) ? (Number(s.conversion).toFixed(1) + "%") : "-";
      var widthPct = Math.max(15, ratio);
      html += (
        '<div class="funnel-stage-row">' +
        '  <div class="funnel-label">' + escapeHTML(s.stage_title) + '</div>' +
        '  <div class="funnel-bar-wrap"><div class="funnel-bar funnel-bar-' + j + '" style="width:' + widthPct + '%;">' +
        '    <span class="funnel-bar-count">' + safe(s.count, 0) + '</span>' +
        '    <span class="funnel-bar-conv">' + conv + '</span>' +
        '  </div></div>' +
        '</div>'
      );
    }
    html += '</div>';
    el.innerHTML = html;
  }

  /* ---------------------------------------------------------------------- *
   * 5) T21 — Distribution charts (channel / grade) - pure HTML bars
   * ---------------------------------------------------------------------- */
  admin.loadDistributionCharts = function () {
    admin.api("/api/admin/data_center/distribution").then(function (resp) {
      var d = (resp && resp.data) || {};
      renderBarDistribution("channel-distribution", d.channel_distribution || []);
      renderBarDistribution("grade-distribution", d.grade_distribution || []);
    }).catch(function (e) { console.error("[distribution]", e); });
  };

  function renderBarDistribution(containerId, rows) {
    var el = byId(containerId);
    if (!el) return;
    if (!rows.length) { el.innerHTML = '<div class="empty-inline">No data available.</div>'; return; }
    var total = 0;
    for (var i = 0; i < rows.length; i++) total += (rows[i].count || 0);
    var html = '<div class="dist-list">';
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      var pct = total > 0 ? ((r.count / total) * 100).toFixed(1) : "0.0";
      html += (
        '<div class="dist-row">' +
        '  <div class="dist-key">' + escapeHTML(r.key || r.label || r.name || "Unknown") + '</div>' +
        '  <div class="dist-bar-wrap"><div class="dist-bar" style="width:' + pct + '%;"></div></div>' +
        '  <div class="dist-count">' + safe(r.count, 0) + ' (' + pct + '%)</div>' +
        '</div>'
      );
    }
    html += '</div>';
    el.innerHTML = html;
  }

  /* ---------------------------------------------------------------------- *
   * 6) T21 — 7-day trend chart (simple line)
   * ---------------------------------------------------------------------- */
  admin.loadTrendChart = function (kind) {
    kind = kind || "leads";
    admin.api("/api/admin/data_center/trend?kind=" + encodeURIComponent(kind)).then(function (resp) {
      var points = (resp && resp.data && resp.data.points) || [];
      renderTrendChart("trend-chart", points, kind);
    }).catch(function (e) { console.error("[trend]", e); });
  };

  function renderTrendChart(containerId, points, kind) {
    var el = byId(containerId);
    if (!el) return;
    if (!points.length) { el.innerHTML = '<div class="empty-inline">No trend data available.</div>'; return; }

    var max = 0, min = 0;
    for (var i = 0; i < points.length; i++) {
      var v = Number(points[i].value || 0);
      if (v > max) max = v;
      if (v < min) min = v;
    }
    var range = (max - min) || 1;

    // SVG-based line chart
    var w = 700, h = 220, padX = 40, padY = 30;
    var innerW = w - padX * 2, innerH = h - padY * 2;
    var stepX = points.length > 1 ? innerW / (points.length - 1) : 0;
    var d = "";
    var dots = "";
    var labels = "";
    for (var j = 0; j < points.length; j++) {
      var p = points[j];
      var val = Number(p.value || 0);
      var x = padX + (stepX * j);
      var y = padY + innerH - ((val - min) / range) * innerH;
      d += (j === 0 ? "M" : "L") + x + "," + y + " ";
      dots += '<circle cx="' + x + '" cy="' + y + '" r="4" class="trend-dot"/>';
      dots += '<text x="' + x + '" y="' + (y - 8) + '" class="trend-val">' + val + '</text>';
      labels += '<text x="' + x + '" y="' + (h - 10) + '" class="trend-label">' + escapeHTML(p.date || p.label || String(j + 1)) + '</text>';
    }

    var html = (
      '<div class="trend-wrap">' +
      '  <svg class="trend-svg" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="xMidYMid meet">' +
      '    <line x1="' + padX + '" y1="' + padY + '" x2="' + padX + '" y2="' + (h - padY) + '" stroke="#ddd" />' +
      '    <line x1="' + padX + '" y1="' + (h - padY) + '" x2="' + (w - padX) + '" y2="' + (h - padY) + '" stroke="#ddd" />' +
      '    <path class="trend-line" d="' + d + '" fill="none" stroke="#4a90e2" stroke-width="2.5"/>' +
      '    ' + dots + ' ' + labels +
      '  </svg>' +
      '</div>'
    );
    el.innerHTML = html;
  }

  /* ---------------------------------------------------------------------- *
   * 7) T21 — Stage detail list loader (collection/cleaning/...)
   * ---------------------------------------------------------------------- */
  var stageEndpoints = {
    collection: "/api/admin/data_center/collection",
    cleaning: "/api/admin/data_center/cleaning",
    compliance: "/api/admin/data_center/compliance",
    grading: "/api/admin/data_center/grading",
    outreach: "/api/admin/data_center/outreach",
    sales: "/api/admin/data_center/sales"
  };

  admin.loadStageList = function (stageKey, bodyIdPrefix, page) {
    page = page || 1;
    var endpoint = stageEndpoints[stageKey];
    if (!endpoint) return;
    var status = byId(bodyIdPrefix + "-filter-status") ? byId(bodyIdPrefix + "-filter-status").value : "";
    var channel = byId(bodyIdPrefix + "-filter-channel") ? byId(bodyIdPrefix + "-filter-channel").value : "";
    var keyword = byId(bodyIdPrefix + "-filter-keyword") ? byId(bodyIdPrefix + "-filter-keyword").value : "";

    var url = endpoint + "?page=" + page + "&per_page=20";
    if (status) url += "&status=" + encodeURIComponent(status);
    if (channel) url += "&channel=" + encodeURIComponent(channel);
    if (keyword) url += "&keyword=" + encodeURIComponent(keyword);

    admin.api(url).then(function (resp) {
      var d = (resp && resp.data) || {};
      renderStageList(bodyIdPrefix, d, stageKey);
    }).catch(function (e) { console.error("[" + stageKey + "]", e); });
  };

  function renderStageList(prefix, data, stageKey) {
    var items = data.items || [];
    var total = data.total || 0;
    var page = data.page || 1;
    var per_page = data.per_page || 20;

    // Stage summary
    setText(prefix + "-total", data.stage_total != null ? data.stage_total : total);
    setText(prefix + "-valid", data.stage_valid != null ? data.stage_valid : total);
    setText(prefix + "-exception", data.stage_exception || 0);
    setText(prefix + "-recent", data.stage_recent || 0);

    // Column keys per stage
    var colKeys = {
      collection: ["task_id", "task_name", "channel", "status", "crawled", "failed", "created_at"],
      cleaning: ["lead_id", "title", "channel", "company", "contact", "status", "created_at"],
      compliance: ["lead_id", "title", "channel", "compliance_status", "compliance_score", "risk_level", "pii_types"],
      grading: ["lead_id", "title", "channel", "grade", "score", "budget", "urgency", "tags"],
      outreach: ["batch_id", "title", "target_lead", "channel", "target_count", "success", "failed", "status", "sent_at"],
      sales: ["lead_id", "title", "company", "assignee", "grade", "status", "followups", "last_followup", "value"]
    }[stageKey] || [];

    var tbodyEl = byId(prefix + "-body");
    if (!tbodyEl) return;

    if (!items.length) {
      var colCount = colKeys.length + 1;
      tbodyEl.innerHTML = '<tr><td colspan="' + colCount + '" class="empty">No ' + stageKey + ' data available.</td></tr>';
    } else {
      var rowsHtml = "";
      for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var lead_id = item.lead_id || item.task_id || item.batch_id || ("row_" + i);
        rowsHtml += "<tr>";
        for (var j = 0; j < colKeys.length; j++) {
          var k = colKeys[j];
          var val = item[k];
          if (typeof val === "object" && val !== null) val = JSON.stringify(val);
          rowsHtml += "<td>" + escapeHTML(safe(val, "")) + "</td>";
        }
        // Action: view opportunity timeline (if lead_id available)
        var canView = admin.permissionSet["btn.data_center.view"];
        var actionHtml = '<td>';
        if (lead_id && canView) {
          actionHtml += '<a class="btn btn-sm" href="/admin/data_center/opportunity/' + encodeURIComponent(lead_id) + '">View</a>';
        } else {
          actionHtml += '<span class="muted">-</span>';
        }
        actionHtml += '</td>';
        rowsHtml += actionHtml;
        rowsHtml += "</tr>";
      }
      tbodyEl.innerHTML = rowsHtml;
    }

    // Pager
    var totalPages = Math.max(1, Math.ceil(total / per_page));
    var pagerHtml = "";
    pagerHtml += '<span class="muted">Page ' + page + ' / ' + totalPages + ' (total ' + total + ')</span>';
    if (page > 1) pagerHtml += '<button class="btn btn-sm" onclick="admin.loadStageList(\'' + stageKey + '\',\'' + prefix + '\',' + (page - 1) + ')">Prev</button>';
    if (page < totalPages) pagerHtml += '<button class="btn btn-sm" onclick="admin.loadStageList(\'' + stageKey + '\',\'' + prefix + '\',' + (page + 1) + ')">Next</button>';
    var pagerEl = byId(prefix + "-pager");
    if (pagerEl) pagerEl.innerHTML = pagerHtml;
  }

  /* ---------------------------------------------------------------------- *
   * 8) T21 — Opportunity timeline loader
   * ---------------------------------------------------------------------- */
  admin.loadOpportunityTimeline = function (lead_id) {
    admin.api("/api/admin/data_center/opportunity/" + encodeURIComponent(lead_id)).then(function (resp) {
      var d = (resp && resp.data) || {};
      // Summary info
      var info = d.info || {};
      setText("opp-title", safe(info.title, "-"));
      setText("opp-company", safe(info.company, "-"));
      setText("opp-channel", safe(info.channel, "-"));
      setText("opp-grade", safe(info.grade, "-"));
      setText("opp-score", safe(info.score, "-"));
      setText("opp-status", safe(info.status, "-"));
      setText("opp-contact", safe(info.contact_masked || info.contact, "-"));

      // Timeline events
      var events = d.events || [];
      var tlEl = byId("opp-timeline");
      if (!tlEl) return;
      if (!events.length) {
        tlEl.innerHTML = '<div class="empty-inline">No timeline events available for this lead.</div>';
        return;
      }
      var html = '<div class="timeline-list">';
      for (var i = 0; i < events.length; i++) {
        var e = events[i];
        html += (
          '<div class="timeline-item">' +
          '  <div class="timeline-marker"></div>' +
          '  <div class="timeline-body">' +
          '    <div class="timeline-head">' +
          '      <span class="timeline-stage">' + escapeHTML(safe(e.stage || e.label, "Stage")) + '</span>' +
          '      <span class="timeline-time">' + escapeHTML(safe(e.time || e.created_at, "-")) + '</span>' +
          '    </div>' +
          '    <div class="timeline-desc">' + escapeHTML(safe(e.description || e.message || e.detail || "", "")) + '</div>' +
          '    <div class="timeline-meta">' +
                 (e.operator ? '<span class="timeline-op">By: ' + escapeHTML(safe(e.operator, "-")) + '</span>' : "") +
                 (e.status ? ' <span class="timeline-status">Status: ' + escapeHTML(safe(e.status, "-")) + '</span>' : "") +
          '    </div>' +
          '  </div>' +
          '</div>'
        );
      }
      html += '</div>';
      tlEl.innerHTML = html;
    }).catch(function (e) { console.error("[timeline]", e); });
  };

  /* ---------------------------------------------------------------------- *
   * 9) Stubs for earlier features (spider/leads/channels/sales/audit/etc.)
   *    These keep the pages.html references working without 404 in console.
   * ---------------------------------------------------------------------- */
  admin.createSpiderTask = function () {
    // Intentionally left as a stub in this minimal frontend.
    // Actual submission should POST to /api/admin/spider/task and refresh the list.
    alert("Spider task creation requires backend integration. (stub)");
    return false;
  };

  admin.loadNotificationsList = function () { /* stub */ };
  admin.markAllNotificationsRead = function () { /* stub */ };

  /* ---------------------------------------------------------------------- *
   * 10) Apply permissions + export
   * ---------------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", function () {
    applyPermissionVisibility();
  });

  // Also run immediately (in case DOMContentLoaded already fired when script was late)
  try { applyPermissionVisibility(); } catch (e) { /* ignore */ }

  window.admin = admin;
})();
