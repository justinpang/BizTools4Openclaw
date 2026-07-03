/* ================================================================
 * admin.js · BizTools4Openclaw 管理后台交互脚本
 * ================================================================ */

(function () {
  const API_BASE = "/api/admin";

  function maskPhone(v) {
    if (!v) return "";
    v = String(v);
    if (v.includes("@")) {
      var p = v.split("@");
      var pre = p[0];
      return (pre[0] || "") + "***" + (pre.length > 1 ? pre[pre.length - 1] : "") + "@***";
    }
    if (/^\d{7,}$/.test(v)) return v.slice(0, 3) + "****" + v.slice(-4);
    if (v.length > 4) return v[0] + "***" + v[v.length - 1];
    return v.slice(0, 1) + "****";
  }

  async function api(path, opts) {
    var options = opts || {};
    options.headers = options.headers || {};
    options.headers["X-Requested-With"] = "XMLHttpRequest";
    if (options.body && typeof options.body !== "string") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    var res = await fetch(API_BASE + path, options);
    if (res.status === 401) {
      window.location.href = "/admin/login";
      return null;
    }
    try { return await res.json(); }
    catch (e) { return { code: res.status, msg: res.statusText, data: null }; }
  }

  /* ---------- 侧边栏菜单 ---------- */
  var MENU = [
    { key: "dashboard", title: "数据看板", icon: "📊", href: "/admin/dashboard" },
    { key: "spider",    title: "爬虫任务", icon: "🕷", href: "/admin/spider" },
    { key: "leads",     title: "商机线索", icon: "💼", href: "/admin/leads" },
    { key: "channels",  title: "渠道账号", icon: "📡", href: "/admin/channels" },
    { key: "sales",     title: "销售管理", icon: "👥", href: "/admin/sales" },
    { key: "audit_log", title: "操作日志", icon: "📜", href: "/admin/audit_log" },
  ];

  function renderSidebar(activeKey) {
    var sb = document.getElementById("sidebar");
    if (!sb) return;
    var html = '<div class="brand">BizTools4Openclaw</div>';
    for (var i = 0; i < MENU.length; i++) {
      var m = MENU[i];
      var cls = "menu-link" + (m.key === activeKey ? " active" : "");
      html += '<a class="' + cls + '" href="' + m.href + '">' + m.icon + ' <span>' + m.title + '</span></a>';
    }
    sb.innerHTML = html;
  }

  /* ---------- Dashboard ---------- */
  function loadDashboard() {
    renderSidebar("dashboard");
    var stats = [
      { key: "spider_tasks", label: "爬虫任务", hint: "已登记任务数" },
      { key: "crawled_total", label: "抓取总量", hint: "累计抓取条目" },
      { key: "leads_total", label: "有效线索", hint: "已通过清洗校验" },
      { key: "send_total", label: "触达批次", hint: "邮件/企微/飞书批次" },
      { key: "accounts_total", label: "渠道账号", hint: "邮件/企微/飞书 总数" },
    ];
    // 先用 skeleton 渲染
    var grid = document.getElementById("stats-grid");
    if (grid) {
      var html = "";
      for (var i = 0; i < stats.length; i++) {
        html += '<div class="stat-card"><div class="label">' + stats[i].label + '</div>' +
          '<div class="value" id="val-' + stats[i].key + '">-</div>' +
          '<div class="hint">' + stats[i].hint + '</div></div>';
      }
      grid.innerHTML = html;
    }
    api("/dashboard/stats", { method: "GET" }).then(function (j) {
      if (!j) return;
      var data = (j.data || {});
      for (var i = 0; i < stats.length; i++) {
        var el = document.getElementById("val-" + stats[i].key);
        if (el) el.textContent = String(data[stats[i].key] ?? 0);
      }
      var funnel = document.getElementById("funnel-area");
      if (funnel && data.funnel) {
        var rows = [];
        var fm = data.funnel;
        if (typeof fm === "object" && fm !== null) {
          for (var k in fm) {
            if (Object.prototype.hasOwnProperty.call(fm, k)) {
              rows.push({ name: k, count: typeof fm[k] === "number" ? fm[k] : parseInt(String(fm[k]).replace(/\D/g, "") || "0", 10) || 0 });
            }
          }
        }
        var max = 1;
        for (var r = 0; r < rows.length; r++) if (rows[r].count > max) max = rows[r].count;
        var fhtml = "";
        for (var r2 = 0; r2 < rows.length; r2++) {
          var pct = Math.round(100 * rows[r2].count / max);
          fhtml += '<div class="funnel-row"><div class="name">' + rows[r2].name + '</div>' +
            '<div class="bar-wrapper"><div class="bar" style="width:' + pct + '%"></div></div>' +
            '<div class="count">' + rows[r2].count + '</div></div>';
        }
        if (!fhtml) fhtml = '<div style="color:#6b7280;font-size:12px;">无漏斗数据（需先有分配/跟进/成交）</div>';
        funnel.innerHTML = fhtml;
      }
      var recent = document.getElementById("recent-tasks");
      if (recent && Array.isArray(data.recent_tasks) && data.recent_tasks.length) {
        var th = '<table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>时间</th></tr></thead><tbody>';
        var tb = "";
        for (var t = 0; t < data.recent_tasks.length; t++) {
          var task = data.recent_tasks[t];
          tb += '<tr><td>' + (task.name || "") + '</td><td>' + (task.status || "") + '</td><td>' + (task.ts || "") + '</td></tr>';
        }
        recent.innerHTML = th + tb + '</tbody></table>';
      } else if (recent) {
        recent.innerHTML = '<div style="color:#6b7280;font-size:12px;">暂无任务记录</div>';
      }
    });
  }

  /* ---------- Spider ---------- */
  function loadSpider() {
    renderSidebar("spider");
    api("/spider/tasks", { method: "GET" }).then(function (j) {
      if (!j) return;
      var sel = document.getElementById("spider-name-select");
      if (sel && Array.isArray(j.spider_names)) {
        sel.innerHTML = "";
        for (var i = 0; i < j.spider_names.length; i++) {
          var opt = document.createElement("option");
          opt.value = j.spider_names[i];
          opt.textContent = j.spider_names[i];
          sel.appendChild(opt);
        }
      }
      var body = document.getElementById("tasks-body");
      if (!body) return;
      if (!Array.isArray(j.items) || j.items.length === 0) {
        body.innerHTML = '<tr><td colspan="7" class="empty">暂无任务，点击上方添加。</td></tr>';
        return;
      }
      var html = "";
      for (var i = 0; i < j.items.length; i++) {
        var item = j.items[i];
        html += '<tr><td>' + (item.job_id || "") + '</td>' +
          '<td>' + (item.spider_name || "") + '</td>' +
          '<td>' + (item.cron || "") + '</td>' +
          '<td>' + (Array.isArray(item.keywords) ? item.keywords.join(", ") : "") + '</td>' +
          '<td>' + (item.status || "") + '</td>' +
          '<td>' + (item.next_run || "-") + '</td>' +
          '<td>' +
          '<button class="btn btn-sm" onclick="admin.runTask(\'' + (item.job_id || "") + '\')">立即运行</button> ' +
          '<button class="btn btn-sm" onclick="admin.pauseTask(\'' + (item.job_id || "") + '\')">暂停</button> ' +
          '<button class="btn btn-sm" onclick="admin.resumeTask(\'' + (item.job_id || "") + '\')">恢复</button> ' +
          '<button class="btn btn-sm btn-danger" onclick="admin.deleteTask(\'' + (item.job_id || "") + '\')">删除</button>' +
          '</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  function createSpiderTask(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/spider/task", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      alert((j && j.msg) || "已保存");
      loadSpider();
    });
    return false;
  }

  function runTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/run", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      alert("已触发运行：\n" + (j.result || j.msg || ""));
    });
  }

  function pauseTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/pause", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已暂停"); });
  }

  function resumeTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/resume", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已恢复"); });
  }

  function deleteTask(id) {
    if (!confirm("确定删除任务 " + id + "？")) return;
    fetch(API_BASE + "/spider/task/" + id, { method: "DELETE", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { loadSpider(); });
  }

  function loadSpiderLogs() {
    var id = document.getElementById("log-job-id").value || "demo";
    fetch(API_BASE + "/spider/task/" + id + "/logs", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var out = document.getElementById("logs-out");
      if (out) out.textContent = Array.isArray(j.items) ? j.items.join("\n") : "(无日志)";
    });
  }

  function loadRisks() {
    fetch(API_BASE + "/spider/risks", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var out = document.getElementById("risks-out");
      if (out) out.textContent = Array.isArray(j.items) && j.items.length ? j.items.join("\n") : "(无风控异常)";
    });
  }

  /* ---------- Leads ---------- */
  function loadLeads() {
    renderSidebar("leads");
    var kw = (document.getElementById("keyword") || {}).value || "";
    var st = (document.getElementById("status") || {}).value || "";
    var qs = "?keyword=" + encodeURIComponent(kw) + "&status=" + encodeURIComponent(st);
    api("/leads" + qs, { method: "GET" }).then(function (j) {
      if (!j) return;
      var body = document.getElementById("leads-body");
      if (!body) return;
      if (!Array.isArray(j.items) || j.items.length === 0) {
        body.innerHTML = '<tr><td colspan="5" class="empty">暂无线索（需先运行爬虫/清洗流程）</td></tr>';
        return;
      }
      var html = "";
      for (var i = 0; i < j.items.length; i++) {
        var item = j.items[i] || {};
        html += '<tr><td>' + (item.opportunity_id || item.id || "") + '</td>' +
          '<td>' + (item.title || item.customer || "-") + '</td>' +
          '<td>' + (item.phone ? maskPhone(item.phone) : (item.customer || "-")) + '</td>' +
          '<td>' + (item.status || "-") + '</td>' +
          '<td>' +
          '<button class="btn btn-sm" onclick="admin.approveLead(\'' + (item.opportunity_id || item.id || "") + '\')">通过</button> ' +
          '<button class="btn btn-sm btn-danger" onclick="admin.rejectLead(\'' + (item.opportunity_id || item.id || "") + '\')">拒绝</button>' +
          '</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  function approveLead(id) {
    fetch(API_BASE + "/leads/" + id + "/approve", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已通过"); loadLeads(); });
  }

  function rejectLead(id) {
    if (!confirm("拒绝后该商机将被加入黑名单，确认？")) return;
    fetch(API_BASE + "/leads/" + id + "/reject", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded" }, body: "reason=人工复核拒绝" }).then(function () { alert("已拒绝"); loadLeads(); });
  }

  function addBlacklist(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/leads/blacklist/add", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已加入"); loadBlacklist(); });
    return false;
  }

  function loadBlacklist() {
    fetch(API_BASE + "/leads/blacklist", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("blacklist-body");
      if (!body) return;
      if (!Array.isArray(j.items) || j.items.length === 0) { body.textContent = "(无黑名单记录)"; return; }
      body.textContent = JSON.stringify(j.items, null, 2);
    });
  }

  /* ---------- Channels ---------- */
  function loadChannels() {
    renderSidebar("channels");
    fetch(API_BASE + "/channels", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var wrap = document.getElementById("channels-wrap");
      if (!wrap) return;
      var data = j.data || [];
      var html = "";
      for (var i = 0; i < data.length; i++) {
        var ch = data[i];
        html += '<div class="panel" style="margin-bottom:16px;">';
        html += '<h3>🛰 ' + ch.channel + '（' + ch.count + ' 个账号）</h3>';
        html += '<table class="data-table"><thead><tr><th>账号 ID</th><th>用户名</th><th>密码</th><th>状态</th><th>额度/日</th><th>已发</th><th>操作</th></tr></thead><tbody>';
        if (Array.isArray(ch.accounts)) {
          for (var k = 0; k < ch.accounts.length; k++) {
            var a = ch.accounts[k];
            html += '<tr><td>' + a.account_id + '</td><td>' + (a.username || "-") + '</td>' +
              '<td>********</td>' +
              '<td>' + (a.status || "ACTIVE") + '</td>' +
              '<td>' + (a.quota || "-") + '</td>' +
              '<td>' + (a.today_sent || 0) + '</td>' +
              '<td><button class="btn btn-sm" onclick="admin.banAccount(\'' + ch.channel + '\',\'' + a.account_id + '\')">封禁</button> ' +
              '<button class="btn btn-sm" onclick="admin.unbanAccount(\'' + ch.channel + '\',\'' + a.account_id + '\')">解封</button></td></tr>';
          }
        }
        html += '</tbody></table></div>';
      }
      wrap.innerHTML = html;
    });
  }

  function createAccount(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/channels/account", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("账号已保存（密码已加密）"); loadChannels(); });
    return false;
  }

  function banAccount(channel, id) {
    fetch(API_BASE + "/channels/" + channel + "/ban/" + id, { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已封禁"); loadChannels(); });
  }

  function unbanAccount(channel, id) {
    fetch(API_BASE + "/channels/" + channel + "/unban/" + id, { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已解封"); loadChannels(); });
  }

  /* ---------- Sales ---------- */
  function loadSales() {
    renderSidebar("sales");
    fetch(API_BASE + "/sales/persons", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("persons-body");
      if (!body) return;
      var items = j.items || [];
      if (!items.length) { body.innerHTML = '<tr><td colspan="6" class="empty">暂无销售</td></tr>'; return; }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var p = items[i];
        html += '<tr><td>' + (p.sales_id || "") + '</td>' +
          '<td>' + (p.name || "") + '</td>' +
          '<td>' + (Array.isArray(p.industries) ? p.industries.join(", ") : (p.industries || "")) + '</td>' +
          '<td>' + (p.weight || 1.0) + '</td>' +
          '<td>' + maskPhone(p.phone || "") + '</td>' +
          '<td>' + maskPhone(p.email || "") + '</td></tr>';
      }
      body.innerHTML = html;
    });
    fetch(API_BASE + "/sales/assignments", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("assignments-body");
      if (!body) return;
      var items = j.items || [];
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var a = items[i];
        html += '<tr><td>' + (a.assignment_id || "") + '</td><td>' + (a.customer || a.opportunity_id || "") + '</td>' +
          '<td>' + (a.sales_id || "auto") + '</td><td>' + (a.status || "-") + '</td><td>' + (a.assigned_at || "-") + '</td></tr>';
      }
      body.innerHTML = html || '<tr><td colspan="5" class="empty">(暂无分配记录)</td></tr>';
    });
    fetch(API_BASE + "/sales/followups", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("followups-body");
      if (!body) return;
      var items = j.items || [];
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var f = items[i];
        html += '<tr><td>' + (f.followup_id || "") + '</td><td>' + (f.opportunity_id || "") + '</td><td>' + (f.channel || "") + '</td>' +
          '<td>' + (f.content || "") + '</td><td>' + (f.by || f.sales_id || "") + '</td><td>' + (f.ts || "") + '</td></tr>';
      }
      body.innerHTML = html || '<tr><td colspan="6" class="empty">(暂无跟进记录)</td></tr>';
    });
  }

  function upsertPerson(e) {
    e.preventDefault();
    var body = new FormData(e.target);
    fetch(API_BASE + "/sales/person", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已保存"); loadSales(); });
    return false;
  }

  function doAssign(e) {
    e.preventDefault();
    var body = new FormData(e.target);
    fetch(API_BASE + "/sales/assign", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已分配"); loadSales(); });
    return false;
  }

  function recordFollowup(e) {
    e.preventDefault();
    var body = new FormData(e.target);
    fetch(API_BASE + "/sales/followup", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function () { alert("已记录"); loadSales(); });
    return false;
  }

  function loadOverdue() {
    fetch(API_BASE + "/sales/overdue", { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("overdue-body");
      if (!body) return;
      var items = j.items || [];
      if (!items.length) { body.innerHTML = '<tr><td colspan="4" class="empty">(无逾期跟进)</td></tr>'; return; }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var f = items[i];
        html += '<tr><td>' + (f.opportunity_id || "") + '</td><td>' + (f.sales_id || "-") + '</td>' +
          '<td>' + (f.last_followup_at || "-") + '</td><td>' + (f.hint || "逾期跟进") + '</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  /* ---------- Audit ---------- */
  function loadAuditLogs() {
    renderSidebar("audit_log");
    var limit = parseInt(document.getElementById("limit").value || "50", 10) || 50;
    fetch(API_BASE + "/audit/logs?limit=" + limit, { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (r) { return r.json(); }).then(function (j) {
      var body = document.getElementById("audit-body");
      if (!body) return;
      var items = j.items || [];
      if (!items.length) { body.innerHTML = '<tr><td colspan="6" class="empty">(暂无日志)</td></tr>'; return; }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var a = items[i];
        var d = a.ts ? new Date(a.ts * 1000) : null;
        html += '<tr><td>' + (d ? d.toLocaleString() : a.ts) + '</td>' +
          '<td>' + (a.username || "-") + '</td>' +
          '<td>' + (a.ip || "-") + '</td>' +
          '<td>' + (a.path || "-") + '</td>' +
          '<td>' + (a.status || "-") + '</td>' +
          '<td>' + (a.latency_ms || 0) + ' ms</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  /* ---------- Page bootstrap ---------- */
  function bootstrap() {
    var page = (window.__PAGE__ || location.pathname.replace("/admin/", "").split("/")[0] || "dashboard");
    switch (page) {
      case "dashboard": loadDashboard(); break;
      case "spider": loadSpider(); break;
      case "leads": loadLeads(); break;
      case "channels": loadChannels(); break;
      case "sales": loadSales(); break;
      case "audit_log": loadAuditLogs(); break;
      default: renderSidebar(page); break;
    }
  }

  window.admin = {
    maskPhone: maskPhone,
    api: api,
    // dashboard
    // spider
    createSpiderTask: createSpiderTask,
    runTask: runTask,
    pauseTask: pauseTask,
    resumeTask: resumeTask,
    deleteTask: deleteTask,
    loadSpiderLogs: loadSpiderLogs,
    loadRisks: loadRisks,
    // leads
    loadLeads: loadLeads,
    approveLead: approveLead,
    rejectLead: rejectLead,
    addBlacklist: addBlacklist,
    loadBlacklist: loadBlacklist,
    // channels
    loadChannels: loadChannels,
    createAccount: createAccount,
    banAccount: banAccount,
    unbanAccount: unbanAccount,
    // sales
    loadSales: loadSales,
    upsertPerson: upsertPerson,
    doAssign: doAssign,
    recordFollowup: recordFollowup,
    loadOverdue: loadOverdue,
    // audit
    loadAuditLogs: loadAuditLogs,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootstrap);
  else bootstrap();
})();
