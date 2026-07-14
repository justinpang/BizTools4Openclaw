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

    // 同步填充方案选择下拉框（执行详情区块使用）
    var planSelect = document.getElementById("crawl-detail-plan-select");
    if (planSelect && items && items.length > 0) {
      var existing = planSelect.value;
      var optsHtml = ['<option value="">-- 选择方案查看执行详情 --</option>'];
      for (var i = 0; i < items.length; i++) {
        var p = items[i];
        var pid = typeof p.id === "number" ? p.id : (p.id ? String(p.id) : "");
        var label = (p.plan_name || "(未命名)") + " [ID: " + pid + "]";
        optsHtml.push('<option value="' + pid + '">' + label + '</option>');
      }
      planSelect.innerHTML = optsHtml.join("");
      if (existing) planSelect.value = existing;
    }

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
      actions.push('<a href="javascript:crawlPlans.showSteps(' + p.id + ')" style="margin-right:8px;color:#1967d2;">步骤详情</a>');
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
      showMessage("正在获取方案配置...");
      api("/api/admin/crawl/steps/plan?plan_id=" + planId, "GET").then(function (planData) {
        if (!planData || planData.code !== 0) {
          showMessage("获取方案配置失败", true);
          return;
        }
        var steps = (planData.data && planData.data.steps) || [];
        var rpStep = steps.find(function(s) { return s.step_type === "result_preview"; });
        var maxItems = rpStep ? rpStep.config && rpStep.config.preview_count : null;
        
        showMessage("正在执行...请稍候");
        var payload = {};
        if (maxItems) {
          payload.max_items = maxItems;
        }
        api("/api/admin/crawl/plans/" + planId + "/run", "POST", payload).then(function (data) {
          if (data && data.code === 0) {
            var items = (data.data && data.data.items_written) || 0;
            showMessage("执行完成，写入 " + items + " 条");
          } else {
            showMessage("执行失败：" + ((data && data.msg) || ""), true);
          }
        });
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
    // ---------- 删除单条运行记录 ----------
    deleteRun: function (planId, runId) {
      confirmThen("⚠ 确定删除该运行记录？此操作不可恢复。", function () {
        api("/api/admin/crawl/runs/" + runId, "DELETE").then(function (data) {
          if (data && data.code === 0) {
            showMessage("运行记录已删除");
            // 重新加载列表
            var planSelect = document.getElementById("crawl-detail-plan-select");
            if (planSelect && planSelect.value == planId) {
              crawlPlans.loadPlanDetail();
            }
          }
          else showMessage("删除失败: " + (data.msg || "未知错误"), true);
        });
      });
    },
    // ---------- 执行详情：折叠/展开 ----------
    toggleDetail: function () {
      var content = document.getElementById("crawl-detail-content");
      var icon = document.getElementById("crawl-detail-toggle-icon");
      if (!content) return;
      if (content.style.display === "none") {
        content.style.display = "block";
        if (icon) icon.textContent = "▼";
      } else {
        content.style.display = "none";
        if (icon) icon.textContent = "▶";
      }
    },
    // ---------- 执行详情：加载选定方案的最近运行列表（倒序） ----------
    loadPlanDetail: function () {
      var planSelect = document.getElementById("crawl-detail-plan-select");
      var planId = planSelect ? planSelect.value : "";
      if (!planId) {
        showMessage("请先选择方案", true);
        return;
      }
      var listContainer = document.getElementById("crawl-detail-run-list");
      var detailContainer = document.getElementById("crawl-detail-run-detail");
      if (!listContainer) return;
      listContainer.innerHTML = '<div style="color:#888;padding:10px;text-align:center;">加载中...</div>';
      if (detailContainer) {
        detailContainer.innerHTML = '<div class="muted" style="font-size:12px;text-align:center;padding:40px;">加载运行记录中...</div>';
      }

      api("/api/admin/crawl/recent-runs?plan_id=" + planId + "&page_size=20").then(function (data) {
        if (!data || data.code !== 0 || !data.data) {
          listContainer.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败：' + (data.msg || "未知错误") + '</div>';
          if (detailContainer) {
            detailContainer.innerHTML = '<div class="muted" style="font-size:12px;text-align:center;padding:40px;">加载失败</div>';
          }
          return;
        }
        var runs = (data.data.runs || []);
        if (runs.length === 0) {
          listContainer.innerHTML = '<div style="color:#888;padding:20px;text-align:center;font-size:12px;">该方案暂无运行记录。<br>可点击"立即执行"开始测试。</div>';
          if (detailContainer) {
            detailContainer.innerHTML = '<div class="muted" style="font-size:12px;text-align:center;padding:40px;">暂无运行记录</div>';
          }
          return;
        }

        var html = [];
        html.push('<div style="font-size:12px;color:#666;margin-bottom:8px;">共 ' + (data.data.total || 0) + ' 次运行（倒序）</div>');
        for (var ri = 0; ri < runs.length; ri++) {
          var run = runs[ri];
          var runId = run.id || run.run_id;
          var statusColor = run.status === "completed" ? "#52c41a" : (run.status === "failed" ? "#f5222d" : "#fa8c16");
          var statusLabel = run.status === "completed" ? "成功" : (run.status === "failed" ? "失败" : (run.status === "running" ? "运行中" : run.status));
          var hasSteps = (run.steps && run.steps.length > 0);
          html.push(
            '<div style="position:relative;padding:8px 10px;margin-bottom:6px;border:1px solid #e8ecf0;border-radius:4px;background:#fff;' +
            'hover:background:#e8f0fe;transition:background 0.2s;" ' +
            'onmouseover="this.style.background=\'#e8f0fe\';this.style.borderColor=\'#1967d2\';" ' +
            'onmouseout="this.style.background=\'#fff\';this.style.borderColor=\'#e8ecf0\';">' +
            '  <div onclick="crawlPlans.showRunDetail(' + planId + ', ' + runId + ')" style="cursor:pointer;">' +
            '    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
            '      <span style="font-weight:bold;font-size:13px;">Run #' + runId + '</span>' +
            '      <span style="color:' + statusColor + ';font-size:12px;font-weight:bold;">' + statusLabel + '</span>' +
            '    </div>' +
            '    <div style="font-size:11px;color:#666;">' + (run.started_at || run.created_at || "").substring(0, 19) + '</div>' +
            '    <div style="font-size:11px;color:#888;margin-top:2px;">' +
            '      ' + (run.items_success || run.items_written || 0) + '/' + (run.items_total || 0) + ' 条 | ' +
            '      ' + (run.duration_ms || 0) + 'ms ' +
            (hasSteps ? '<span style="color:#1967d2;">(' + run.steps.length + '步)</span>' : '<span style="color:#999;">(无步骤)</span>') +
            '    </div>' +
            '  </div>' +
            '  <div style="text-align:right;margin-top:4px;padding-top:4px;border-top:1px dashed #e8ecf0;">' +
            '    <a href="javascript:void(0)" onclick="event.stopPropagation();crawlPlans.deleteRun(' + planId + ', ' + runId + ')" ' +
            'style="font-size:11px;color:#f5222d;text-decoration:none;">🗑 删除</a>' +
            '  </div>' +
            '</div>'
          );
        }
        listContainer.innerHTML = html.join("");

        if (detailContainer) {
          detailContainer.innerHTML = '<div class="muted" style="font-size:12px;text-align:center;padding:40px;">点击左侧运行记录查看步骤详情</div>';
        }
      }).catch(function (err) {
        listContainer.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败: ' + err + '</div>';
        if (detailContainer) {
          detailContainer.innerHTML = '<div class="muted" style="font-size:12px;text-align:center;padding:40px;">加载失败</div>';
        }
      });
    },
    // ---------- 显示单次运行的步骤详情 ----------
    showRunDetail: function (planId, runId) {
      var detailContainer = document.getElementById("crawl-detail-run-detail");
      if (!detailContainer) return;
      detailContainer.innerHTML = '<div style="color:#888;padding:20px;text-align:center;">加载中...</div>';

      api("/api/admin/crawl/steps?plan_id=" + planId + "&run_id=" + runId).then(function (data) {
        if (!data || data.code !== 0 || !data.data) {
          detailContainer.innerHTML = '<div style="color:#f5222d;padding:20px;">加载失败：' + (data.msg || "未知错误") + '</div>';
          return;
        }
        var steps = (data.data.steps || []);
        var total = data.data.total || 0;

        var html = [];
        html.push('<div style="margin-bottom:12px;">');
        html.push('<div style="font-weight:bold;color:#333;font-size:14px;">Run #' + runId + ' 步骤详情</div>');
        html.push('<div style="font-size:12px;color:#666;margin-top:2px;">共 ' + total + ' 个步骤</div>');
        html.push('</div>');

        if (steps.length === 0) {
          html.push('<div style="padding:30px;text-align:center;background:#f7f9fc;border-radius:6px;">');
          html.push('<div style="font-size:13px;color:#888;margin-bottom:8px;">本次运行无步骤级详情。</div>');
          html.push('<div style="font-size:12px;color:#aaa;">可能原因：</div>');
          html.push('<ul style="font-size:12px;color:#aaa;text-align:left;margin-left:20px;">');
          html.push('<li>方案配置中"保存步骤级中间结果"未启用</li>');
          html.push('<li>运行在步骤记录功能上线前执行</li>');
          html.push('<li>运行过程中异常终止</li>');
          html.push('</ul>');
          html.push('</div>');
        } else {
          html.push('<table class="data-table" style="width:100%;border-collapse:collapse;font-size:12px;">');
          html.push(
            '<thead><tr style="background:#f5f7fa;">' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">序号</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;">步骤名称</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:80px;">类型</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">状态</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">输入数</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">输出数</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:80px;">耗时(ms)</th>' +
            '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;">输入/输出详情</th>' +
            '</tr></thead><tbody>'
          );
          for (var si = 0; si < steps.length; si++) {
            var st = steps[si];
            var sColor = st.status === "success" ? "#52c41a" : (st.status === "failed" ? "#f5222d" : (st.status === "skipped" ? "#888" : "#1890ff"));
            var sLabel = st.status === "success" ? "成功" : (st.status === "failed" ? "失败" : (st.status === "skipped" ? "跳过" : (st.status || "运行中")));
            var inputSummary = "—";
            try {
              if (st.input_json && typeof st.input_json === "object") {
                inputSummary = JSON.stringify(st.input_json);
              } else if (st.input_json) {
                inputSummary = String(st.input_json);
              }
            } catch (e) { inputSummary = "—"; }
            var outputSummary = "—";
            try {
              if (st.output_json && typeof st.output_json === "object") {
                outputSummary = JSON.stringify(st.output_json);
              } else if (st.output_json) {
                outputSummary = String(st.output_json);
              }
            } catch (e) { outputSummary = "—"; }
            html.push(
              '<tr style="background:' + (si % 2 === 0 ? '#fff' : '#fafbfc') + ';">' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;font-weight:bold;color:#666;">' + (st.step_index || (si + 1)) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;font-weight:bold;">' + (st.step_name || "步骤 " + (si + 1)) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.step_type || "-") + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;"><span style="color:' + sColor + ';font-weight:bold;">' + sLabel + '</span></td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.items_in || 0) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.items_out || 0) + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.duration_ms || "-") + '</td>' +
              '<td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:11px;color:#555;">' +
              '  <div style="background:#f7f9fc;padding:6px;border-radius:4px;">' +
              '    <div style="margin-bottom:3px;"><b>输入:</b> <span style="color:#1967d2;">' + inputSummary + '</span></div>' +
              '    <div style="margin-bottom:3px;"><b>输出:</b> <span style="color:#52c41a;">' + outputSummary + '</span></div>' +
              (st.error_message ? '<div style="color:#f5222d;"><b>错误:</b> ' + st.error_message + '</div>' : "") +
              '  </div>' +
              '</td>' +
              '</tr>'
            );
          }
          html.push("</tbody></table>");
        }
        detailContainer.innerHTML = html.join("");
      }).catch(function (err) {
        detailContainer.innerHTML = '<div style="color:#f5222d;padding:20px;">加载失败: ' + err + '</div>';
      });
    },
    // ---------- 步骤详情快捷按钮 ----------
    showSteps: function (planId) {
      // 展开执行详情区块，选择该方案并加载
      var content = document.getElementById("crawl-detail-content");
      var icon = document.getElementById("crawl-detail-toggle-icon");
      if (content && content.style.display === "none") {
        content.style.display = "block";
        if (icon) icon.textContent = "▼";
      }
      var planSelect = document.getElementById("crawl-detail-plan-select");
      if (planSelect) { planSelect.value = String(planId); }
      window.crawlPlans.loadPlanDetail();
    },
  };

  // 自动启动
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPlans);
  } else {
    loadPlans();
  }
})();
