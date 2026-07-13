/* =========================================================================
 * crawl_plans.js — 采集方案管理列表页
 *   渲染方案表格、操作按钮（编辑/克隆/启停/测试/删除/导出）
 *   API: /api/admin/crawl/plans  （由 web_admin/api/crawl_config.py 提供）
 * ========================================================================= */
(function () {
  "use strict";

  // -------- 安全 API 调用（复用 admin.safeApi 或 fallback 到 fetch） --------
  function api(path, method, body) {
    var opts = {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body && method && method !== "GET") {
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  // -------- 状态样式 --------
  var STATUS_STYLE = {
    draft:    { badge: "background:#eee;color:#666;border-radius:4px;padding:2px 8px;font-size:12px;", label: "草稿" },
    active:   { badge: "background:#e6f7ff;color:#1890ff;border-radius:4px;padding:2px 8px;font-size:12px;", label: "运行中" },
    paused:   { badge: "background:#fff7e6;color:#fa8c16;border-radius:4px;padding:2px 8px;font-size:12px;", label: "已暂停" },
    deleted:  { badge: "background:#fff1f0;color:#f5222d;border-radius:4px;padding:2px 8px;font-size:12px;", label: "已删除" },
  };

  function statusBadge(status) {
    var s = STATUS_STYLE[status] || STATUS_STYLE.draft;
    return '<span style="' + s.badge + '">' + s.label + '</span>';
  }

  // -------- 表格渲染 --------
  function renderTable(items) {
    var container = document.getElementById("crawl-plans-container");
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML = (
        '<div style="padding:40px;text-align:center;color:#999;">' +
        '暂无采集方案。点击「+ 新建方案」或「批量导入」开始配置。' +
        '</div>'
      );
      return;
    }

    var html = [];
    html.push(
      '<table class="data-table" style="width:100%;border-collapse:collapse;">' +
      '  <thead><tr style="background:#f5f7fa;">' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">方案名称</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">目标域名</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">类型</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">状态</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">采集次数</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">累计条目</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">创建人</th>' +
      '    <th style="padding:10px;text-align:left;border-bottom:1px solid #e8ecf0;">操作</th>' +
      '  </tr></thead><tbody>'
    );

    for (var i = 0; i < items.length; i++) {
      var p = items[i];
      var rowStyle = (i % 2 === 0) ? "background:white;" : "background:#fafbfc;";
      var actions = [];
      actions.push('<a href="/admin/crawl/steps-editor?plan_id=' + p.id + '" style="margin-right:8px;">编辑</a>');
      actions.push('<a href="javascript:crawlPlans.clone(' + p.id + ')" style="margin-right:8px;">克隆</a>');
      actions.push('<a href="javascript:crawlPlans.test(' + p.id + ')" style="margin-right:8px;">测试</a>');
      if (p.status === "active") {
        actions.push('<a href="javascript:crawlPlans.disable(' + p.id + ')" style="margin-right:8px;color:#fa8c16;">停用</a>');
      } else if (p.status !== "deleted") {
        actions.push('<a href="javascript:crawlPlans.enable(' + p.id + ')" style="margin-right:8px;color:#52c41a;">启用</a>');
      }
      actions.push('<a href="javascript:crawlPlans.runNow(' + p.id + ')" style="margin-right:8px;">立即执行</a>');
      actions.push('<a href="javascript:crawlPlans.export(' + p.id + ')" style="margin-right:8px;">导出</a>');
      if (p.status !== "deleted") {
        actions.push('<a href="javascript:crawlPlans.delete(' + p.id + ')" style="color:#f5222d;">删除</a>');
      }

      html.push(
        '<tr style="' + rowStyle + '">' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;">' +
        '    <div style="font-weight:bold;">' + (p.plan_name || "(未命名)") + '</div>' +
        '    <div style="font-size:11px;color:#999;">ID: ' + p.id + ' | ver: ' + (p.current_version || 1) + '</div>' +
        '  </td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (p.target_domain || "-") + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (p.spider_type || "-") + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;">' + statusBadge(p.status) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (p.run_count_total || 0) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (p.items_total || 0) + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (p.created_by || "-") + '</td>' +
        '  <td style="padding:10px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + actions.join("") + '</td>' +
        '</tr>'
      );
    }
    html.push("</tbody></table>");
    container.innerHTML = html.join("");
  }

  // -------- 加载方案列表 --------
  function loadPlans() {
    var keyword = (document.getElementById("crawl-keyword") || {}).value || "";
    var status = (document.getElementById("crawl-status") || {}).value || "";
    var url = "/api/admin/crawl/plans?page=1&page_size=50";
    if (keyword) url += "&keyword=" + encodeURIComponent(keyword);
    if (status) url += "&status=" + encodeURIComponent(status);

    var container = document.getElementById("crawl-plans-container");
    if (container) container.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">加载中...</div>';

    api(url).then(function (data) {
      var items = (data && data.data && data.data.items) || (data && data.items) || [];
      renderTable(items);
    }).catch(function (err) {
      if (container) container.innerHTML = '<div style="padding:20px;color:#f5222d;">加载失败: ' + err + '</div>';
    });
  }

  // -------- 操作 --------
  function confirmThen(msg, action) {
    if (window.confirm(msg)) action();
  }

  function showMessage(text, isError) {
    var div = document.createElement("div");
    div.style.cssText = [
      "position:fixed", "top:20px", "right:20px", "padding:12px 20px",
      "background:" + (isError ? "#fff1f0" : "#f6ffed"),
      "color:" + (isError ? "#f5222d" : "#52c41a"),
      "border:1px solid " + (isError ? "#ffa39e" : "#b7eb8f"),
      "border-radius:6px", "z-index:9999", "box-shadow:0 2px 8px rgba(0,0,0,0.15)",
      "font-size:14px",
    ].join(";");
    div.textContent = text;
    document.body.appendChild(div);
    setTimeout(function () { document.body.removeChild(div); }, 3000);
  }

  // -------- 暴露到全局 --------
  window.crawlPlans = {
    load: loadPlans,
    refresh: loadPlans,
    openEditor: function () {
      window.location.href = "/admin/crawl/steps-editor";
    },
    openImport: function () {
      var raw = window.prompt("粘贴 JSON 配置（导出的方案内容）：");
      if (!raw) return;
      var config;
      try {
        config = JSON.parse(raw);
      } catch (e) {
        showMessage("JSON 格式错误：" + e.message, true);
        return;
      }
      api("/api/admin/crawl/plans/import", "POST", config).then(function (data) {
        if (data && data.code === 0) {
          showMessage("导入成功！");
          loadPlans();
        } else {
          showMessage("导入失败：" + ((data && data.msg) || "未知错误"), true);
        }
      });
    },
    test: function (planId) {
      api("/api/admin/crawl/plans/" + planId + "/test", "POST", {}).then(function (data) {
        if (data && data.code === 0) {
          var items = (data.data && data.data.items) || [];
          showMessage("测试完成，采集到 " + items.length + " 条");
          if (items.length > 0) {
            var txt = "预览前 3 条：\n\n" + JSON.stringify(items.slice(0, 3), null, 2);
            window.alert(txt.substring(0, 500));
          }
        } else {
          showMessage("测试失败：" + ((data && data.msg) || "无数据"), true);
        }
      });
    },
    clone: function (planId) {
      confirmThen("确定克隆该方案？", function () {
        api("/api/admin/crawl/plans/" + planId + "/clone", "POST", {}).then(function (data) {
          if (data && data.code === 0) {
            showMessage("克隆成功！");
            loadPlans();
          } else {
            showMessage("克隆失败", true);
          }
        });
      });
    },
    enable: function (planId) {
      api("/api/admin/crawl/plans/" + planId + "/enable", "POST", {}).then(function (data) {
        if (data && data.code === 0) { showMessage("已启用"); loadPlans(); }
        else showMessage("启用失败", true);
      });
    },
    disable: function (planId) {
      api("/api/admin/crawl/plans/" + planId + "/disable", "POST", {}).then(function (data) {
        if (data && data.code === 0) { showMessage("已停用"); loadPlans(); }
        else showMessage("停用失败", true);
      });
    },
    runNow: function (planId) {
      showMessage("正在执行...请稍候");
      api("/api/admin/crawl/plans/" + planId + "/run", "POST", {}).then(function (data) {
        if (data && data.code === 0) {
          var items = (data.data && data.data.items_written) || 0;
          showMessage("执行完成，写入 " + items + " 条");
        } else {
          showMessage("执行失败：" + ((data && data.msg) || ""), true);
        }
      });
    },
    export: function (planId) {
      api("/api/admin/crawl/plans/" + planId + "/export").then(function (data) {
        if (data && data.code === 0 && data.data) {
          var jsonStr = JSON.stringify(data.data, null, 2);
          var blob = new Blob([jsonStr], { type: "application/json" });
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = "crawl_plan_" + planId + ".json";
          a.click();
          URL.revokeObjectURL(url);
          showMessage("已导出");
        } else {
          showMessage("导出失败", true);
        }
      });
    },
    delete: function (planId) {
      confirmThen("⚠ 确定删除该方案？所有运行记录保留，但方案将被标记为已删除。", function () {
        api("/api/admin/crawl/plans/" + planId, "DELETE").then(function (data) {
          if (data && data.code === 0) { showMessage("已删除"); loadPlans(); }
          else showMessage("删除失败", true);
        });
      });
    },
  };

  // 自动启动
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPlans);
  } else {
    loadPlans();
  }
})();
