/* ================================================================
 * admin.js · BizTools4Openclaw 管理后台交互脚本
 *
 *  1. 顶层命名空间 admin.{ui, api}
 *  2. admin.ui.bootstrap() 从 <script type="application/json" id="admin-init-json">
 *     读取初始化数据（username / role / permissions / menuGroups / activeKey）
 *  3. 菜单按权限渲染；按钮按 data-requires-permission 过滤；
 *     全局搜索按菜单标题模糊匹配 → 点击或回车跳转
 *  4. 脱敏工具：autoMask(root) 对所有带 data-sensitive 的元素进行掩码
 *     敏感字段同时在 DOM 层面拦截 copy/cut 事件
 *  5. 保留原有业务页面逻辑（loadDashboard / Spider / Leads / Channels / Sales）
 *     不破坏现有功能
 * ================================================================ */

(function () {
  "use strict";

  // -------- 常量 --------
  var API_BASE = "/api/admin";
  var MENU_FLAT = [
    { key: "dashboard", title: "数据看板", icon: "📊", href: "/admin/dashboard" },
    { key: "spider",    title: "爬虫任务", icon: "🕷", href: "/admin/spider" },
    { key: "leads",     title: "商机线索", icon: "💼", href: "/admin/leads" },
    { key: "channels",  title: "渠道账号", icon: "📡", href: "/admin/channels" },
    { key: "sales",     title: "销售管理", icon: "👥", href: "/admin/sales" },
    { key: "audit_log", title: "操作日志", icon: "📜", href: "/admin/audit_log" },
  ];

  // -------- 工具函数 --------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // -------- 脱敏工具 --------
  function maskPhone(v) {
    if (!v) return "";
    v = String(v).replace(/\D/g, "");
    if (v.length <= 4) return v.replace(/./g, "*");
    return v.slice(0, 3) + "****" + v.slice(-4);
  }
  function maskEmail(v) {
    if (!v) return "";
    v = String(v);
    var at = v.indexOf("@");
    if (at <= 0) return v[0] + "****";
    var pre = v.slice(0, at);
    var masked = (pre[0] || "") + "****" + (pre.length > 1 ? pre.slice(-1) : "");
    return masked + "@***";
  }
  function maskWechat(v) {
    if (!v) return "";
    v = String(v);
    if (v.length <= 4) return v.replace(/./g, "*");
    return v.slice(0, 2) + "****" + v.slice(-2);
  }
  function maskSecret(v) { return "********"; }
  function maskPassword(v) { return "********"; }

  function maskByType(type, value) {
    switch (type) {
      case "phone":    return maskPhone(value);
      case "email":    return maskEmail(value);
      case "wechat":   return maskWechat(value);
      case "secret":   return maskSecret();
      case "password": return maskPassword();
      default:         return maskSecret();
    }
  }

  function autoMask(root) {
    if (!root) root = document;
    // 1) 显式声明 data-sensitive="type" 的元素
    $all("[data-sensitive]", root).forEach(function (el) {
      var type = el.getAttribute("data-sensitive") || "secret";
      // 仅在从未被处理过时执行，避免重复掩码破坏 DOM
      if (el.getAttribute("data-mask-applied") === "1") return;
      var originalText = el.textContent;
      el.setAttribute("data-mask-original", originalText);
      el.textContent = maskByType(type, originalText);
      el.classList.add("sensitive-mask");
      el.classList.add(type);
      el.setAttribute("data-mask-applied", "1");
      // 禁用密钥/密码的 copy / cut
      if (type === "secret" || type === "password") {
        el.addEventListener("copy",  function (e) { e.preventDefault(); return false; });
        el.addEventListener("cut",   function (e) { e.preventDefault(); return false; });
        el.addEventListener("contextmenu", function (e) { e.preventDefault(); return false; });
      }
    });

    // 2) 自动识别常见字段（表格中 phone/email/password/secret 列）
    // 查找业务 API 渲染后的表格 td，根据其前后文文本/属性进行启发式识别
    $all(".data-table td, td.phone, td.email, td.secret, td.password, td.wechat, td[class*='phone'], td[class*='email'], td[class*='password']", root)
      .forEach(function (el) {
        if (el.getAttribute("data-mask-applied") === "1") return;
        var text = (el.textContent || "").trim();
        if (!text) return;
        var type = null;
        // 启发式：匹配手机号 / 邮箱 / 密码列提示
        if (/^1[3-9]\d{9}$/.test(text.replace(/\s+/g, "")))     type = "phone";
        else if (/^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(text))         type = "email";
        else if (/^(wx|wechat|weixin)_/i.test(text))              type = "wechat";
        else if (/^[a-z0-9_\-]{16,}$/i.test(text) && text.length >= 20) type = "secret";
        if (type) {
          el.setAttribute("data-sensitive", type);
          el.setAttribute("data-mask-original", text);
          el.textContent = maskByType(type, text);
          el.classList.add("sensitive-mask");
          el.classList.add(type);
          el.setAttribute("data-mask-applied", "1");
          if (type === "secret" || type === "password") {
            el.addEventListener("copy", function (e) { e.preventDefault(); return false; });
            el.addEventListener("cut",  function (e) { e.preventDefault(); return false; });
          }
        }
      });
  }

  // -------- 权限：按钮/元素过滤 --------
  function applyPermission(root, permissions) {
    if (!root) root = document;
    var permSet = Object.create(null);
    (permissions || []).forEach(function (p) { permSet[p] = 1; });

    // 带 data-requires-permission 的元素：无权限 → display:none
    $all("[data-requires-permission]", root).forEach(function (el) {
      var req = (el.getAttribute("data-requires-permission") || "").trim();
      if (!req) return;
      var needList = req.split(/[\s,]+/).filter(Boolean);
      // 多权限：只要命中任意一个即可显示（OR 语义，方便按钮按角色复用）
      var ok = needList.some(function (p) { return permSet[p]; });
      el.style.display = ok ? "" : "none";
    });

    // 表单：若最外层 form 需要权限，也按同样逻辑处理
    $all("form[data-requires-permission]", root).forEach(function (form) {
      var req = (form.getAttribute("data-requires-permission") || "").trim();
      var needList = req.split(/[\s,]+/).filter(Boolean);
      var ok = needList.some(function (p) { return permSet[p]; });
      if (!ok) {
        // 无权限 → 整个表单隐藏
        form.style.display = "none";
      }
    });
  }

  // -------- 菜单渲染 --------
  function renderSidebar(activeKey, menuGroups) {
    var sb = $("#sidebar-inner");
    // 若新布局不存在（旧页面），回落到老渲染方式
    if (!sb) {
      var old = $("#sidebar");
      if (old) {
        var html = '<div class="brand">BizTools4Openclaw</div>';
        for (var i = 0; i < MENU_FLAT.length; i++) {
          var m = MENU_FLAT[i];
          var cls = "menu-link" + (m.key === activeKey ? " active" : "");
          html += '<a class="' + cls + '" href="' + m.href + '">' +
            m.icon + ' <span>' + m.title + '</span></a>';
        }
        old.innerHTML = html;
      }
      return;
    }

    if (!menuGroups || !menuGroups.length) {
      // 向后兼容：若后端未返回分组菜单，则渲染扁平版
      var flatHtml = "";
      for (var j = 0; j < MENU_FLAT.length; j++) {
        var mm = MENU_FLAT[j];
        var cls2 = "menu-item" + (mm.key === activeKey ? " active" : "");
        flatHtml += '<a class="' + cls2 + '" href="' + mm.href + '">' +
          '<span class="menu-item-icon">' + mm.icon + '</span>' +
          '<span class="menu-item-title">' + mm.title + '</span></a>';
      }
      sb.innerHTML = '<div class="menu-group"><div class="menu-group-title">后台</div>' +
        '<div class="menu-group-items">' + flatHtml + '</div></div>';
      return;
    }

    var groupsHtml = "";
    for (var g = 0; g < menuGroups.length; g++) {
      var group = menuGroups[g];
      if (!group.items || !group.items.length) continue;
      var itemsHtml = "";
      for (var k = 0; k < group.items.length; k++) {
        var item = group.items[k];
        var activeCls = "menu-item" + (item.key === activeKey ? " active" : "");
        itemsHtml += '<a class="' + activeCls + '" href="' + item.href + '" data-key="' + item.key + '">' +
          '<span class="menu-item-icon">' + (item.icon || "·") + '</span>' +
          '<span class="menu-item-title">' + escapeHtml(item.title) + '</span></a>';
      }
      groupsHtml += '<div class="menu-group" data-group="' + (group.group_key || group.title || "") + '">' +
        '<div class="menu-group-title"><span class="menu-group-icon">' + (group.icon || "") + '</span>' +
        '<span>' + escapeHtml(group.title) + '</span></div>' +
        '<div class="menu-group-items">' + itemsHtml + '</div>' +
        '</div>';
    }
    sb.innerHTML = groupsHtml;
  }

  // -------- 面包屑 --------
  function renderBreadcrumb(activeKey, menuGroups) {
    var bc = $("#breadcrumb");
    if (!bc) return;
    // 从分组菜单中反推
    var groupTitle = "", itemTitle = "";
    if (menuGroups && menuGroups.length) {
      outer: for (var i = 0; i < menuGroups.length; i++) {
        var items = menuGroups[i].items || [];
        for (var j = 0; j < items.length; j++) {
          if (items[j].key === activeKey) {
            groupTitle = menuGroups[i].title;
            itemTitle = items[j].title;
            break outer;
          }
        }
      }
    }
    if (!groupTitle) {
      // 回落到扁平 MENU_FLAT 查找
      for (var k = 0; k < MENU_FLAT.length; k++) {
        if (MENU_FLAT[k].key === activeKey) {
          itemTitle = MENU_FLAT[k].title;
          groupTitle = "管理";
          break;
        }
      }
    }
    if (itemTitle) {
      bc.innerHTML = (groupTitle ? '<span class="crumb">' + escapeHtml(groupTitle) + '</span> / ' : '') +
        '<span class="crumb">' + escapeHtml(itemTitle) + '</span>';
    }
  }

  // -------- 全局搜索（菜单标题模糊匹配） --------
  function bindGlobalSearch(inputEl, menuGroups) {
    if (!inputEl) return;
    var allItems = [];
    if (menuGroups && menuGroups.length) {
      for (var i = 0; i < menuGroups.length; i++) {
        var items = menuGroups[i].items || [];
        for (var j = 0; j < items.length; j++) {
          allItems.push({
            title: items[j].title,
            group: menuGroups[i].title,
            href: items[j].href,
            key: items[j].key,
          });
        }
      }
    } else {
      for (var k = 0; k < MENU_FLAT.length; k++) {
        allItems.push({
          title: MENU_FLAT[k].title, group: "",
          href: MENU_FLAT[k].href, key: MENU_FLAT[k].key,
        });
      }
    }
    // 创建建议面板 DOM
    var panel = document.createElement("div");
    panel.className = "global-search-panel";
    panel.style.cssText =
      "position:absolute;top:100%;left:0;right:0;z-index:50;background:#fff;" +
      "box-shadow:0 8px 24px rgba(0,0,0,.08);border-radius:8px;max-height:320px;overflow-y:auto;" +
      "display:none;margin-top:4px;border:1px solid #e5e7eb;";
    inputEl.parentNode.style.position = "relative";
    inputEl.parentNode.appendChild(panel);

    function renderPanel(keyword) {
      if (!keyword) { panel.style.display = "none"; panel.innerHTML = ""; return; }
      var kw = keyword.toLowerCase();
      var matched = allItems.filter(function (it) {
        return it.title.toLowerCase().indexOf(kw) !== -1 ||
          (it.group || "").toLowerCase().indexOf(kw) !== -1 ||
          (it.key || "").toLowerCase().indexOf(kw) !== -1;
      });
      if (!matched.length) {
        panel.innerHTML = '<div style="padding:12px 14px;color:#9ca3af;font-size:13px;">无匹配菜单</div>';
      } else {
        var html = "";
        for (var i = 0; i < matched.length; i++) {
          var item = matched[i];
          html +=
            '<a href="' + item.href + '" data-index="' + i +
            '" style="display:block;padding:8px 14px;text-decoration:none;color:#111827;font-size:13px;' +
            (i === 0 ? "background:#eef2ff;" : "") + '">' +
            '<div style="font-weight:500;">' + escapeHtml(item.title) + '</div>' +
            (item.group ? '<div style="font-size:11px;color:#6b7280;">' + escapeHtml(item.group) + '</div>' : "") +
            '</a>';
        }
        panel.innerHTML = html;
      }
      panel.style.display = "block";
    }

    inputEl.addEventListener("input", function () { renderPanel(inputEl.value.trim()); });
    inputEl.addEventListener("focus", function () { renderPanel(inputEl.value.trim()); });
    document.addEventListener("click", function (e) {
      if (panel.contains(e.target) || e.target === inputEl) return;
      panel.style.display = "none";
    });
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        var first = panel.querySelector('a[data-index="0"]');
        if (first) window.location.href = first.getAttribute("href");
      } else if (e.key === "Escape") {
        panel.style.display = "none";
      }
    });
  }

  // -------- API 请求封装 --------
  async function api(path, opts) {
    var options = opts || {};
    options.headers = options.headers || {};
    options.headers["X-Requested-With"] = "XMLHttpRequest";
    options.headers["Accept"] = "application/json";
    if (options.body && typeof options.body !== "string" && !(options.body instanceof FormData)) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    try {
      var res = await fetch(API_BASE + path, options);
      if (res.status === 401) {
        window.location.href = "/admin/login";
        return null;
      }
      if (res.status === 403) {
        alert("权限不足，无法执行该操作。");
        return null;
      }
      return await res.json();
    } catch (err) {
      console.error("api error", err);
      return { code: 500, msg: "网络异常", data: null };
    }
  }

  // -------- 业务页面渲染函数（保持原有风格，但改用新 API/脱敏） --------
  function loadDashboard(init) {
    var grid = document.getElementById("stats-grid");
    // 骨架
    if (grid) {
      var placeholders = ["爬虫任务", "抓取总量", "有效线索", "触达批次", "渠道账号"];
      var html = "";
      for (var i = 0; i < placeholders.length; i++) {
        html += '<div class="stat-card"><div class="label">' + placeholders[i] +
          '</div><div class="value">...</div></div>';
      }
      grid.innerHTML = html;
    }
    api("/dashboard/stats", { method: "GET" }).then(function (j) {
      if (!j || !grid) return;
      var data = j.data || j || {};
      var values = {
        "爬虫任务": data.spider_tasks || 0,
        "抓取总量": data.crawled_total || 0,
        "有效线索": data.leads_total || 0,
        "触达批次": data.send_total || 0,
        "渠道账号": data.accounts_total || 0,
      };
      var out = "";
      for (var k in values) {
        if (!Object.prototype.hasOwnProperty.call(values, k)) continue;
        out += '<div class="stat-card"><div class="label">' + k +
          '</div><div class="value">' + values[k] + '</div></div>';
      }
      grid.innerHTML = out;
    });

    var funnel = document.getElementById("funnel-area");
    if (funnel) funnel.innerHTML = '<div class="empty-inline">暂无数据</div>';
    var recent = document.getElementById("recent-tasks");
    if (recent) recent.innerHTML = '<div class="empty-inline">暂无任务</div>';

    api("/dashboard/stats", { method: "GET" }).then(function (j) {
      if (!j) return;
      var data = j.data || j || {};
      if (funnel && data.funnel) {
        var rows = [];
        var fm = data.funnel;
        if (typeof fm === "object" && fm !== null) {
          for (var key in fm) {
            if (Object.prototype.hasOwnProperty.call(fm, key)) {
              rows.push({ name: key, count: typeof fm[key] === "number" ? fm[key] : 0 });
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
        funnel.innerHTML = fhtml || '<div class="empty-inline">暂无数据</div>';
      }
    });
  }

  function loadSpider() {
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
        body.innerHTML = '<tr><td colspan="7" class="empty">暂无任务，点击上方保存任务。</td></tr>';
        return;
      }
      var html = "";
      for (var k = 0; k < j.items.length; k++) {
        var item = j.items[k];
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
          '<button class="btn btn-sm btn-danger" data-requires-permission="btn.spider.delete" onclick="admin.deleteTask(\'' + (item.job_id || "") + '\')">删除</button>' +
          '</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  function createSpiderTask(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/spider/task", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var msg = (j && j.msg) || "Saved";
        if (j && j.needs_approval) msg = "[Pending Review] Task saved, waiting for compliance review: " + msg;
        alert(msg);
        if (typeof loadSpider === "function") loadSpider();
        if (typeof loadSpiderFiltered === "function") loadSpiderFiltered();
      })
      .catch(function (err) { alert("Failed to create task: " + String(err || "")); });
    return false;
  }
  function runTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/run", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) { alert("已触发运行：\n" + (j.result || j.msg || "")); });
  }
  function pauseTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/pause", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已暂停"); });
  }
  function resumeTask(id) {
    fetch(API_BASE + "/spider/task/" + id + "/resume", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已恢复"); });
  }
  function deleteTask(id) {
    if (!confirm("确定删除任务 " + id + "？")) return;
    fetch(API_BASE + "/spider/task/" + id, { method: "DELETE", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { loadSpider(); });
  }
  function loadSpiderLogs() {
    var id = (document.getElementById("log-job-id") || {}).value || "demo";
    fetch(API_BASE + "/spider/task/" + id + "/logs", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var out = document.getElementById("logs-out");
        if (out) out.textContent = Array.isArray(j.items) ? j.items.join("\n") : "(无日志)";
      });
  }
  function loadRisks() {
    fetch(API_BASE + "/spider/risks", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var out = document.getElementById("risks-out");
        if (out) out.textContent = Array.isArray(j.items) && j.items.length ? j.items.join("\n") : "(无风控异常)";
      });
  }

  function loadLeads() {
    var kw = (document.getElementById("keyword") || {}).value || "";
    var st = (document.getElementById("status") || {}).value || "";
    var qs = "?keyword=" + encodeURIComponent(kw) + "&status=" + encodeURIComponent(st);
    api("/leads" + qs, { method: "GET" }).then(function (j) {
      var body = document.getElementById("leads-body");
      if (!body) return;
      if (!j || !Array.isArray(j.items) || j.items.length === 0) {
        body.innerHTML = '<tr><td colspan="5" class="empty">暂无线索</td></tr>';
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
          '<button class="btn btn-sm" data-requires-permission="btn.leads.approve" onclick="admin.approveLead(\'' + (item.opportunity_id || item.id || "") + '\')">通过</button> ' +
          '<button class="btn btn-sm btn-danger" data-requires-permission="btn.leads.reject" onclick="admin.rejectLead(\'' + (item.opportunity_id || item.id || "") + '\')">拒绝</button>' +
          '</td></tr>';
      }
      body.innerHTML = html;
      autoMask(body.parentNode);
      // 注意：按钮权限过滤在 bootstrap 之后触发，但因为这里动态更新了 DOM，必须在此处再次过滤
      applyPermission(document, window.__ADMIN_PERMISSIONS__ || []);
    });
  }
  function approveLead(id) {
    fetch(API_BASE + "/leads/" + id + "/approve", { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已通过"); loadLeads(); });
  }
  function rejectLead(id) {
    if (!confirm("拒绝后该商机将被加入黑名单，确认？")) return;
    fetch(API_BASE + "/leads/" + id + "/reject", {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded" },
      body: "reason=人工复核拒绝",
    }).then(function () { alert("已拒绝"); loadLeads(); });
  }
  function addBlacklist(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/leads/blacklist/add", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已加入"); loadBlacklist(); });
    return false;
  }
  function loadBlacklist() {
    fetch(API_BASE + "/leads/blacklist", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var body = document.getElementById("blacklist-body");
        if (!body) return;
        if (!Array.isArray(j.items) || j.items.length === 0) { body.textContent = "(无黑名单记录)"; return; }
        body.textContent = JSON.stringify(j.items, null, 2);
      });
  }

  function loadChannels() {
    fetch(API_BASE + "/channels", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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
                '<td data-sensitive="password">********</td>' +
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
        autoMask(wrap);
        applyPermission(wrap, window.__ADMIN_PERMISSIONS__ || []);
      });
  }
  function createAccount(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/channels/account", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("账号已保存（密码已加密）"); loadChannels(); });
    return false;
  }
  function banAccount(channel, id) {
    fetch(API_BASE + "/channels/" + channel + "/ban/" + id, { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已封禁"); loadChannels(); });
  }
  function unbanAccount(channel, id) {
    fetch(API_BASE + "/channels/" + channel + "/unban/" + id, { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已解封"); loadChannels(); });
  }

  function loadSales() {
    fetch(API_BASE + "/sales/persons", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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
            '<td data-sensitive="phone">' + maskPhone(p.phone || "") + '</td>' +
            '<td data-sensitive="email">' + maskEmail(p.email || "") + '</td></tr>';
        }
        body.innerHTML = html;
      });
    fetch(API_BASE + "/sales/assignments", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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
    fetch(API_BASE + "/sales/followups", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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
    fetch(API_BASE + "/sales/person", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已保存"); loadSales(); });
    return false;
  }
  function doAssign(e) {
    e.preventDefault();
    var body = new FormData(e.target);
    fetch(API_BASE + "/sales/assign", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已分配"); loadSales(); });
    return false;
  }
  function recordFollowup(e) {
    e.preventDefault();
    var body = new FormData(e.target);
    fetch(API_BASE + "/sales/followup", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function () { alert("已记录"); loadSales(); });
    return false;
  }
  function loadOverdue() {
    fetch(API_BASE + "/sales/overdue", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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

  // -------- 操作日志（增强版） --------
  var AUDIT_PAGE = 1;
  var AUDIT_PAGE_SIZE = 20;

  function loadAuditLogsEnhanced() {
    var f_role = (document.getElementById("f-role") || {}).value || "";
    var f_op = (document.getElementById("f-op") || {}).value || "";
    var f_kw = ((document.getElementById("f-keyword") || {}).value || "").trim();
    var query = "?page=" + AUDIT_PAGE + "&page_size=" + AUDIT_PAGE_SIZE +
      (f_role ? "&role=" + encodeURIComponent(f_role) : "") +
      (f_op ? "&op_type=" + encodeURIComponent(f_op) : "") +
      (f_kw ? "&keyword=" + encodeURIComponent(f_kw) : "");
    fetch(API_BASE + "/audit_enhanced/logs" + query, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var body = document.getElementById("audit-body");
        if (!body) {
          // 旧版本 audit_log 页面
          loadAuditLogs();
          return;
        }
        if (!j || !Array.isArray(j.items) || j.items.length === 0) {
          body.innerHTML = '<tr><td colspan="9" class="empty">无符合条件的记录</td></tr>';
        } else {
          var html = "";
          for (var i = 0; i < j.items.length; i++) {
            var a = j.items[i];
            var d = a.ts ? new Date(a.ts * 1000) : null;
            var dStr = d ? d.toLocaleString() : (a.ts || "-");
            html += '<tr><td>' + dStr + '</td>' +
              '<td>' + (a.username || "-") + '</td>' +
              '<td>' + (a.role ? '<span class="role-tag role-' + a.role + '">' + a.role + '</span>' : "-") + '</td>' +
              '<td>' + (a.ip || "-") + '</td>' +
              '<td>' + (a.operation_type || "-") + '</td>' +
              '<td>' + (a.path || a.action_detail || "-") + '</td>' +
              '<td>' + (a.status || "-") + '</td>' +
              '<td>' + (a.latency_ms || 0) + ' ms</td>' +
              '<td>' + (a.trace_id || "-") + '</td></tr>';
          }
          body.innerHTML = html;
        }
        var summary = document.getElementById("audit-summary");
        if (summary) {
          summary.textContent = "共 " + (j.total || 0) + " 条，页 " + AUDIT_PAGE;
        }
      });
  }
  function loadAuditLogs() {
    // 旧版兼容：保留原始 50 条读取
    var limit = parseInt(((document.getElementById("limit") || {}).value || "50"), 10) || 50;
    fetch(API_BASE + "/audit/logs?limit=" + limit, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
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

  function nextAuditPage() {
    AUDIT_PAGE += 1;
    loadAuditLogsEnhanced();
  }
  function prevAuditPage() {
    if (AUDIT_PAGE > 1) AUDIT_PAGE -= 1;
    loadAuditLogsEnhanced();
  }
  function exportAuditLogs() {
    var f_role = (document.getElementById("f-role") || {}).value || "";
    var f_op = (document.getElementById("f-op") || {}).value || "";
    var f_kw = ((document.getElementById("f-keyword") || {}).value || "").trim();
    var query = "?role=" + encodeURIComponent(f_role) +
      "&op_type=" + encodeURIComponent(f_op) +
      "&keyword=" + encodeURIComponent(f_kw);
    window.open(API_BASE + "/audit_enhanced/logs/export" + query, "_blank");
  }

  // -------- T19 · 采集管理增强（动态表单 + 任务详情 + 分页明细） --------
  // 各渠道专属表单字段（对齐底层爬虫接口配置）
  var CHANNEL_FORM_FIELDS = {
    generic_web: [
      { name: "url_template", label: "URL 模板（带 {page} 占位）", type: "text", placeholder: "https://example.com/list?page={page}" },
      { name: "site_type", label: "站点类型（bbs/news）", type: "text", placeholder: "bbs" },
      { name: "max_depth", label: "最大爬取深度", type: "number", placeholder: "3" },
      { name: "extract_rules", label: "抽取规则（JSON）", type: "textarea", placeholder: "{\"title\": \".post-title\"}" },
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "商机, 采购" },
      { name: "publish_days", label: "发布日期范围（天）", type: "number", placeholder: "30" },
      { name: "region", label: "地域", type: "text", placeholder: "全国" },
    ],
    short_video: [
      { name: "platform", label: "平台（douyin/kuaishou/bilibili）", type: "text", placeholder: "douyin" },
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "创业, 副业" },
      { name: "region", label: "地域", type: "text", placeholder: "北京" },
      { name: "publish_days", label: "发布日期范围（天）", type: "number", placeholder: "7" },
      { name: "min_likes", label: "最低点赞数", type: "number", placeholder: "1000" },
      { name: "min_comments", label: "最低评论数", type: "number", placeholder: "100" },
      { name: "min_views", label: "最低播放量", type: "number", placeholder: "10000" },
    ],
    xhs: [
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "探店, 美妆" },
      { name: "region", label: "地域", type: "text", placeholder: "上海" },
      { name: "publish_days", label: "发布日期范围（天）", type: "number", placeholder: "30" },
      { name: "post_type", label: "内容类型（note/video）", type: "text", placeholder: "note" },
      { name: "min_likes", label: "最低点赞数", type: "number", placeholder: "500" },
      { name: "min_comments", label: "最低评论数", type: "number", placeholder: "50" },
    ],
    qa_platform: [
      { name: "platform", label: "平台（zhihu/baidu-qa）", type: "text", placeholder: "zhihu" },
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "加盟, 开店" },
      { name: "publish_days", label: "发布日期范围（天）", type: "number", placeholder: "30" },
      { name: "min_answers", label: "最低回答数", type: "number", placeholder: "3" },
      { name: "min_views", label: "最低浏览量", type: "number", placeholder: "500" },
    ],
    b2b_supply: [
      { name: "platform", label: "平台（huangye88/1688）", type: "text", placeholder: "huangye88" },
      { name: "industry", label: "行业", type: "text", placeholder: "机械制造" },
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "供应商, 批发" },
      { name: "region", label: "地域", type: "text", placeholder: "江浙沪" },
      { name: "filter_price", label: "价格区间（low/mid/high）", type: "text", placeholder: "mid" },
    ],
    bidding: [
      { name: "bid_type", label: "公告类型（bid/win/change）", type: "text", placeholder: "bid" },
      { name: "industry", label: "行业", type: "text", placeholder: "建筑工程" },
      { name: "region", label: "地域", type: "text", placeholder: "广东" },
      { name: "keywords", label: "关键词（逗号分隔）", type: "text", placeholder: "采购, 招标" },
      { name: "publish_days", label: "发布日期范围（天）", type: "number", placeholder: "15" },
    ],
    company_biz: [
      { name: "company_keywords", label: "公司关键词（逗号分隔）", type: "text", placeholder: "科技, 贸易" },
      { name: "industry", label: "行业", type: "text", placeholder: "互联网" },
      { name: "region", label: "地域", type: "text", placeholder: "深圳" },
      { name: "registered_capital_min", label: "最低注册资本（万）", type: "number", placeholder: "100" },
      { name: "establishment_years", label: "成立年限（年）", type: "number", placeholder: "3" },
    ],
  };

  var CHANNEL_LABEL_MAP = {
    generic_web: "通用网页/论坛",
    short_video: "短视频",
    xhs: "小红书",
    qa_platform: "问答平台",
    b2b_supply: "供需 B2B",
    bidding: "招投标",
    company_biz: "企业工商",
  };

  // 根据选择的渠道动态渲染专属参数表单
  function renderChannelForm(channel) {
    var container = document.getElementById("channel-specific-fields");
    if (!container) return;
    container.innerHTML = "";
    var fields = CHANNEL_FORM_FIELDS[channel] || [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      var wrap = document.createElement("div");
      wrap.className = "field-row";
      var label = document.createElement("label");
      label.textContent = f.label;
      var input;
      if (f.type === "textarea") {
        input = document.createElement("textarea");
        input.rows = 3;
      } else {
        input = document.createElement("input");
        input.type = f.type || "text";
      }
      input.name = f.name;
      input.placeholder = f.placeholder || "";
      input.className = "text-input";
      wrap.appendChild(label);
      wrap.appendChild(input);
      container.appendChild(wrap);
    }
  }

  // 任务列表：支持按渠道/状态/关键字筛选
  function loadSpiderFiltered() {
    var channel = (document.getElementById("filter-channel") || {}).value || "";
    var status = (document.getElementById("filter-status") || {}).value || "";
    var keyword = (document.getElementById("filter-keyword") || {}).value || "";
    var url = "/spider/tasks?channel=" + encodeURIComponent(channel) +
              "&status=" + encodeURIComponent(status) +
              "&keyword=" + encodeURIComponent(keyword);
    api(url, { method: "GET" }).then(function (j) {
      if (!j) return;
      var body = document.getElementById("tasks-body");
      if (!body) return;
      if (!Array.isArray(j.items) || j.items.length === 0) {
        body.innerHTML = '<tr><td colspan="8" class="empty">暂无任务</td></tr>';
        return;
      }
      var html = "";
      for (var k = 0; k < j.items.length; k++) {
        var item = j.items[k];
        var ch = item.channel || "-";
        var chLabel = CHANNEL_LABEL_MAP[ch] || ch;
        var st = item.status || "READY";
        html += '<tr><td>' + (item.job_id || "") + '</td>' +
          '<td>' + chLabel + '</td>' +
          '<td>' + (item.task_name || item.spider_name || "") + '</td>' +
          '<td><span class="task-status ' + st + '">' + st + '</span></td>' +
          '<td>' + (item.success || 0) + '</td>' +
          '<td>' + (item.failed || 0) + '</td>' +
          '<td>' + (item.next_run || "-") + '</td>' +
          '<td>' +
          '<a href="/admin/spider/detail/' + (item.job_id || "") + '" class="btn btn-sm">详情</a> ' +
          '<button class="btn btn-sm" data-requires-permission="btn.spider.run" onclick="admin.runTask(\'' + (item.job_id || "") + '\')">启动</button> ' +
          '<button class="btn btn-sm" data-requires-permission="btn.spider.pause" onclick="admin.pauseTask(\'' + (item.job_id || "") + '\')">暂停</button> ' +
          '<button class="btn btn-sm" data-requires-permission="btn.spider.resume" onclick="admin.resumeTask(\'' + (item.job_id || "") + '\')">恢复</button> ' +
          '<button class="btn btn-sm" data-requires-permission="btn.spider.retry" onclick="admin.retryTask(\'' + (item.job_id || "") + '\')">重试</button> ' +
          '<button class="btn btn-sm" data-requires-permission="btn.spider.terminate" onclick="admin.terminateTask(\'' + (item.job_id || "") + '\')">终止</button> ' +
          '<button class="btn btn-sm btn-danger" data-requires-permission="btn.spider.delete" onclick="admin.deleteTask(\'' + (item.job_id || "") + '\')">删除</button>' +
          '</td></tr>';
      }
      body.innerHTML = html;
    });
  }

  // 任务详情页渲染（配置 + 进度 + 明细 + 日志）
  function loadSpiderDetail(jobId) {
    api("/spider/task/" + encodeURIComponent(jobId), { method: "GET" }).then(function (j) {
      if (!j || !j.job) { alert("任务不存在"); return; }
      var job = j.job;
      var ch = job.channel || "-";
      var chLabel = CHANNEL_LABEL_MAP[ch] || ch;
      var cfgEl = document.getElementById("detail-config");
      if (cfgEl) {
        var kvHtml = "";
        var keys = Object.keys(job);
        for (var i = 0; i < keys.length; i++) {
          var key = keys[i];
          var val = job[key];
          if (typeof val === "object") val = JSON.stringify(val);
          kvHtml += '<div class="kv"><div class="k">' + key + '</div><div class="v">' + (val != null ? String(val) : "-") + '</div></div>';
        }
        cfgEl.innerHTML = kvHtml;
      }
      // 进度统计
      var progressEl = document.getElementById("detail-progress");
      if (progressEl) {
        var success = parseInt(job.success || 0, 10);
        var failed = parseInt(job.failed || 0, 10);
        var risk = parseInt(job.risk_blocked || 0, 10);
        var max = parseInt(job.max_items || 0, 10) || (success + failed + risk + 1);
        var pct = Math.min(100, Math.round((success + failed + risk) * 100 / max));
        var st = job.status || "READY";
        progressEl.innerHTML =
          '<div class="progress-stats">' +
            '<div class="progress-item"><div class="label">状态</div><div class="value"><span class="task-status ' + st + '">' + st + '</span></div></div>' +
            '<div class="progress-item"><div class="label">采集成功</div><div class="value success">' + success + '</div></div>' +
            '<div class="progress-item"><div class="label">采集失败</div><div class="value failure">' + failed + '</div></div>' +
            '<div class="progress-item"><div class="label">风控拦截</div><div class="value warn">' + risk + '</div></div>' +
            '<div class="progress-item"><div class="label">进度</div><div class="value">' + pct + '%</div></div>' +
          '</div>' +
          '<div class="progress-bar"><div class="progress-inner" style="width:' + pct + '%"></div></div>';
      }
      // 日志按钮与分页明细
      loadTaskItems(jobId, 1, 20);
      refreshTaskLogs(jobId);
    });
  }

  function terminateTask(jobId) {
    if (!confirm("确认终止任务？此操作不可恢复。")) return;
    api("/spider/task/" + encodeURIComponent(jobId) + "/terminate", { method: "POST" }).then(function (j) {
      alert((j && j.msg) || "已终止");
      if (typeof loadSpiderFiltered === "function") loadSpiderFiltered();
    });
  }

  function retryTask(jobId) {
    if (!confirm("确认从上次中断位置重试任务？")) return;
    api("/spider/task/" + encodeURIComponent(jobId) + "/retry", { method: "POST" }).then(function (j) {
      alert((j && j.msg) || "已重试");
      if (typeof loadSpiderDetail === "function") {
        loadSpiderDetail(jobId);
      }
    });
  }

  function loadTaskItems(jobId, page, pageSize) {
    page = page || 1;
    pageSize = pageSize || 20;
    var url = "/spider/task/" + encodeURIComponent(jobId) + "/items?page=" + page + "&page_size=" + pageSize;
    api(url, { method: "GET" }).then(function (j) {
      var body = document.getElementById("items-body");
      if (!body) return;
      if (!j || !Array.isArray(j.items) || j.items.length === 0) {
        body.innerHTML = '<tr><td colspan="5" class="empty">暂无采集明细</td></tr>';
        document.getElementById("items-pagination").innerHTML = "";
        return;
      }
      var html = "";
      for (var k = 0; k < j.items.length; k++) {
        var it = j.items[k];
        html += '<tr>' +
          '<td>' + (it.id || "") + '</td>' +
          '<td><div class="content">' + (it.title || "") + '</div><div class="meta">' + (it.source || "") + '</div></td>' +
          '<td data-mask="author">' + (it.author || "") + '</td>' +
          '<td data-mask="phone">' + (it.phone || "") + '</td>' +
          '<td data-mask="email">' + (it.email || "") + '</td>' +
          '</tr>';
      }
      body.innerHTML = html;
      // 分页器
      var total = j.total || 0;
      var cur = j.page || 1;
      var size = j.page_size || 20;
      var totalPages = Math.max(1, Math.ceil(total / size));
      var pagEl = document.getElementById("items-pagination");
      if (pagEl) {
        pagEl.innerHTML =
          '共 ' + total + ' 条 · 第 ' + cur + ' / ' + totalPages + ' 页 ' +
          (cur > 1 ? '<button class="btn btn-sm" onclick="admin.loadTaskItems(\'' + jobId + '\',' + (cur - 1) + ',' + size + ')">上一页</button> ' : '') +
          (cur < totalPages ? '<button class="btn btn-sm" onclick="admin.loadTaskItems(\'' + jobId + '\',' + (cur + 1) + ',' + size + ')">下一页</button>' : '');
      }
      // 脱敏：使用原有 mask 函数
      try { autoMask(document.getElementById("items-body")); } catch (e) {}
    });
  }

  // 任务日志自动刷新
  var _taskLogTimer = null;
  function refreshTaskLogs(jobId) {
    if (_taskLogTimer) clearInterval(_taskLogTimer);
    var logsEl = document.getElementById("task-logs");
    if (!logsEl) return;
    function update() {
      api("/spider/task/" + encodeURIComponent(jobId) + "/logs?limit=100", { method: "GET" }).then(function (j) {
        if (!j || !Array.isArray(j.items)) return;
        var html = "";
        for (var i = 0; i < j.items.length; i++) {
          var line = String(j.items[i]);
          var cls = "log-info";
          if (/error|失败|ERR/i.test(line)) cls = "log-error";
          else if (/warn|风控|WARN/i.test(line)) cls = "log-warn";
          else if (/success|完成|SUCCESS/i.test(line)) cls = "log-success";
          html += '<div class="' + cls + '">' + line + '</div>';
        }
        logsEl.innerHTML = html || '<div class="log-warn">暂无日志</div>';
      });
    }
    update();
    _taskLogTimer = setInterval(update, 5000);
  }
  function stopTaskLogRefresh() {
    if (_taskLogTimer) { clearInterval(_taskLogTimer); _taskLogTimer = null; }
  }

  // -------- 账号管理（新 API） --------
  function loadAccounts() {
    fetch(API_BASE + "/accounts", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var body = document.getElementById("accounts-body");
        if (!body) return;
        var items = j.items || j.accounts || j.data || [];
        if (!items.length) {
          body.innerHTML = '<tr><td colspan="5" class="empty">暂无账号（从 .env 配置）</td></tr>';
          return;
        }
        var html = "";
        for (var i = 0; i < items.length; i++) {
          var a = items[i];
          html += '<tr>' +
            '<td>' + (a.username || "") + '</td>' +
            '<td><span class="role-tag role-' + (a.role || "ops") + '">' + (a.role || "-") + '</span></td>' +
            '<td>' + (a.disabled ? "禁用" : "启用") + '</td>' +
            '<td>' + (a.created_at ? (typeof a.created_at === "number" ? new Date(a.created_at * 1000).toLocaleString() : a.created_at) : "-") + '</td>' +
            '<td>' +
            '<button class="btn btn-sm" data-requires-permission="btn.system.reset_password" onclick="admin.resetAccountPassword(\'' + (a.username || "") + '\')">重置密码</button> ' +
            '<button class="btn btn-sm btn-danger" data-requires-permission="btn.system.accounts" onclick="admin.toggleAccountDisabled(\'' + (a.username || "") + '\',' + (!a.disabled) + ')">' +
            (a.disabled ? "启用" : "禁用") + '</button>' +
            '</td></tr>';
        }
        body.innerHTML = html;
        applyPermission(document, window.__ADMIN_PERMISSIONS__ || []);
      });
  }
  function createAdminAccount(e) {
    e.preventDefault();
    var form = e.target;
    var body = new FormData(form);
    fetch(API_BASE + "/accounts", { method: "POST", body: body, headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.code === 0) {
          alert("创建成功：\n账号：" + (j.username || "") +
            "\n角色：" + (j.role || "") +
            "\n初始密码：" + (j.password_plain || "(已脱敏)"));
          loadAccounts();
        } else {
          alert("创建失败：" + ((j && j.msg) || "未知错误"));
        }
      });
    return false;
  }
  function resetAccountPassword(username) {
    if (!confirm("确认重置账号 " + username + " 的密码？将生成一次性随机密码。")) return;
    fetch(API_BASE + "/accounts/" + encodeURIComponent(username) + "/reset_password", {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.code === 0) {
          alert("重置成功。\n新密码：" + (j.password_plain || "（已隐藏）") + "\n请立即登录修改。");
        } else {
          alert("重置失败：" + ((j && j.msg) || "未知错误"));
        }
      });
  }
  function toggleAccountDisabled(username, wantDisabled) {
    var verb = wantDisabled ? "禁用" : "启用";
    if (!confirm("确认" + verb + " 账号 " + username + "？")) return;
    var body = new FormData();
    body.set("disabled", wantDisabled ? "1" : "0");
    fetch(API_BASE + "/accounts/" + encodeURIComponent(username), {
      method: "PUT",
      body: body,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.code === 0) {
          loadAccounts();
        } else {
          alert(verb + "失败：" + ((j && j.msg) || "未知错误"));
        }
      });
  }

  // -------- 启动入口：bootstrap --------
  function bootstrap() {
    // 读取后端注入的 init JSON（新布局）
    var initEl = document.getElementById("admin-init-json");
    var init = null;
    if (initEl) {
      try { init = JSON.parse(initEl.textContent || "{}"); } catch (e) { init = {}; }
    } else {
      init = {};
    }

    var activeKey = init.activeKey;
    if (!activeKey) {
      // 旧布局 / 未注入：从 URL 推断
      var path = location.pathname;
      var m = path.match(/^\/admin\/([a-z_]+)/);
      activeKey = m ? m[1] : "dashboard";
    }
    var permissions = init.permissions || [];
    var menuGroups = init.menuGroups || [];
    window.__ADMIN_PERMISSIONS__ = permissions;

    // 1) 侧边栏 / 面包屑 / 顶栏
    renderSidebar(activeKey, menuGroups);
    renderBreadcrumb(activeKey, menuGroups);
    var searchEl = document.getElementById("global-search");
    if (searchEl) bindGlobalSearch(searchEl, menuGroups);

    // 2) 按钮 / 表单权限过滤
    applyPermission(document, permissions);

    // 3) 敏感字段自动脱敏（含已有业务页面的启发式识别）
    autoMask(document);

    // 4) 按 activeKey 做页面级数据加载
    switch (activeKey) {
      case "dashboard":    loadDashboard(); break;
      case "spider":       loadSpider(); break;
      case "leads":        loadLeads(); break;
      case "channels":     loadChannels(); break;
      case "sales":        loadSales(); break;
      case "audit_log":    loadAuditLogsEnhanced(); break;
      case "accounts":     loadAccounts(); break;
      default:             /* 空状态 / 403 页面 */ break;
    }
  }

  // -------- T20 合规审核相关前端函数 --------
  var _rejectTargetJobId = null;

  // 加载合规协议文本（任务创建页）
  function loadComplianceAgreementText() {
    var target = document.getElementById("compliance-agreement-text");
    if (!target) return;
    api.get("/compliance/agreement_text", function (data) {
      if (data && data.agreement_text) {
        target.textContent = data.agreement_text;
      }
    }, function (err) {
      target.textContent = "[Failed to load compliance agreement] " + String(err || "");
    });
  }

  // 加载待审核任务列表
  function loadPendingTasks() {
    api.get("/compliance/tasks/pending", function (data) {
      var tbody = document.getElementById("pending-tasks-body");
      if (!tbody) return;
      var items = data && data.items ? data.items : [];
      if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty">[OK] No pending approval tasks at this time</td></tr>';
        return;
      }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var t = items[i];
        var c = t.compliance || {};
        html += "<tr>"
          + "<td>" + escapeHtml(t.job_id || "") + "</td>"
          + "<td>" + escapeHtml(t.channel || "") + "</td>"
          + "<td>" + escapeHtml(t.task_name || "") + "</td>"
          + "<td>" + escapeHtml(t.submitted_by || "") + "</td>"
          + "<td>" + (t.submitted_at ? new Date(t.submitted_at * 1000).toLocaleString() : "-") + "</td>"
          + "<td>" + escapeHtml(c.data_purpose || "") + "</td>"
          + "<td>" + escapeHtml(c.retention_period || "") + "</td>"
          + '<td class="actions">'
          + '<a class="btn btn-sm btn-primary" data-requires-permission="btn.compliance.approve" href="javascript:admin.approveTask(\'' + t.job_id + '\')">Approve</a> '
          + '<a class="btn btn-sm btn-danger" data-requires-permission="btn.compliance.reject" href="javascript:admin.openRejectModal(\'' + t.job_id + '\')">Reject</a> '
          + '<a class="btn btn-sm" href="/admin/spider/' + t.job_id + '">View</a>'
          + "</td></tr>";
      }
      tbody.innerHTML = html;
      applyPermission();
    }, function (err) {
      var tbody = document.getElementById("pending-tasks-body");
      if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty">[ERROR] Failed to load: ' + escapeHtml(String(err || "")) + "</td></tr>";
    });
  }

  // 审核通过
  function approveTask(jobId) {
    if (!confirm("Confirm approval for task " + jobId + "? Once approved, the task status will change to READY and can be started.")) return;
    api.post("/compliance/task/" + encodeURIComponent(jobId) + "/approve", {}, function (data) {
      alert("Task approved: " + jobId);
      loadPendingTasks();
      loadApprovalHistory();
    }, function (err) { alert("Approval failed: " + String(err || "")); });
  }

  // 打开驳回弹窗
  function openRejectModal(jobId) {
    _rejectTargetJobId = jobId;
    var modal = document.getElementById("reject-modal");
    if (modal) {
      modal.style.display = "block";
      var ta = document.getElementById("reject-reason");
      if (ta) { ta.value = ""; ta.focus(); }
    }
  }

  // 关闭驳回弹窗
  function closeRejectModal() {
    var modal = document.getElementById("reject-modal");
    if (modal) modal.style.display = "none";
    _rejectTargetJobId = null;
  }

  // 提交驳回
  function submitReject() {
    var ta = document.getElementById("reject-reason");
    var reason = (ta && ta.value || "").trim();
    if (!reason) { alert("Rejection reason cannot be empty"); return; }
    if (!_rejectTargetJobId) { alert("No target task selected, please retry"); return; }
    var body = new FormData();
    body.append("reason", reason);
    api.post("/compliance/task/" + encodeURIComponent(_rejectTargetJobId) + "/reject", body, function (data) {
      alert("Task rejected successfully");
      closeRejectModal();
      loadPendingTasks();
      loadApprovalHistory();
    }, function (err) { alert("Rejection failed: " + String(err || "")); });
  }

  // 加载审核历史记录
  function loadApprovalHistory() {
    api.get("/compliance/tasks/history", function (data) {
      var tbody = document.getElementById("approval-history-body");
      if (!tbody) return;
      var items = data && data.items ? data.items : [];
      if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty">No audit record at this time</td></tr>';
        return;
      }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var rec = items[i];
        html += "<tr>"
          + "<td>" + escapeHtml(rec.job_id || "") + "</td>"
          + "<td>" + escapeHtml(rec.task_name || "") + "</td>"
          + "<td>" + escapeHtml(rec.channel || "") + "</td>"
          + "<td>" + escapeHtml(rec.submitted_by || "") + "</td>"
          + "<td>" + escapeHtml(rec.reviewed_by || "") + "</td>"
          + "<td>" + (rec.reviewed_at ? new Date(rec.reviewed_at * 1000).toLocaleString() : "-") + "</td>"
          + '<td><span class="status status-' + (rec.decision || "UNKNOWN").toLowerCase() + '">' + escapeHtml(rec.decision || "-") + '</span></td>'
          + "<td>" + escapeHtml(rec.reject_reason || "-") + "</td>"
          + "</tr>";
      }
      tbody.innerHTML = html;
    }, function (err) {
      var tbody = document.getElementById("approval-history-body");
      if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty">[ERROR] Failed to load history: ' + escapeHtml(String(err || "")) + "</td></tr>";
    });
  }

  // 加载合规配置页（渠道规则、协议文本、留存选项、关键词）
  function loadComplianceConfigPage() {
    api.get("/compliance/config", function (data) {
      // 1. 渠道审批规则
      var rulesBody = document.getElementById("channel-rules-body");
      if (rulesBody && data.channel_rules) {
        var html = "";
        var keys = Object.keys(data.channel_rules);
        for (var i = 0; i < keys.length; i++) {
          var ch = keys[i];
          var rule = data.channel_rules[ch] || {};
          var checked = rule.need_approval ? "checked" : "";
          html += "<tr>"
            + "<td>" + escapeHtml(ch) + "</td>"
            + '<td><input type="text" value="' + escapeHtml(rule.risk_level || "") + '" data-channel="' + escapeHtml(ch) + '" data-field="risk_level" class="channel-rule-input" style="width:100%;"/></td>'
            + '<td style="text-align:center;"><input type="checkbox" data-channel="' + escapeHtml(ch) + '" data-field="need_approval" class="channel-rule-checkbox" ' + checked + '/></td>'
            + '<td><button class="btn btn-sm btn-primary" data-channel="' + escapeHtml(ch) + '" onclick="admin.saveChannelRule(\'' + escapeHtml(ch) + '\')" data-requires-permission="btn.compliance.config">Save</button></td>'
            + "</tr>";
        }
        rulesBody.innerHTML = html;
        applyPermission();
      }
      // 2. 合规协议文本
      var ag = document.getElementById("agreement-text-edit");
      if (ag) ag.value = data.agreement_text || "";
      // 3. 留存周期选项
      var rt = document.getElementById("retention-options-edit");
      if (rt) rt.value = (data.retention_options && data.retention_options.join ? data.retention_options.join(",") : "30d,90d,180d,1y");
      // 4. 违规关键词
      var kw = document.getElementById("forbidden-keywords-edit");
      if (kw) kw.value = (data.forbidden_keywords && data.forbidden_keywords.join ? data.forbidden_keywords.join(",") : "phone,email,id card");
    }, function (err) {
      alert("Failed to load compliance config: " + String(err || ""));
    });
  }

  // 保存单个渠道规则
  function saveChannelRule(channel) {
    var inputs = document.querySelectorAll(".channel-rule-input[data-channel='" + channel + "']");
    var checkbox = document.querySelector(".channel-rule-checkbox[data-channel='" + channel + "']");
    var risk_level = "";
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].getAttribute("data-field") === "risk_level") risk_level = inputs[i].value.trim();
    }
    if (!risk_level) risk_level = "MEDIUM";
    var need_approval = checkbox && checkbox.checked ? "true" : "false";
    var body = new FormData();
    body.append("channel", channel);
    body.append("risk_level", risk_level);
    body.append("need_approval", need_approval);
    api.post("/compliance/config/channel_rules", body, function (data) {
      alert("Channel rule saved: " + channel);
    }, function (err) { alert("Failed to save: " + String(err || "")); });
  }

  // 保存协议文本
  function saveAgreementText() {
    var ta = document.getElementById("agreement-text-edit");
    if (!ta) return;
    var body = new FormData();
    body.append("text", ta.value || "");
    api.post("/compliance/config/agreement_text", body, function (data) { alert("Compliance agreement saved"); },
      function (err) { alert("Failed to save: " + String(err || "")); });
  }

  // 保存留存周期选项
  function saveRetentionOptions() {
    var inp = document.getElementById("retention-options-edit");
    if (!inp) return;
    var body = new FormData();
    body.append("options", inp.value || "");
    api.post("/compliance/config/retention_options", body, function (data) { alert("Retention options saved"); },
      function (err) { alert("Failed to save: " + String(err || "")); });
  }

  // 保存违规关键词
  function saveForbiddenKeywords() {
    var ta = document.getElementById("forbidden-keywords-edit");
    if (!ta) return;
    var body = new FormData();
    body.append("keywords", ta.value || "");
    api.post("/compliance/config/forbidden_keywords", body, function (data) { alert("Forbidden keyword list saved"); },
      function (err) { alert("Failed to save: " + String(err || "")); });
  }

  // 通知中心：加载通知列表
  function loadNotificationsList() {
    api.get("/compliance/notifications", function (data) {
      var tbody = document.getElementById("notifications-body");
      if (!tbody) return;
      var items = data && data.items ? data.items : [];
      if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty">[OK] No notifications</td></tr>';
        return;
      }
      var html = "";
      for (var i = 0; i < items.length; i++) {
        var n = items[i];
        var status = n.read ? "READ" : "UNREAD";
        var link = n.link ? '<a class="btn btn-sm" href="' + escapeHtml(n.link) + '">View</a>' : "";
        html += "<tr>"
          + "<td>" + (n.created_at ? new Date(n.created_at * 1000).toLocaleString() : "-") + "</td>"
          + "<td>" + escapeHtml(n.type || "") + "</td>"
          + "<td>" + escapeHtml(n.title || "") + "</td>"
          + "<td>" + escapeHtml(n.content || "") + "</td>"
          + '<td><span class="status status-' + status.toLowerCase() + '">' + status + "</span></td>"
          + "<td>" + link + "</td>"
          + "</tr>";
      }
      tbody.innerHTML = html;
    }, function (err) {
      var tbody = document.getElementById("notifications-body");
      if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="empty">[ERROR] Failed to load: ' + escapeHtml(String(err || "")) + "</td></tr>";
    });
  }

  // 通知中心：标记全部已读
  function markAllNotificationsRead() {
    api.post("/compliance/notifications/read_all", {}, function (data) {
      alert("All notifications marked as read");
      loadNotificationsList();
    }, function (err) { alert("Operation failed: " + String(err || "")); });
  }

  // -------- 导出到全局命名空间 --------
  window.admin = {
    ui: {
      bootstrap: bootstrap,
      autoMask: autoMask,
      applyPermission: applyPermission,
      renderSidebar: renderSidebar,
      renderBreadcrumb: renderBreadcrumb,
      bindGlobalSearch: bindGlobalSearch,
      maskPhone: maskPhone,
      maskEmail: maskEmail,
      maskWechat: maskWechat,
      maskSecret: maskSecret,
      maskPassword: maskPassword,
    },

    api: api,

    // 业务功能（保留向后兼容的函数签名）
    createSpiderTask: createSpiderTask,
    runTask: runTask,
    pauseTask: pauseTask,
    resumeTask: resumeTask,
    deleteTask: deleteTask,
    loadSpiderLogs: loadSpiderLogs,
    loadRisks: loadRisks,
    loadLeads: loadLeads,
    approveLead: approveLead,
    rejectLead: rejectLead,
    addBlacklist: addBlacklist,
    loadBlacklist: loadBlacklist,
    loadChannels: loadChannels,
    createAccount: createAccount,
    banAccount: banAccount,
    unbanAccount: unbanAccount,
    loadSales: loadSales,
    upsertPerson: upsertPerson,
    doAssign: doAssign,
    recordFollowup: recordFollowup,
    loadOverdue: loadOverdue,

    // 审计
    loadAuditLogs: loadAuditLogs,
    loadAuditLogsEnhanced: loadAuditLogsEnhanced,
    nextAuditPage: nextAuditPage,
    prevAuditPage: prevAuditPage,
    exportAuditLogs: exportAuditLogs,

    // T19 采集管理增强
    renderChannelForm: renderChannelForm,
    loadSpiderFiltered: loadSpiderFiltered,
    loadSpiderDetail: loadSpiderDetail,
    terminateTask: terminateTask,
    retryTask: retryTask,
    loadTaskItems: loadTaskItems,
    refreshTaskLogs: refreshTaskLogs,
    stopTaskLogRefresh: stopTaskLogRefresh,

    // 账号管理
    loadAccounts: loadAccounts,
    createAdminAccount: createAdminAccount,
    resetAccountPassword: resetAccountPassword,
    toggleAccountDisabled: toggleAccountDisabled,

    // T20 合规审核
    loadComplianceAgreementText: loadComplianceAgreementText,
    loadPendingTasks: loadPendingTasks,
    approveTask: approveTask,
    openRejectModal: openRejectModal,
    closeRejectModal: closeRejectModal,
    submitReject: submitReject,
    loadApprovalHistory: loadApprovalHistory,
    loadComplianceConfigPage: loadComplianceConfigPage,
    saveChannelRule: saveChannelRule,
    saveAgreementText: saveAgreementText,
    saveRetentionOptions: saveRetentionOptions,
    saveForbiddenKeywords: saveForbiddenKeywords,

    // T20 通知中心
    loadNotificationsList: loadNotificationsList,
    markAllNotificationsRead: markAllNotificationsRead,
  };

  // 页面就绪后自动 bootstrap
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})();
