/* =========================================================================
 * crawl_monitor.js — 采集任务监控页
 *   - 展示近期执行记录（状态 / 采集条数 / 匹配率 / 耗时）
 *   - 自动刷新开关（默认关）
 *   - 告警高亮：匹配率 < 60% 黄色，< 30% 红色
 * ========================================================================= */
(function () {
  "use strict";

  var autoTimer = null;

  function api(path, method, body) {
    var opts = {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body && method && method !== "GET") opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  function rateColor(rate) {
    if (rate == null) return "#999";
    if (rate < 0.3) return "#f5222d";
    if (rate < 0.6) return "#fa8c16";
    return "#52c41a";
  }

  function statusBadge(status) {
    var palette = {
      completed: { color: "#52c41a", bg: "#f6ffed", label: "成功" },
      running:   { color: "#1890ff", bg: "#e6f7ff", label: "运行中" },
      failed:    { color: "#f5222d", bg: "#fff1f0", label: "失败" },
      pending:   { color: "#888",    bg: "#f5f5f5", label: "等待" },
    };
    var p = palette[status] || palette.pending;
    return '<span style="background:' + p.bg + ';color:' + p.color + ';padding:2px 10px;border-radius:4px;font-size:12px;">' + p.label + '</span>';
  }

  function renderStats(runs) {
    var statsEl = document.getElementById("crawl-stats");
    if (!statsEl) return;
    var total = runs.length, success = 0, failed = 0, running = 0, itemsSum = 0;
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.status === "completed") success++;
      else if (r.status === "failed") failed++;
      else if (r.status === "running") running++;
      if (r.items_success) itemsSum += r.items_success;
    }
    statsEl.innerHTML =
      '<div style="padding:15px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;text-align:center;">' +
      '  <div style="font-size:24px;font-weight:bold;color:#52c41a;">' + success + '</div><div style="font-size:12px;color:#555;">成功次数</div></div>' +
      '<div style="padding:15px;background:#fff1f0;border:1px solid #ffa39e;border-radius:6px;text-align:center;">' +
      '  <div style="font-size:24px;font-weight:bold;color:#f5222d;">' + failed + '</div><div style="font-size:12px;color:#555;">失败次数</div></div>' +
      '<div style="padding:15px;background:#e6f7ff;border:1px solid #91d5ff;border-radius:6px;text-align:center;">' +
      '  <div style="font-size:24px;font-weight:bold;color:#1890ff;">' + itemsSum + '</div><div style="font-size:12px;color:#555;">累计采集条目</div></div>' +
      '<div style="padding:15px;background:#fffbe6;border:1px solid #ffe58f;border-radius:6px;text-align:center;">' +
      '  <div style="font-size:24px;font-weight:bold;color:#fa8c16;">' + total + '</div><div style="font-size:12px;color:#555;">总执行次数</div></div>';
  }

  function renderRuns(runs) {
    var container = document.getElementById("crawl-runs-container");
    if (!container) return;
    if (!runs || runs.length === 0) {
      container.innerHTML = '<div style="padding:30px;text-align:center;color:#999;">暂无执行记录。请在「方案管理」中创建方案并启动采集。</div>';
      return;
    }
    var html = [];
    html.push(
      '<table style="width:100%;border-collapse:collapse;">' +
      '  <thead><tr style="background:#f5f7fa;">' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">方案 ID</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">状态</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">总数</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">成功</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">匹配率</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">耗时</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">触发人</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">开始时间</th>' +
      '  </tr></thead><tbody>'
    );
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      var rowBg = (i % 2 === 0) ? "white" : "#fafbfc";
      var rateColor = rateColor(r.field_match_rate);
      var rateDisplay = (r.field_match_rate != null && r.field_match_rate !== undefined)
        ? (Math.round(r.field_match_rate * 100) + "%")
        : "-";
      html.push(
        '<tr style="background:' + rowBg + ';">' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">#' + r.plan_id + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;">' + statusBadge(r.status) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (r.items_total || 0) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;color:#52c41a;">' + (r.items_success || 0) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;color:' + rateColor + ';font-weight:bold;">' + rateDisplay + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + ((r.duration_ms || 0)) + ' ms</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (r.trigger_by || "-") + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:12px;color:#666;">' + (r.started_at || "-") + '</td>' +
        '</tr>'
      );
    }
    html.push("</tbody></table>");
    container.innerHTML = html.join("");
  }

  function refresh() {
    api("/api/admin/crawl/runs?page=1&page_size=50").then(function (data) {
      var items = (data && data.data && data.data.items) || (data && data.items) || [];
      renderStats(items);
      renderRuns(items);
    }).catch(function () {
      var container = document.getElementById("crawl-runs-container");
      if (container) container.innerHTML = '<div style="color:#f5222d;padding:20px;">加载失败，请检查网络</div>';
    });
  }

  function toggleAuto() {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
      var btn = document.getElementById("btn-auto");
      if (btn) btn.textContent = "⏱ 自动刷新: 关";
    } else {
      autoTimer = setInterval(refresh, 10000);
      var btn2 = document.getElementById("btn-auto");
      if (btn2) btn2.textContent = "⏱ 自动刷新: 开（10s）";
    }
  }

  window.crawlMonitor = {
    refresh: refresh,
    autoToggle: toggleAuto,
  };

  // 启动
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refresh);
  } else {
    refresh();
  }
})();
