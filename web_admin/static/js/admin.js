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
    _submitting: false,
    api: function (path, method, body) {
      var opts = { method: method || "GET", headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
      if (body && method && method !== "GET") opts.body = JSON.stringify(body);
      return fetch(path, opts).then(function (r) { return r.json(); });
    },
    // T24: 统一安全 API 调用 — 带错误处理、重复提交保护、超时
    safeApi: function (path, method, body, opts) {
      opts = opts || {};
      var timeoutMs = opts.timeout || 15000;
      // 防重复提交
      if (opts.preventDoubleSubmit) {
        if (admin._submitting) {
          return Promise.reject(new Error("操作进行中，请稍候..."));
        }
        admin._submitting = true;
      }
      var fetchOpts = { method: method || "GET", headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
      if (body && method && method !== "GET") fetchOpts.body = JSON.stringify(body);

      var timeoutPromise = new Promise(function (_, reject) {
        setTimeout(function () { reject(new Error("请求超时，请检查网络")); }, timeoutMs);
      });

      return Promise.race([fetch(path, fetchOpts).then(function (r) { return r.json(); }), timeoutPromise])
        .then(function (data) {
          if (opts.preventDoubleSubmit) admin._submitting = false;
          // 通用非 0 code 处理
          if (data && typeof data.code !== "undefined" && data.code !== 0) {
            var msg = data.msg || "操作失败";
            if (opts.showError !== false) admin.showError(msg);
            throw new Error(msg);
          }
          return data;
        })
        .catch(function (err) {
          if (opts.preventDoubleSubmit) admin._submitting = false;
          var msg = (err && err.message) ? err.message : "网络异常，请稍后重试";
          if (opts.showError !== false) admin.showError(msg);
          throw err;
        });
    },
    // T24: 统一错误提示
    showError: function (msg) {
      var existing = document.getElementById("admin-error-toast");
      if (existing) existing.remove();
      var toast = document.createElement("div");
      toast.id = "admin-error-toast";
      toast.className = "error-toast";
      toast.textContent = "⚠ " + msg;
      document.body.appendChild(toast);
      setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 4000);
    },
    // T24: 统一成功提示
    showSuccess: function (msg) {
      var existing = document.getElementById("admin-success-toast");
      if (existing) existing.remove();
      var toast = document.createElement("div");
      toast.id = "admin-success-toast";
      toast.className = "success-toast";
      toast.textContent = "✓ " + msg;
      document.body.appendChild(toast);
      setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 2500);
    },
    // T24: 空列表渲染
    renderEmptyState: function (container, message) {
      if (!container) return;
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">○</div><div class="empty-text">' + (message || "暂无数据") + '</div></div>';
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
    if (!stages.length) { el.innerHTML = '<div class="empty-inline">暂无漏斗数据</div>'; return; }

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
    if (!rows.length) { el.innerHTML = '<div class="empty-inline">暂无数据</div>'; return; }
    var total = 0;
    for (var i = 0; i < rows.length; i++) total += (rows[i].count || 0);
    var html = '<div class="dist-list">';
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      var pct = total > 0 ? ((r.count / total) * 100).toFixed(1) : "0.0";
      html += (
        '<div class="dist-row">' +
        '  <div class="dist-key">' + escapeHTML(r.key || r.label || r.name || "未命名") + '</div>' +
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
    if (!points.length) { el.innerHTML = '<div class="empty-inline">暂无趋势数据</div>'; return; }

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
      tbodyEl.innerHTML = '<tr><td colspan="' + colCount + '" class="empty">暂无数据</td></tr>';
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
          actionHtml += '<a class="btn btn-sm" href="/admin/data_center/opportunity/' + encodeURIComponent(lead_id) + '">查看</a>';
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
    pagerHtml += '<span class="muted">第 ' + page + ' / ' + totalPages + ' (共 ' + total + ')</span>';
    if (page > 1) pagerHtml += '<button class="btn btn-sm" onclick="admin.loadStageList(\'' + stageKey + '\',\'' + prefix + '\',' + (page - 1) + ')">上一页</button>';
    if (page < totalPages) pagerHtml += '<button class="btn btn-sm" onclick="admin.loadStageList(\'' + stageKey + '\',\'' + prefix + '\',' + (page + 1) + ')">下一页</button>';
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
        tlEl.innerHTML = '<div class="empty-inline">此商机暂无时间线事件</div>';
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
          '      <span class="timeline-stage">' + escapeHTML(safe(e.stage || e.label, "阶段")) + '</span>' +
          '      <span class="timeline-time">' + escapeHTML(safe(e.time || e.created_at, "-")) + '</span>' +
          '    </div>' +
          '    <div class="timeline-desc">' + escapeHTML(safe(e.description || e.message || e.detail || "", "")) + '</div>' +
          '    <div class="timeline-meta">' +
                 (e.operator ? '<span class="timeline-op">操作人: ' + escapeHTML(safe(e.operator, "-")) + '</span>' : "") +
                 (e.status ? ' <span class="timeline-status">状态: ' + escapeHTML(safe(e.status, "-")) + '</span>' : "") +
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
   * T22.0) 操作定义 & 渲染工具
   * ---------------------------------------------------------------------- */
  var STAGE_OPS = {
    exception: [
      { key: "reinsert", title: "单条重新入库", method: "POST", url: "/api/admin/data_center/exception/EDIT-ITEM-ID/reinsert",
        dynamic_item_id: true, fields: [] },
      { key: "discard", title: "[高危]废弃单条", risk: "high", method: "POST", url: "/api/admin/data_center/exception/EDIT-ITEM-ID/discard",
        dynamic_item_id: true, fields: [] },
      { key: "false_positive", title: "标记为误判", method: "POST", url: "/api/admin/data_center/exception/EDIT-ITEM-ID/mark-false-positive",
        dynamic_item_id: true, fields: [] }
    ],
    collection: [
      { key: "task_speed", title: "调整采集速度", method: "POST", url: "/api/admin/data_center/manual/collection/task-speed",
        fields: [{ name: "job_id", label: "任务ID", placeholder: "task-xxxx", required: true },
                  { name: "speed_level", label: "速度等级(1-5)", type: "number", value: "3" }] },
      { key: "task_keywords", title: "追加关键词", method: "POST", url: "/api/admin/data_center/manual/collection/task-keywords",
        fields: [{ name: "job_id", label: "任务ID", placeholder: "task-xxxx", required: true },
                  { name: "keywords", label: "关键词(逗号分隔)", placeholder: "CRM,SaaS,企业服务", required: true }] },
      { key: "item_status", title: "标记条目有效/无效", method: "POST", url: "/api/admin/data_center/manual/collection/item-status",
        fields: [{ name: "item_id", label: "条目ID", required: true },
                  { name: "status", label: "状态", type: "select", options: ["valid", "invalid"], value: "valid" }] },
      { key: "push_cleaning", title: "推送进入清洗", method: "POST", url: "/api/admin/data_center/manual/collection/push-to-cleaning",
        fields: [{ name: "job_id", label: "任务ID", placeholder: "task-xxxx", required: true },
                  { name: "item_ids", label: "条目ID(逗号分隔)", placeholder: "留空=全部" }] },
      { key: "batch_run", title: "批量启动任务", method: "POST", url: "/api/admin/data_center/manual/collection/batch-run",
        fields: [{ name: "job_ids", label: "任务ID列表(逗号分隔)", placeholder: "task-a,task-b", required: true }] },
      { key: "batch_pause", title: "批量暂停任务", method: "POST", url: "/api/admin/data_center/manual/collection/batch-pause",
        fields: [{ name: "job_ids", label: "任务ID列表(逗号分隔)", placeholder: "task-a,task-b", required: true }] }
    ],
    cleaning: [
      { key: "reclean", title: "重新清洗", method: "POST", url: "/api/admin/data_center/manual/cleaning/reclean",
        fields: [{ name: "lead_ids", label: "商机ID(逗号分隔)", placeholder: "lead-1,lead-2", required: true }] },
      { key: "edit_entity", title: "人工修正实体", method: "PATCH", url: "/api/admin/data_center/manual/cleaning/EDIT-ITEM-ID",
        dynamic_item_id: true, fields: [
          { name: "company", label: "企业名称" },
          { name: "contact", label: "联系方式" },
          { name: "tags", label: "需求标签(逗号分隔)" }
        ] },
      { key: "mark_normal", title: "异常标记正常", method: "POST", url: "/api/admin/data_center/manual/cleaning/EDIT-ITEM-ID/mark-normal",
        dynamic_item_id: true, fields: [] }
    ],
    compliance: [
      { key: "force_pass", title: "[高危]强制放行", risk: "high", method: "POST", url: "/api/admin/data_center/manual/compliance/EDIT-ITEM-ID/force-pass",
        dynamic_item_id: true, fields: [] },
      { key: "mark_false_positive", title: "标记误判", method: "POST", url: "/api/admin/data_center/manual/compliance/EDIT-ITEM-ID/mark-false-positive",
        dynamic_item_id: true, fields: [] },
      { key: "reject_permanent", title: "[高危]永久驳回", risk: "high", method: "POST", url: "/api/admin/data_center/manual/compliance/EDIT-ITEM-ID/reject-permanent",
        dynamic_item_id: true, fields: [] },
      { key: "update_grade", title: "调整合规等级", method: "PATCH", url: "/api/admin/data_center/manual/compliance/EDIT-ITEM-ID/grade",
        dynamic_item_id: true, fields: [
          { name: "compliance_grade", label: "等级", type: "select", options: ["A", "B", "C", "D"], value: "B" }
        ] },
      { key: "mask_rule", title: "调整脱敏规则", method: "PATCH", url: "/api/admin/data_center/manual/compliance/EDIT-ITEM-ID/mask-rule",
        dynamic_item_id: true, fields: [
          { name: "mask_level", label: "脱敏级别", type: "select", options: ["default", "strict", "plaintext"], value: "default" }
        ] }
    ],
    grading: [
      { key: "grade", title: "调整商机等级", method: "PATCH", url: "/api/admin/data_center/manual/grading/EDIT-ITEM-ID/grade",
        dynamic_item_id: true, fields: [
          { name: "grade", label: "等级", type: "select", options: ["A", "B", "C", "D"], value: "B" }
        ] },
      { key: "score", title: "修改打分", method: "PATCH", url: "/api/admin/data_center/manual/grading/EDIT-ITEM-ID/score",
        dynamic_item_id: true, fields: [
          { name: "score", label: "分数(0.0-5.0)", type: "number", value: "3.0" }
        ] },
      { key: "tags", title: "补充行业/地域标签", method: "PATCH", url: "/api/admin/data_center/manual/grading/EDIT-ITEM-ID/tags",
        dynamic_item_id: true, fields: [
          { name: "tags", label: "标签(逗号分隔)", placeholder: "SaaS,北京,金融" }
        ] },
      { key: "blacklist_add", title: "[高危]加入黑名单", risk: "high", method: "POST", url: "/api/admin/data_center/manual/grading/EDIT-ITEM-ID/blacklist/add",
        dynamic_item_id: true, fields: [] },
      { key: "blacklist_remove", title: "移出黑名单", method: "POST", url: "/api/admin/data_center/manual/grading/EDIT-ITEM-ID/blacklist/remove",
        dynamic_item_id: true, fields: [] }
    ],
    outreach: [
      { key: "send", title: "手动发起触达", method: "POST", url: "/api/admin/data_center/manual/outreach/EDIT-ITEM-ID/send",
        dynamic_item_id: true, fields: [
          { name: "channel", label: "渠道", type: "select", options: ["email", "wechat", "sms", "feishu"], value: "email" },
          { name: "content", label: "触达内容", type: "textarea", placeholder: "您好..." }
        ] },
      { key: "resend", title: "失败重发/换渠道", method: "POST", url: "/api/admin/data_center/manual/outreach/EDIT-ITEM-ID/resend",
        dynamic_item_id: true, fields: [
          { name: "new_channel", label: "新渠道", type: "select", options: ["email", "wechat", "sms", "feishu"], value: "email" }
        ] },
      { key: "cancel", title: "取消待发送", method: "DELETE", url: "/api/admin/data_center/manual/outreach/EDIT-ITEM-ID/cancel",
        dynamic_item_id: true, fields: [] }
    ],
    sales: [
      { key: "assign", title: "分配销售", method: "POST", url: "/api/admin/data_center/manual/sales/EDIT-ITEM-ID/assign",
        dynamic_item_id: true, fields: [
          { name: "assignee", label: "销售人员", placeholder: "zhang.san", required: true }
        ] },
      { key: "followup", title: "录入跟进记录", method: "POST", url: "/api/admin/data_center/manual/sales/EDIT-ITEM-ID/followup",
        dynamic_item_id: true, fields: [
          { name: "note", label: "跟进内容", type: "textarea", placeholder: "客户已回复，对套餐A兴趣较高...", required: true },
          { name: "next_followup", label: "下次跟进时间", placeholder: "2026-07-10 10:00" }
        ] },
      { key: "add_tags", title: "添加客户标签", method: "PATCH", url: "/api/admin/data_center/manual/sales/EDIT-ITEM-ID/tags",
        dynamic_item_id: true, fields: [
          { name: "tags", label: "标签(逗号分隔)", placeholder: "高意向,金融,已试用" }
        ] },
      { key: "status", title: "[高危]标记商机状态", risk: "high", method: "PATCH", url: "/api/admin/data_center/manual/sales/EDIT-ITEM-ID/status",
        dynamic_item_id: true, fields: [
          { name: "status", label: "状态", type: "select", options: ["communicating", "high_intent", "won", "lost", "closed_invalid"], value: "communicating" }
        ] }
    ]
  };

  // 渲染阶段工具栏按钮（根据 data-stage-actions 属性）
  function renderStageActionBar() {
    var nodes = document.querySelectorAll('[data-stage-actions]');
    if (!nodes.length) return;
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var stage = node.getAttribute('data-stage-actions');
      if (!STAGE_OPS[stage]) continue;
      var html = '';
      var list = STAGE_OPS[stage];
      for (var j = 0; j < list.length; j++) {
        var op = list[j];
        var cls = op.risk === 'high' ? 'btn btn-sm btn-danger' : 'btn btn-sm';
        html += '<button class="' + cls + '" data-op-key="' + op.key + '" data-stage="' + stage + '" data-dynamic="' + (op.dynamic_item_id ? '1' : '0') + '" onclick="admin.openManualDialog(\'' + stage + '\',\'' + op.key + '\',null)">' + op.title + '</button>';
      }
      node.innerHTML = html;
    }
  }

  admin.openManualDialog = function (stage, opKey, itemId) {
    var list = STAGE_OPS[stage];
    if (!list) return;
    var op = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === opKey) { op = list[i]; break; }
    }
    if (!op) return;

    var titleEl = document.getElementById('manual-dialog-title');
    titleEl.textContent = op.title + (op.risk === 'high' ? ' [高危操作]' : '');
    titleEl.className = op.risk === 'high' ? 'title-high-risk' : '';

    // 构建表单
    var bodyHtml = '';
    bodyHtml += '<div class="manual-dialog-stage">所属阶段：' + stage + '</div>';
    bodyHtml += '<div class="manual-dialog-desc">操作将被完整记录到审计日志中，请确认后执行。</div>';
    bodyHtml += '<div class="manual-dialog-form">';

    if (op.dynamic_item_id) {
      bodyHtml += '<label>目标ID<span class="required">*</span>' +
        '<input type="text" name="item_id" placeholder="lead-xxxxx / raw-xxxxx" value="' + (itemId || '') + '" required></label>';
    }

    if (op.fields && op.fields.length) {
      for (var f = 0; f < op.fields.length; f++) {
        var field = op.fields[f];
        var type = field.type || 'text';
        var label = field.label || field.name;
        bodyHtml += '<label>' + label + (field.required ? '<span class="required">*</span>' : '');
        if (type === 'select') {
          bodyHtml += '<select name="' + field.name + '">';
          var opts = field.options || [];
          for (var o = 0; o < opts.length; o++) {
            var selected = field.value === opts[o] ? 'selected' : '';
            bodyHtml += '<option value="' + opts[o] + '" ' + selected + '>' + opts[o] + '</option>';
          }
          bodyHtml += '</select>';
        } else if (type === 'textarea') {
          bodyHtml += '<textarea name="' + field.name + '" placeholder="' + (field.placeholder || '') + '" rows="4"></textarea>';
        } else {
          bodyHtml += '<input type="' + type + '" name="' + field.name + '" placeholder="' + (field.placeholder || '') + '" value="' + (field.value || '') + '">';
        }
        bodyHtml += '</label>';
      }
    }

    bodyHtml += '<label>操作原因<span class="required">*</span>' +
      '<textarea name="reason" rows="2" placeholder="请简要说明操作原因，必填" required></textarea></label>';
    bodyHtml += '</div>';

    if (op.risk === 'high') {
      bodyHtml += '<div class="manual-dialog-high-risk-notice">⚠ 高危操作：将永久改变数据状态，仅高级权限可执行，请谨慎操作。</div>';
    }

    var bodyEl = document.getElementById('manual-dialog-body');
    bodyEl.innerHTML = bodyHtml;

    // 存储当前操作上下文
    admin._currentOp = { stage: stage, opKey: opKey, op: op };

    document.getElementById('manual-dialog-submit').className = op.risk === 'high' ? 'btn btn-primary btn-danger-countdown' : 'btn btn-primary';
    document.getElementById('manual-dialog-mask').style.display = 'flex';
  };

  admin.closeManualDialog = function () {
    document.getElementById('manual-dialog-mask').style.display = 'none';
    admin._currentOp = null;
  };

  admin.submitManualDialog = function () {
    var ctx = admin._currentOp;
    if (!ctx) return;
    var op = ctx.op;

    // 收集表单字段
    var inputs = document.querySelectorAll('#manual-dialog-body input, #manual-dialog-body select, #manual-dialog-body textarea');
    var params = {};
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      var name = el.name;
      if (!name) continue;
      if (el.hasAttribute('required') && !el.value.trim()) {
        admin.showToast('请填写：' + el.name, 'error');
        el.focus();
        return;
      }
      params[name] = el.value;
    }

    // 动态替换 item_id
    var url = op.url;
    if (op.dynamic_item_id && params.item_id) {
      url = url.replace('EDIT-ITEM-ID', params.item_id);
      delete params.item_id;
    }

    // 二次确认
    var msg = '确认执行「' + op.title + '」？' + (op.risk === 'high' ? '（高危操作）' : '');
    if (!confirm(msg)) return;

    // 构造 query string
    var qs = [];
    for (var k in params) {
      if (params.hasOwnProperty(k)) {
        qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
      }
    }

    // 实际请求：根据 method 选 GET / POST
    var fetchUrl = url;
    var fetchOpts = {
      method: op.method || 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    };
    if (op.method === 'GET') {
      fetchUrl = url + (url.indexOf('?') >= 0 ? '&' : '?') + qs.join('&');
    } else if (op.method === 'DELETE') {
      // DELETE 可以带少量参数
      fetchUrl = url + (url.indexOf('?') >= 0 ? '&' : '?') + qs.join('&');
    } else {
      fetchOpts.body = qs.join('&');
    }

    var submitBtn = document.getElementById('manual-dialog-submit');
    submitBtn.disabled = true;
    submitBtn.textContent = '执行中...';

    fetch(fetchUrl, fetchOpts).then(function (resp) {
      return resp.json().catch(function () { return { code: -1, msg: resp.statusText }; });
    }).then(function (data) {
      if (data && data.code === 0) {
        admin.showToast('操作成功：' + (data.data && data.data.audit_id ? '日志ID=' + data.data.audit_id : '完成'), 'success');
        admin.closeManualDialog();
        // 刷新当前页
        if (typeof admin.loadStageList === 'function' && ctx.stage) {
          var bodyId = 'dc-' + ctx.stage;
          admin.loadStageList(ctx.stage, bodyId, 1);
        }
      } else {
        var err = (data && data.msg) || '操作失败';
        admin.showToast('失败：' + err, 'error');
      }
    }).catch(function (e) {
      admin.showToast('网络异常：' + e, 'error');
    }).finally(function () {
      submitBtn.disabled = false;
      submitBtn.textContent = '确认执行';
    });
  };

  admin.showToast = function (msg, type) {
    var el = document.getElementById('manual-toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'manual-toast manual-toast-' + (type || 'info');
    el.style.display = 'block';
    setTimeout(function () { el.style.display = 'none'; }, 2800);
  };

  // T22: 扩展表格行 — 为每行注入"操作"按钮（仅在 data_center 页面生效）
  function injectRowActionButtons() {
    var stageFromUrl = function () {
      var u = (location.pathname || '').toLowerCase();
      if (u.indexOf('collection') >= 0) return 'collection';
      if (u.indexOf('cleaning') >= 0) return 'cleaning';
      if (u.indexOf('compliance') >= 0) return 'compliance';
      if (u.indexOf('grading') >= 0) return 'grading';
      if (u.indexOf('outreach') >= 0) return 'outreach';
      if (u.indexOf('sales') >= 0) return 'sales';
      return null;
    }();
    if (!stageFromUrl || !STAGE_OPS[stageFromUrl]) return;

    // 为每行的 Actions 列注入操作
    function renderRowActions() {
      var rows = document.querySelectorAll('.data-table tbody tr');
      for (var r = 0; r < rows.length; r++) {
        var row = rows[r];
        if (row.getAttribute('data-t22-injected')) continue;
        if (row.querySelector('.empty')) continue;
        // 取第一个单元格作为 item_id
        var firstCell = row.querySelector('td:first-child');
        var itemId = firstCell ? firstCell.textContent.trim() : ('item-' + r);

        // 生成该行操作按钮
        var ops = STAGE_OPS[stageFromUrl];
        // 仅选择带 dynamic_item_id 的操作作为行内操作
        var rowButtons = [];
        for (var k = 0; k < ops.length; k++) {
          if (ops[k].dynamic_item_id) rowButtons.push(ops[k]);
        }
        // 只展示前 2-3 个作为行内快捷操作
        var showCount = Math.min(rowButtons.length, 3);
        var html = '';
        for (var b = 0; b < showCount; b++) {
          var bop = rowButtons[b];
          var bcls = bop.risk === 'high' ? 'btn btn-sm btn-danger' : 'btn btn-sm';
          html += '<button class="' + bcls + '" onclick="admin.openManualDialog(\'' + stageFromUrl + '\',\'' + bop.key + '\',\'' + itemId + '\')">操作</button>';
        }

        // 注入到 Actions 列（最后一列）
        var cells = row.querySelectorAll('td');
        if (cells.length) {
          cells[cells.length - 1].innerHTML = html;
        }
        row.setAttribute('data-t22-injected', '1');
      }
    }
    // 初始渲染 + 定时补偿（列表加载完成后）
    renderRowActions();
    setTimeout(renderRowActions, 500);
    setTimeout(renderRowActions, 1500);
  }

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
  /* ========================================================================= *
   * T23: 异常数据池 + 分渠道漏斗 + 批量操作 + 数据导出
   * ========================================================================= */

  /* ---------- 1) Exception Pool ---------- */
  admin.loadExceptionStats = function () {
    fetch("/api/admin/data_center/exception/stats")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.data) {
          var d = data.data;
          var t = document.getElementById("exception-total");
          var p = document.getElementById("exception-pending");
          var res = document.getElementById("exception-resolved");
          var tr = document.getElementById("exception-trend");
          if (t) t.textContent = d.total;
          if (p) p.textContent = d.pending;
          if (res) res.textContent = d.resolved;
          if (tr) {
            var trLabel = "待处理";
            if (d.trend && d.trend.length) {
              trLabel = d.trend.map(function (x) { return x.date + ":" + x.pending; }).join(" | ");
            }
            tr.textContent = trLabel.substring(0, 30);
          }
          // 类型分布
          var dist = document.getElementById("exception-type-dist");
          if (dist && d.by_type) {
            var html = "";
            var maxVal = 1;
            var keys = Object.keys(d.by_type);
            keys.forEach(function (k) { if (d.by_type[k].count > maxVal) maxVal = d.by_type[k].count; });
            keys.forEach(function (k) {
              var item = d.by_type[k];
              var pct = Math.round(item.count / maxVal * 100);
              html += '<div class="type-bar-row" style="margin-bottom:8px;">' +
                       '  <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">' +
                       '    <span>' + item.name + '</span>' +
                       '    <span style="color:#6b7a90;">' + item.count + ' (' + item.ratio + '%)</span>' +
                       '  </div>' +
                       '  <div class="progress-bar-container" style="height:10px;">' +
                       '    <div class="progress-bar-fill" style="width:' + pct + '%;background:#4a90e2;"></div>' +
                       '  </div>' +
                       '</div>';
            });
            dist.innerHTML = html;
          }
          // 填充筛选下拉
          var ftype = document.getElementById("exception-filter-type");
          if (ftype && d.by_type) {
            keys.forEach(function (k) {
              var opt = document.createElement("option");
              opt.value = k;
              opt.textContent = d.by_type[k].name;
              ftype.appendChild(opt);
            });
          }
          var fchan = document.getElementById("exception-filter-channel");
          if (fchan && d.by_channel) {
            Object.keys(d.by_channel).forEach(function (ch) {
              var opt = document.createElement("option");
              opt.value = ch;
              opt.textContent = d.by_channel[ch].name;
              fchan.appendChild(opt);
            });
          }
        }
      }).catch(function (e) { console.error("exception stats error", e); });
  };

  admin.loadExceptionList = function (page) {
    if (!page) page = 1;
    var ft = document.getElementById("exception-filter-type") ? document.getElementById("exception-filter-type").value : "";
    var fc = document.getElementById("exception-filter-channel") ? document.getElementById("exception-filter-channel").value : "";
    var fs = document.getElementById("exception-filter-status") ? document.getElementById("exception-filter-status").value : "";
    var url = "/api/admin/data_center/exception/list?page=" + page + "&page_size=20" +
              (ft ? "&exception_type=" + encodeURIComponent(ft) : "") +
              (fc ? "&channel=" + encodeURIComponent(fc) : "") +
              (fs ? "&status=" + encodeURIComponent(fs) : "");
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var tbody = document.getElementById("exception-tbody");
        if (!tbody) return;
        if (!data.data || !data.data.items || !data.data.items.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无数据</td></tr>';
          return;
        }
        var rowsHtml = "";
        data.data.items.forEach(function (item) {
          // 英文状态码比较 + 中文显示
          var __zhExcStatus = {"pending":"待处理","resolved":"已处理","discarded":"已废弃","false_positive":"误判"};
          var statusColor = "pending" === item.status ? "#f5a623" :
                             "resolved" === item.status ? "#28a745" :
                             "discarded" === item.status ? "#dc3545" :
                             "false_positive" === item.status ? "#6b7a90" : "#2c3e50";
          rowsHtml += '<tr data-item-id="' + item.exception_id + '">' +
            '<td>' + item.exception_id + '</td>' +
            '<td><span class="status-tag" style="background:#f0f3f7;color:#2c3e50;padding:2px 8px;border-radius:3px;font-size:11px;">' + (item.exception_type || "") + '</span></td>' +
            '<td>' + (item.source_channel || "") + '</td>' +
            '<td>' + (item.title || "") + '</td>' +
            '<td style="color:' + statusColor + ';font-weight:500;">' + (__zhExcStatus[item.status] || item.status) + '</td>' +
            '<td>' + (item.created_at || "") + '</td>' +
            '<td data-stage="exception" class="row-actions">' +
              '<button class="btn btn-sm" onclick="admin.openManualDialog(\'exception\',\'reinsert\',\'' + item.exception_id + '\')">重新入库</button>' +
              '<button class="btn btn-sm btn-danger" onclick="admin.openManualDialog(\'exception\',\'discard\',\'' + item.exception_id + '\')">废弃</button>' +
              '<button class="btn btn-sm" onclick="admin.openManualDialog(\'exception\',\'false_positive\',\'' + item.exception_id + '\')">标记误判</button>' +
            '</td></tr>';
        });
        tbody.innerHTML = rowsHtml;
        // 分页
        var pag = document.getElementById("exception-pagination");
        if (pag && data.data.total > 20) {
          var pages = Math.ceil(data.data.total / 20);
          var phtml = '<div style="margin-top:12px;display:flex;gap:4px;justify-content:center;align-items:center;">';
          for (var p = 1; p <= pages; p++) {
            phtml += '<button class="btn btn-sm" onclick="admin.loadExceptionList(' + p + ');return false;">' + p + '</button>';
          }
          phtml += '</div>';
          pag.innerHTML = phtml;
        }
      });
  };

  /* ---------- 2) Channel Funnel ---------- */
  admin.loadChannelFunnel = function () {
    var period = document.getElementById("channel-period") ? document.getElementById("channel-period").value : "week";
    var days = document.getElementById("channel-days") ? document.getElementById("channel-days").value : "30";
    var url = "/api/admin/data_center/channel-funnel?period=" + period + "&days=" + days;
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.data) return;
        var d = data.data;
        var tc = document.getElementById("total-crawl");
        var tw = document.getElementById("total-won");
        var tv = document.getElementById("total-conv");
        if (tc) tc.textContent = d.total ? d.total.crawl || 0 : 0;
        if (tw) tw.textContent = d.total ? d.total.won || 0 : 0;
        var overall = 0;
        if (d.total && d.total.crawl > 0 && d.total.won) overall = Math.round(d.total.won / d.total.crawl * 1000) / 10;
        if (tv) tv.textContent = overall + "%";

        var grid = document.getElementById("channel-funnel-grid");
        if (grid && d.channels && d.channels.length) {
          var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;">';
          d.channels.forEach(function (ch) {
            html += '<div style="border:1px solid #e1e8ef;border-radius:8px;padding:14px;background:#fafbfc;">';
            html += '<div style="font-weight:600;font-size:14px;margin-bottom:10px;color:#2c3e50;">' + ch.channel_name + '</div>';
            // mini funnel bars
            if (ch.stages && ch.stages.length) {
              var maxCount = 0;
              ch.stages.forEach(function (s) { if (s.count > maxCount) maxCount = s.count; });
              ch.stages.forEach(function (s) {
                var width = maxCount > 0 ? Math.max(Math.round(s.count / maxCount * 100), 2) : 0;
                html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;font-size:11px;color:#5a6a7e;">' +
                         '  <span>' + s.name + '</span>' +
                         '  <span style="flex:1;max-width:140px;height:8px;background:#e8eef5;border-radius:3px;overflow:hidden;margin:0 8px;">' +
                         '    <span style="display:block;height:100%;background:#4a90e2;width:' + width + '%;"></span>' +
                         '  </span>' +
                         '  <span style="width:70px;text-align:right;">' + s.count + ' (' + s.ratio + '%)</span>' +
                         '</div>';
              });
            }
            // 核心指标
            if (ch.metrics) {
              html += '<div style="margin-top:8px;padding-top:8px;border-top:1px dashed #d9e1ea;font-size:11px;color:#6b7a90;">';
              html += '平均周期: ' + (ch.metrics.avg_won_cycle_days || '-') + ' 天 | ';
              html += '成单成本: ' + (ch.metrics.cost_per_won_lead || '-');
              html += '</div>';
            }
            html += '</div>';
          });
          html += '</div>';
          grid.innerHTML = html;
        }
        // 排行榜
        var rk = document.getElementById("channel-rankings");
        if (rk && d.rankings) {
          var rhtml = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;">';
          Object.keys(d.rankings).forEach(function (rkKey) {
            var items = d.rankings[rkKey];
            if (!items || !items.length) return;
            rhtml += '<div style="border:1px solid #e1e8ef;border-radius:8px;padding:12px;">';
            var titleMap = { by_conversion: "按转化率", by_won: "按成单数", by_cost: "按成本(升序)" };
            rhtml += '<div style="font-weight:600;font-size:13px;margin-bottom:8px;color:#2c3e50;">' + (titleMap[rkKey] || rkKey) + '</div>';
            items.forEach(function (item, idx) {
              var color = idx === 0 ? "#d4a017" : idx === 1 ? "#b0b4b8" : idx === 2 ? "#b07a3f" : "#6b7a90";
              rhtml += '<div style="display:flex;justify-content:space-between;font-size:12px;padding:4px 0;color:' + color + ';">' +
                        '  <span>' + (idx + 1) + '. ' + item.name + '</span>' +
                        '  <span style="font-weight:500;">' + item.value + ' ' + (item.unit || "") + '</span>' +
                        '</div>';
            });
            rhtml += '</div>';
          });
          rhtml += '</div>';
          rk.innerHTML = rhtml;
        }
        // 趋势
        var trendEl = document.getElementById("channel-trend");
        if (trendEl && d.trend) {
          var trhtml = '<table class="data-table"><thead><tr><th>周期</th>';
          // columns from first row
          if (d.trend.length) Object.keys(d.trend[0]).forEach(function (k) { if (k !== "period") trhtml += "<th>" + k + "</th>"; });
          trhtml += "</tr></thead><tbody>";
          d.trend.forEach(function (row) {
            trhtml += "<tr><td>" + row.period + "</td>";
            Object.keys(row).forEach(function (k) { if (k !== "period") trhtml += "<td>" + row[k] + "</td>"; });
            trhtml += "</tr>";
          });
          trhtml += "</tbody></table>";
          trendEl.innerHTML = trhtml;
        }
      }).catch(function (e) { console.error("channel funnel error", e); });
  };

  /* ---------- 3) Batch Operation Center ---------- */
  admin.loadBatchOpTypes = function () {
    fetch("/api/admin/data_center/batch/op-types")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var sel = document.getElementById("batch-op-type");
        if (!sel || !data.data) return;
        var items = Array.isArray(data.data) ? data.data : [];
        // fallback: 内置常见类型
        if (!items.length) {
          items = [
            { key: "exception_batch_reinsert", name: "异常数据-批量重新入库" },
            { key: "exception_batch_discard", name: "异常数据-批量废弃" },
            { key: "grading_batch_change_grade", name: "商机-批量调级" },
            { key: "outreach_batch_send", name: "触达-批量发送" },
            { key: "sales_batch_assign", name: "销售-批量分配" }
          ];
        }
        sel.innerHTML = "";
        items.forEach(function (op) {
          var o = document.createElement("option");
          o.value = op.key;
          o.textContent = op.name;
          sel.appendChild(o);
        });
      }).catch(function () {
        var sel = document.getElementById("batch-op-type");
        if (sel) sel.innerHTML = '<option value="exception_batch_reinsert">异常数据-批量重新入库</option><option value="grading_batch_change_grade">商机-批量调级</option><option value="collection_batch_run">采集-批量启动</option>';
      });
  };

  admin.fillBatchDemo = function () {
    var ta = document.getElementById("batch-item-ids");
    if (ta) {
      var demo = [];
      for (var i = 1; i <= 30; i++) demo.push("EX-DEMO-" + i);
      ta.value = demo.join(",");
    }
  };

  admin.submitBatch = function () {
    var opType = document.getElementById("batch-op-type") ? document.getElementById("batch-op-type").value : "";
    var ids = document.getElementById("batch-item-ids") ? document.getElementById("batch-item-ids").value : "";
    var reason = document.getElementById("batch-reason") ? document.getElementById("batch-reason").value : "批量操作";
    if (!opType || !ids.trim()) { admin.showToast("请填写操作类型 + 条目ID", "error"); return; }
    var url = "/api/admin/data_center/batch/submit?op_type=" + encodeURIComponent(opType) +
              "&item_ids=" + encodeURIComponent(ids) + "&reason=" + encodeURIComponent(reason);
    var submitBtn = document.querySelector("#batch-progress-section");
    if (submitBtn) submitBtn.style.display = "block";
    admin.showToast("批量任务已提交", "info");
    fetch(url, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.data && data.data.batch_id) {
          admin._currentBatchId = data.data.batch_id;
          admin._batchPollCount = 0;
          admin.pollBatchStatus();
        } else {
          admin.showToast("提交失败：" + (data.msg || "未知错误"), "error");
        }
      }).catch(function (e) { admin.showToast("提交异常：" + e, "error"); });
  };

  admin.pollBatchStatus = function () {
    if (!admin._currentBatchId) return;
    fetch("/api/admin/data_center/batch/" + admin._currentBatchId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.data) return;
        var st = data.data;
        var info = document.getElementById("batch-progress-info");
        var bar = document.getElementById("batch-progress-bar");
        var section = document.getElementById("batch-progress-section");
        if (section) section.style.display = "block";
        if (info) {
          var __zhBatchLbl = {"completed":"已完成","running":"执行中","pending":"等待中","failed":"失败"};
          info.innerHTML = '<div><strong>批量任务ID:</strong> ' + st.batch_id + '</div>' +
            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态: ' + (__zhBatchLbl[st.status] || st.status) + ' | 总数: ' + st.total + ' | 成功: ' + st.succeeded + ' | 失败: ' + st.failed + '</div>';
        }
        var pct = st.total > 0 ? Math.round(st.processed / st.total * 100) : 0;
        if (bar) bar.style.width = pct + "%";
        if (st.status !== "completed" && admin._batchPollCount < 30) {
          admin._batchPollCount = (admin._batchPollCount || 0) + 1;
          setTimeout(function () { admin.pollBatchStatus(); }, 2000);
        } else {
          admin.loadBatchList();
          admin.showToast("批量任务已完成：" + st.batch_id, "success");
        }
      }).catch(function () { /* ignore */ });
  };

  admin.refreshBatchStatus = function () {
    admin.pollBatchStatus();
  };

  admin.loadBatchList = function () {
    fetch("/api/admin/data_center/batch/list")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var body = document.getElementById("batch-list-body");
        if (!body) return;
        if (!data.data || !data.data.items || !data.data.items.length) {
          body.innerHTML = '<tr><td colspan="9" class="empty">暂无批量任务</td></tr>';
          return;
        }
        var rows = "";
        data.data.items.forEach(function (it) {
          // 英文状态码比较 + 中文显示
          var __zhBatchStatus = {"completed":"已完成","running":"执行中","pending":"等待中","failed":"失败"};
          var __zhRisk = {"critical":"严重","high":"高","normal":"正常","low":"低"};
          var statusColor = "completed" === it.status ? "#28a745" : "running" === it.status ? "#4a90e2" : "pending" === it.status ? "#f5a623" : "#6b7a90";
          var riskColor = "critical" === it.risk_level ? "#dc3545" : "high" === it.risk_level ? "#f5a623" : "#6b7a90";
          rows += '<tr><td>' + it.batch_id + '</td>' +
                  '<td>' + (it.op_type || "") + '</td>' +
                  '<td>' + (it.operator || "") + '</td>' +
                  '<td>' + (it.total || 0) + '</td>' +
                  '<td style="color:#28a745;">' + (it.succeeded || 0) + '</td>' +
                  '<td style="color:#dc3545;">' + (it.failed || 0) + '</td>' +
                  '<td style="color:' + statusColor + ';font-weight:500;">' + (__zhBatchStatus[it.status] || it.status) + '</td>' +
                  '<td style="color:' + riskColor + ';">' + (__zhRisk[it.risk_level] || it.risk_level || "正常") + '</td>' +
                  '<td>' + (it.started_at || "") + '</td></tr>';
        });
        body.innerHTML = rows;
      }).catch(function () { /* ignore */ });
  };

  /* ---------- 4) Export Center ---------- */
  admin.loadExportStages = function () {
    fetch("/api/admin/data_center/export/list")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var sel = document.getElementById("export-stage");
        if (!sel) return;
        var stages = (data.data && data.data.stages) || [
          { key: "exception", name: "异常数据" },
          { key: "collection", name: "采集阶段" },
          { key: "cleaning", name: "清洗阶段" },
          { key: "grading", name: "商机分级" },
          { key: "outreach", name: "客户触达" },
          { key: "sales", name: "销售闭环" },
          { key: "channel_funnel", name: "渠道漏斗统计" }
        ];
        sel.innerHTML = "";
        stages.forEach(function (s) {
          var o = document.createElement("option");
          o.value = s.key;
          o.textContent = s.name || s.key;
          sel.appendChild(o);
        });
      }).catch(function () { /* ignore */ });
  };

  admin.submitExport = function () {
    var stage = document.getElementById("export-stage") ? document.getElementById("export-stage").value : "exception";
    var plaintext = document.getElementById("export-plaintext") ? document.getElementById("export-plaintext").checked : false;
    var reason = document.getElementById("export-reason") ? document.getElementById("export-reason").value : "数据导出";
    var url = "/api/admin/data_center/export/submit?stage_key=" + encodeURIComponent(stage) +
              "&export_plaintext=" + (plaintext ? "true" : "false") + "&reason=" + encodeURIComponent(reason);
    var section = document.getElementById("export-progress-section");
    if (section) section.style.display = "block";
    admin.showToast("导出任务已提交", "info");
    fetch(url, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.data && data.data.export_id) {
          admin._currentExportId = data.data.export_id;
          admin._exportPollCount = 0;
          admin.pollExportStatus();
        } else {
          admin.showToast("导出失败：" + (data.msg || "未知错误"), "error");
        }
      }).catch(function (e) { admin.showToast("导出异常：" + e, "error"); });
  };

  admin.pollExportStatus = function () {
    if (!admin._currentExportId) return;
    fetch("/api/admin/data_center/export/" + admin._currentExportId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.data) return;
        var st = data.data;
        var info = document.getElementById("export-progress-info");
        var bar = document.getElementById("export-progress-bar");
        var section = document.getElementById("export-progress-section");
        if (section) section.style.display = "block";
        if (info) {
          var size = st.file_size ? (st.file_size / 1024).toFixed(1) + " KB" : "生成中...";
          var rows = st.row_count || 0;
          var __zhExpStatus = {"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"};
          info.innerHTML = '<div><strong>导出ID:</strong> ' + st.export_id + '</div>' +
            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态：' + (__zhExpStatus[st.status] || st.status) + ' | 行数：' + rows + ' | 大小：' + size + '</div>';
          if (st.status === "ready" && st.file_content_b64) {
            var filename = "export_" + st.stage_key + "_" + st.export_id + ".csv";
            info.innerHTML += '<div style="margin-top:8px;"><a class="btn btn-primary" onclick="admin.downloadExportFile(\'' +
              st.export_id + '\')">📥 下载CSV文件</a></div>';
          }
        }
        var pct = st.status === "ready" ? 100 : st.status === "generating" ? 40 : 5;
        if (bar) bar.style.width = pct + "%";
        if (st.status !== "ready" && admin._exportPollCount < 15) {
          admin._exportPollCount = (admin._exportPollCount || 0) + 1;
          setTimeout(function () { admin.pollExportStatus(); }, 2500);
        } else if (st.status === "ready") {
          admin.loadExportList();
          admin.showToast("导出已就绪：" + st.export_id, "success");
        }
      });
  };

  admin.downloadExportFile = function (export_id) {
    fetch("/api/admin/data_center/export/" + export_id)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.data || !data.data.file_content_b64) { admin.showToast("无法获取文件内容", "error"); return; }
        var binaryString = atob(data.data.file_content_b64);
        var bytes = new Uint8Array(binaryString.length);
        for (var i = 0; i < binaryString.length; i++) bytes[i] = binaryString.charCodeAt(i);
        var blob = new Blob([bytes], { type: "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "export_" + (data.data.stage_key || "data") + "_" + export_id + ".csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        admin.showToast("文件下载已触发", "success");
      }).catch(function (e) { admin.showToast("下载异常：" + e, "error"); });
  };

  admin.loadExportList = function () {
    fetch("/api/admin/data_center/export/list")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var body = document.getElementById("export-list-body");
        if (!body) return;
        if (!data.data || !data.data.items || !data.data.items.length) {
          body.innerHTML = '<tr><td colspan="9" class="empty">暂无导出记录</td></tr>';
          return;
        }
        var rows = "";
        data.data.items.forEach(function (it) {
          var __zhExpListStatus = {"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"};
          var statusColor = "ready" === it.status ? "#28a745" : "generating" === it.status ? "#4a90e2" : "error" === it.status ? "#dc3545" : "#6b7a90";
          var maskLabel = true === it.mask_enabled ? "已脱敏" : (it.mask_enabled ? it.mask_enabled : "-");
          var downloadHtml = it.status === "ready" ? '<a class="btn btn-sm" onclick="admin.downloadExportFile(\'' + it.export_id + '\')">📥</a>' : "-";
          rows += '<tr><td>' + it.export_id + '</td>' +
                  '<td>' + (it.stage_name || it.stage_key || "") + '</td>' +
                  '<td>' + (it.operator || "") + '</td>' +
                  '<td>' + (it.row_count || 0) + '</td>' +
                  '<td>' + (it.file_size ? (it.file_size / 1024).toFixed(1) + "KB" : "-") + '</td>' +
                  '<td>' + maskLabel + '</td>' +
                  '<td style="color:' + statusColor + ';font-weight:500;">' + (__zhExpListStatus[it.status] || it.status) + '</td>' +
                  '<td>' + (it.started_at || it.completed_at || "") + '</td>' +
                  '<td>' + downloadHtml + '</td></tr>';
        });
        body.innerHTML = rows;
      }).catch(function () { /* ignore */ });
  };

  document.addEventListener("DOMContentLoaded", function () {
    applyPermissionVisibility();
    try { renderStageActionBar(); } catch (e) { /* ignore */ }
    try { injectRowActionButtons(); } catch (e) { /* ignore */ }
  });

  // Also run immediately (in case DOMContentLoaded already fired when script was late)
  try { applyPermissionVisibility(); } catch (e) { /* ignore */ }

  window.admin = admin;
})();
