(function () {
  "use strict";

  var state = {
    currentPlanId: null,
    currentPlan: null,
    currentRunId: null,
    currentTab: "runs",
  };

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

  function confirmThen(msg, action) {
    if (window.confirm(msg)) action();
  }

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

  function runStatusBadge(status) {
    var colors = {
      completed: { bg: "#f6ffed", color: "#52c41a", label: "成功" },
      failed:    { bg: "#fff1f0", color: "#f5222d", label: "失败" },
      running:   { bg: "#e6f7ff", color: "#1890ff", label: "运行中" },
      pending:   { bg: "#fff7e6", color: "#fa8c16", label: "等待中" },
    };
    var s = colors[status] || { bg: "#f5f5f5", color: "#666", label: status || "未知" };
    return '<span style="background:' + s.bg + ';color:' + s.color + ';border-radius:4px;padding:2px 8px;font-size:12px;">' + s.label + '</span>';
  }

  function formatTime(t) {
    if (!t) return "-";
    var s = String(t);
    return s.substring(0, 19).replace("T", " ");
  }

  function loadPlans() {
    var keyword = (document.getElementById("dc-collection-keyword") || {}).value || "";
    var status = (document.getElementById("dc-collection-status") || {}).value || "";
    var url = "/api/admin/crawl/plans?page=1&page_size=50";
    if (keyword) url += "&keyword=" + encodeURIComponent(keyword);
    if (status) url += "&status=" + encodeURIComponent(status);

    var container = document.getElementById("dc-collection-plans");
    if (container) container.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">加载中...</div>';

    api(url).then(function (data) {
      var items = (data && data.data && data.data.items) || (data && data.items) || [];
      updateStats(items);
      renderPlanCards(items);
    }).catch(function (err) {
      if (container) container.innerHTML = '<div style="padding:20px;color:#f5222d;">加载失败: ' + err + '</div>';
    });
  }

  function updateStats(items) {
    var total = items.length;
    var active = 0;
    var itemsTotal = 0;
    for (var i = 0; i < items.length; i++) {
      if (items[i].status === "active") active++;
      itemsTotal += (items[i].items_total || 0);
    }
    var elPlans = document.getElementById("dc-stat-plans");
    var elActive = document.getElementById("dc-stat-active");
    var elItems = document.getElementById("dc-stat-items");
    var elRecent = document.getElementById("dc-stat-recent");
    if (elPlans) elPlans.textContent = total;
    if (elActive) elActive.textContent = active;
    if (elItems) elItems.textContent = itemsTotal.toLocaleString();
    if (elRecent) elRecent.textContent = "-";
  }

  function renderPlanCards(items) {
    var container = document.getElementById("dc-collection-plans");
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML = (
        '<div style="padding:60px;text-align:center;color:#999;">' +
        '  <div style="font-size:48px;margin-bottom:16px;">🕷</div>' +
        '  <div style="font-size:16px;margin-bottom:8px;">暂无采集方案</div>' +
        '  <div style="font-size:13px;">点击「+ 新建方案」开始配置你的采集任务</div>' +
        '</div>'
      );
      return;
    }

    var html = [];
    for (var i = 0; i < items.length; i++) {
      var p = items[i];
      var lastRunTime = p.last_run_at ? formatTime(p.last_run_at) : "从未运行";
      html.push(
        '<div class="dc-plan-card" onclick="dcCollection.showPlanDetail(' + p.id + ')">' +
        '  <div class="dc-plan-card-header">' +
        '    <div>' +
        '      <h4 class="dc-plan-card-title">' + (p.plan_name || "(未命名方案)") + '</h4>' +
        '      <div class="dc-plan-card-domain">🌐 ' + (p.target_domain || "-") + ' | 类型: ' + (p.spider_type || "-") + '</div>' +
        '    </div>' +
        '    <div>' + statusBadge(p.status) + '</div>' +
        '  </div>' +
        '  <div class="dc-plan-card-stats">' +
        '    <div class="dc-plan-stat">' +
        '      <div class="dc-plan-stat-label">运行次数</div>' +
        '      <div class="dc-plan-stat-value">' + (p.run_count_total || 0) + '</div>' +
        '    </div>' +
        '    <div class="dc-plan-stat">' +
        '      <div class="dc-plan-stat-label">累计采集</div>' +
        '      <div class="dc-plan-stat-value">' + (p.items_total || 0) + '</div>' +
        '    </div>' +
        '    <div class="dc-plan-stat">' +
        '      <div class="dc-plan-stat-label">上次运行</div>' +
        '      <div class="dc-plan-stat-value" style="font-size:13px;">' + lastRunTime + '</div>' +
        '    </div>' +
        '    <div class="dc-plan-stat">' +
        '      <div class="dc-plan-stat-label">创建人</div>' +
        '      <div class="dc-plan-stat-value" style="font-size:13px;">' + (p.created_by || "-") + '</div>' +
        '    </div>' +
        '  </div>' +
        '  <div class="dc-plan-card-actions">' +
        '    <button class="btn btn-sm" onclick="event.stopPropagation();dcCollection.editPlan(' + p.id + ')">✏️ 编辑</button>' +
        '    <button class="btn btn-sm" onclick="event.stopPropagation();dcCollection.testPlan(' + p.id + ')">🧪 测试</button>' +
        (p.status === "active"
          ? '<button class="btn btn-sm" onclick="event.stopPropagation();dcCollection.disablePlan(' + p.id + ')" style="color:#fa8c16;">⏸ 停用</button>'
          : '<button class="btn btn-sm" onclick="event.stopPropagation();dcCollection.enablePlan(' + p.id + ')" style="color:#52c41a;">▶ 启用</button>') +
        '    <button class="btn btn-sm btn-primary" onclick="event.stopPropagation();dcCollection.runNow(' + p.id + ')">🚀 立即执行</button>' +
        '  </div>' +
        '</div>'
      );
    }
    container.innerHTML = html.join("");
  }

  function showPlanDetail(planId) {
    state.currentPlanId = planId;
    var section = document.getElementById("dc-collection-detail-section");
    if (section) section.style.display = "block";

    var titleEl = document.getElementById("dc-detail-title");
    if (titleEl) titleEl.textContent = "方案详情 — 加载中...";

    api("/api/admin/crawl/plans/" + planId + "/detail").then(function (data) {
      var plan = (data && data.data) || (data && data.plan) || null;
      if (plan) {
        state.currentPlan = plan;
        if (titleEl) titleEl.textContent = "📋 " + (plan.plan_name || "方案详情");
      }
    }).catch(function () {});

    loadRunList(planId);
    switchTab("runs");

    section && section.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function closeDetail() {
    state.currentPlanId = null;
    state.currentPlan = null;
    state.currentRunId = null;
    var section = document.getElementById("dc-collection-detail-section");
    if (section) section.style.display = "none";
  }

  function loadRunList(planId) {
    var container = document.getElementById("dc-run-list");
    if (container) container.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">加载中...</div>';

    api("/api/admin/crawl/recent-runs?plan_id=" + planId + "&page_size=20").then(function (data) {
      if (!data || data.code !== 0 || !data.data) {
        if (container) container.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败：' + (data.msg || "未知错误") + '</div>';
        return;
      }
      var runs = data.data.runs || [];
      renderRunList(runs, data.data.total || 0, planId);
    }).catch(function (err) {
      if (container) container.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败: ' + err + '</div>';
    });
  }

  function renderRunList(runs, total, planId) {
    var container = document.getElementById("dc-run-list");
    if (!container) return;

    if (runs.length === 0) {
      container.innerHTML = (
        '<div style="padding:40px;text-align:center;color:#999;">' +
        '  <div style="font-size:32px;margin-bottom:12px;">📭</div>' +
        '  <div>该方案暂无运行记录</div>' +
        '  <div style="font-size:12px;margin-top:8px;">点击「立即执行」开始采集</div>' +
        '</div>'
      );
      return;
    }

    var html = ['<div style="font-size:13px;color:#666;margin-bottom:12px;">共 ' + total + ' 次运行（最近 20 条）</div>'];
    for (var i = 0; i < runs.length; i++) {
      var run = runs[i];
      var runId = run.id || run.run_id;
      var isActive = state.currentRunId === runId;
      html.push(
        '<div class="dc-run-item ' + (isActive ? "active" : "") + '" onclick="dcCollection.showRunDetail(' + planId + ', ' + runId + ')">' +
        '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
        '    <span style="font-weight:bold;">Run #' + runId + '</span>' +
        runStatusBadge(run.status) +
        '  </div>' +
        '  <div style="font-size:12px;color:#666;margin-bottom:4px;">🕒 ' + formatTime(run.started_at || run.created_at) + '</div>' +
        '  <div style="font-size:12px;color:#888;">' +
        '    ✅ ' + (run.items_success || run.items_written || 0) + ' / ' + (run.items_total || 0) + ' 条' +
        '    | ⏱ ' + (run.duration_ms || 0) + 'ms' +
        '    | 🔧 ' + ((run.steps && run.steps.length) || 0) + ' 步' +
        '  </div>' +
        '  <div style="text-align:right;margin-top:6px;">' +
        '    <a href="javascript:void(0)" onclick="event.stopPropagation();dcCollection.deleteRun(' + planId + ', ' + runId + ')" ' +
        'style="font-size:11px;color:#f5222d;text-decoration:none;">🗑 删除</a>' +
        '  </div>' +
        '</div>'
      );
    }
    container.innerHTML = html.join("");
  }

  function showRunDetail(planId, runId) {
    state.currentRunId = runId;
    var items = document.querySelectorAll(".dc-run-item");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.remove("active");
    }
    var runEl = document.querySelector('.dc-run-item[onclick*="showRunDetail(' + planId + ', ' + runId + ')"]');
    if (runEl) runEl.classList.add("active");
    loadRunSteps(planId, runId);
    loadRunData(planId, runId);
    switchTab("steps");
  }

  function loadRunSteps(planId, runId) {
    var container = document.getElementById("dc-steps-view");
    if (!container) return;
    container.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">加载中...</div>';

    api("/api/admin/crawl/steps?plan_id=" + planId + "&run_id=" + runId).then(function (data) {
      if (!data || data.code !== 0 || !data.data) {
        container.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败：' + (data.msg || "未知错误") + '</div>';
        return;
      }
      var steps = data.data.steps || [];
      var total = data.data.total || 0;
      renderStepsTable(steps, total);
    }).catch(function (err) {
      container.innerHTML = '<div style="color:#f5222d;padding:10px;">加载失败: ' + err + '</div>';
    });
  }

  function renderStepsTable(steps, total) {
    var container = document.getElementById("dc-steps-view");
    if (!container) return;

    if (steps.length === 0) {
      container.innerHTML = (
        '<div style="padding:30px;text-align:center;background:#f7f9fc;border-radius:6px;">' +
        '  <div style="font-size:13px;color:#888;margin-bottom:8px;">本次运行无步骤级详情</div>' +
        '  <div style="font-size:12px;color:#aaa;">可能原因：方案配置中"保存步骤级中间结果"未启用</div>' +
        '</div>'
      );
      return;
    }

    var html = [];
    html.push('<div style="margin-bottom:12px;font-size:13px;color:#666;">共 ' + total + ' 个步骤</div>');
    html.push('<table class="data-table" style="width:100%;border-collapse:collapse;font-size:12px;">');
    html.push(
      '<thead><tr style="background:#f5f7fa;">' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">序号</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;">步骤名称</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:100px;">类型</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">状态</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">输入</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:60px;">输出</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #e8ecf0;width:80px;">耗时(ms)</th>' +
      '</tr></thead><tbody>'
    );

    for (var si = 0; si < steps.length; si++) {
      var st = steps[si];
      var sColor = st.status === "success" ? "#52c41a" : (st.status === "failed" ? "#f5222d" : (st.status === "skipped" ? "#888" : "#1890ff"));
      var sLabel = st.status === "success" ? "成功" : (st.status === "failed" ? "失败" : (st.status === "skipped" ? "跳过" : (st.status || "运行中")));
      html.push(
        '<tr style="background:' + (si % 2 === 0 ? '#fff' : '#fafbfc') + ';">' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;font-weight:bold;color:#666;">' + (st.step_index || (si + 1)) + '</td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.step_name || "-") + '</td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:11px;color:#888;">' + (st.step_type || "-") + '</td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;"><span style="color:' + sColor + ';font-weight:bold;">' + sLabel + '</span></td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.input_count || 0) + '</td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.output_count || 0) + '</td>' +
        '<td style="padding:8px;border-bottom:1px solid #e8ecf0;">' + (st.duration_ms || 0) + '</td>' +
        '</tr>'
      );
    }
    html.push('</tbody></table>');
    container.innerHTML = html.join("");
  }

  function loadRunData(planId, runId) {
    var container = document.getElementById("dc-data-list");
    if (!container) return;
    container.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">加载中...</div>';

    api("/api/admin/crawl/steps?plan_id=" + planId + "&run_id=" + runId + "&page=1&page_size=100").then(function (data) {
      if (!data || data.code !== 0 || !data.data) {
        container.innerHTML = '<div style="padding:20px;color:#999;">暂无结构化数据预览</div>';
        return;
      }
      var steps = data.data.steps || [];
      var lastStep = null;
      for (var i = steps.length - 1; i >= 0; i--) {
        if (steps[i].status === "success" && steps[i].output_count > 0) {
          lastStep = steps[i];
          break;
        }
      }
      if (lastStep && lastStep.output_json) {
        renderDataFromStep(lastStep);
      } else {
        container.innerHTML = (
          '<div style="padding:40px;text-align:center;color:#999;">' +
          '  <div style="font-size:32px;margin-bottom:12px;">📊</div>' +
          '  <div>采集完成后自动生成结构化数据</div>' +
          '  <div style="font-size:12px;margin-top:8px;color:#888;">数据在采集过程中实时结构化，无需额外清洗步骤</div>' +
          '</div>'
        );
      }
    }).catch(function (err) {
      container.innerHTML = '<div style="padding:20px;color:#999;">暂无结构化数据预览</div>';
    });
  }

  function renderDataFromStep(step) {
    var container = document.getElementById("dc-data-list");
    if (!container) return;

    var output = step.output_json;
    var items = [];
    if (typeof output === "object") {
      if (Array.isArray(output)) {
        items = output;
      } else if (output.items && Array.isArray(output.items)) {
        items = output.items;
      } else if (output.data && Array.isArray(output.data)) {
        items = output.data;
      } else {
        items = [output];
      }
    } else if (typeof output === "string") {
      try {
        var parsed = JSON.parse(output);
        if (Array.isArray(parsed)) items = parsed;
        else if (parsed.items && Array.isArray(parsed.items)) items = parsed.items;
        else if (parsed.data && Array.isArray(parsed.data)) items = parsed.data;
        else items = [parsed];
      } catch (e) {
        items = [{ value: output }];
      }
    }

    if (!items || items.length === 0) {
      container.innerHTML = (
        '<div style="padding:40px;text-align:center;color:#999;">' +
        '  <div style="font-size:32px;margin-bottom:12px;">📊</div>' +
        '  <div>暂无结构化数据</div>' +
        '  <div style="font-size:12px;margin-top:8px;color:#888;">步骤名称: ' + (step.step_name || "-") + '</div>' +
        '</div>'
      );
      return;
    }

    var displayItems = items.slice(0, 5);
    var html = [];
    html.push('<div style="margin-bottom:12px;font-size:13px;color:#666;">');
    html.push('  结构化数据预览（来自步骤: <strong>' + (step.step_name || "未知步骤") + '</strong>，共 ' + items.length + ' 条，展示前 5 条）');
    html.push('</div>');
    html.push('<div style="max-height:400px;overflow-y:auto;">');

    for (var i = 0; i < displayItems.length; i++) {
      var item = displayItems[i];
      var itemObj = typeof item === "object" ? item : { value: item };
      var keys = Object.keys(itemObj);

      html.push('<div style="border:1px solid #e8ecf0;border-radius:6px;padding:12px;margin-bottom:10px;background:#fafbfc;">');
      html.push('  <div style="font-weight:bold;margin-bottom:8px;color:#1890ff;"># ' + (i + 1) + '</div>');
      html.push('  <div style="display:grid;grid-template-columns:1fr 2fr;gap:6px 12px;font-size:12px;">');

      var displayKeys = keys.slice(0, 15);
      for (var ki = 0; ki < displayKeys.length; ki++) {
        var key = displayKeys[ki];
        var val = itemObj[key];
        if (typeof val === "object" && val !== null) {
          val = JSON.stringify(val);
        }
        var valStr = String(val || "");
        if (valStr.length > 120) valStr = valStr.substring(0, 120) + "...";
        html.push('    <div style="color:#666;font-weight:bold;">' + key + '</div>');
        html.push('    <div style="color:#333;word-break:break-all;">' + valStr + '</div>');
      }
      if (keys.length > 15) {
        html.push('    <div style="color:#888;font-size:11px;grid-column:span 2;">... 还有 ' + (keys.length - 15) + ' 个字段</div>');
      }
      html.push('  </div>');
      html.push('</div>');
    }

    if (items.length > 5) {
      html.push('<div style="text-align:center;color:#888;font-size:12px;padding:10px;">共 ' + items.length + ' 条数据，仅展示前 5 条预览</div>');
    }

    html.push('</div>');
    html.push('<div style="margin-top:12px;padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;font-size:12px;color:#389e0d;">');
    html.push('  ✅ <strong>采集即结构化</strong>：所有数据在采集过程中实时完成结构化处理，无需额外的清洗步骤。');
    html.push('</div>');
    container.innerHTML = html.join("");
  }

  function switchTab(tabName) {
    state.currentTab = tabName;
    var tabs = document.querySelectorAll(".dc-detail-tab");
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].getAttribute("data-tab") === tabName) {
        tabs[i].classList.add("active");
      } else {
        tabs[i].classList.remove("active");
      }
    }
    var contents = document.querySelectorAll(".dc-tab-content");
    for (var j = 0; j < contents.length; j++) {
      contents[j].style.display = "none";
    }
    var activeContent = document.getElementById("dc-tab-" + tabName);
    if (activeContent) activeContent.style.display = "block";
  }

  function editPlan(planId) {
    window.location.href = "/admin/crawl/steps-editor?plan_id=" + planId;
  }

  function testPlan(planId) {
    showMessage("正在测试...请稍候");
    api("/api/admin/crawl/plans/" + planId + "/test", "POST", {}).then(function (data) {
      if (data && data.code === 0) {
        var items = (data.data && data.data.items) || [];
        showMessage("测试完成，采集到 " + items.length + " 条");
        if (items.length > 0) {
          var txt = "预览前 3 条结构化数据：\n\n" + JSON.stringify(items.slice(0, 3), null, 2);
          window.alert(txt.substring(0, 800));
        }
      } else {
        showMessage("测试失败：" + ((data && data.msg) || "无数据"), true);
      }
    });
  }

  function enablePlan(planId) {
    api("/api/admin/crawl/plans/" + planId + "/enable", "POST", {}).then(function (data) {
      if (data && data.code === 0) { showMessage("已启用"); loadPlans(); }
      else showMessage("启用失败", true);
    });
  }

  function disablePlan(planId) {
    api("/api/admin/crawl/plans/" + planId + "/disable", "POST", {}).then(function (data) {
      if (data && data.code === 0) { showMessage("已停用"); loadPlans(); }
      else showMessage("停用失败", true);
    });
  }

  function runNow(planId) {
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
          showMessage("执行完成，写入 " + items + " 条结构化数据");
          loadPlans();
          if (state.currentPlanId === planId) {
            loadRunList(planId);
          }
        } else {
          showMessage("执行失败：" + ((data && data.msg) || ""), true);
        }
      });
    });
  }

  function deleteRun(planId, runId) {
    confirmThen("⚠ 确定删除该运行记录？此操作不可恢复。", function () {
      api("/api/admin/crawl/runs/" + runId, "DELETE").then(function (data) {
        if (data && data.code === 0) {
          showMessage("运行记录已删除");
          loadRunList(planId);
        }
        else showMessage("删除失败: " + (data.msg || "未知错误"), true);
      });
    });
  }

  function openEditor() {
    window.location.href = "/admin/crawl/steps-editor";
  }

  window.dcCollection = {
    loadPlans: loadPlans,
    refresh: loadPlans,
    openEditor: openEditor,
    showPlanDetail: showPlanDetail,
    closeDetail: closeDetail,
    showRunDetail: showRunDetail,
    switchTab: switchTab,
    editPlan: editPlan,
    testPlan: testPlan,
    enablePlan: enablePlan,
    disablePlan: disablePlan,
    runNow: runNow,
    deleteRun: deleteRun,
  };

  document.addEventListener("DOMContentLoaded", function () {
    loadPlans();
  });
})();
