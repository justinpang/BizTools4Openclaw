/* =========================================================================
 * crawl_editor.js — 可视化采集配置编辑器
 *   5 步流程：① URL 预览 → ② 列表字段 → ③ 详情字段 → ④ 附件配置 → ⑤ 保存调度
 *   全局状态存储于 window.__crawlPlanDraft（JSON 对象，记录全部配置）
 * ========================================================================= */
(function () {
  "use strict";

  // -------- API helper --------
  function api(path, method, body) {
    var opts = {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body && method && method !== "GET") opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  // -------- 从 URL 读取 plan_id（编辑模式） --------
  function getUrlParam(name) {
    var m = window.location.search.match(new RegExp("[?&]" + name + "=([^&]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  // -------- 全局状态（单页应用） --------
  var currentStep = 1;
  var draft = {
    plan_name: "",
    target_domain: "",
    spider_type: "generic",
    rule_config: {
      list_rule: {
        url_template: "",
        item_selector: "",
        link_selector: "",
        fields: [],  // [{name, selector, extractor, required, cleaners}]
        pagination: { mode: "none" },
      },
      detail_rule: {
        use_render: false,
        fields: [],
      },
      attachment_rules: [],
      field_mapping: {},
    },
    schedule_config: { enabled: false, cron: "0 0 2 * * ?" },
    increment_config: { dedup_mode: "url" },
  };

  // 若传入 plan_id，加载已有方案
  var editingPlanId = getUrlParam("plan_id");
  if (editingPlanId) {
    api("/api/admin/crawl/plans/" + editingPlanId + "/detail").then(function (data) {
      if (data && data.code === 0 && data.data) {
        var p = data.data;
        draft.plan_name = p.plan_name || draft.plan_name;
        draft.target_domain = p.target_domain || draft.target_domain;
        draft.spider_type = p.spider_type || draft.spider_type;
        if (p.rule_config) {
          try {
            var rc = (typeof p.rule_config === "string") ? JSON.parse(p.rule_config) : p.rule_config;
            if (rc && rc.list_rule) draft.rule_config = rc;
          } catch (e) { /* ignore */ }
        }
        if (p.schedule_config) draft.schedule_config = p.schedule_config;
        if (p.increment_config) draft.increment_config = p.increment_config;
      }
    });
  }

  window.__crawlPlanDraft = draft;

  // -------- 工具函数 --------
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

  // 生成 CSS selector（从元素往上级回溯）
  function buildCssSelector(element) {
    if (!element || element.nodeType !== 1) return "";
    var parts = [];
    var el = element;
    var maxDepth = 6;
    while (el && el.nodeType === 1 && el.tagName !== "BODY" && parts.length < maxDepth) {
      var tag = el.tagName.toLowerCase();
      var part = tag;
      if (el.id) {
        parts.unshift(tag + "#" + el.id);
        break;
      }
      if (el.className && typeof el.className === "string") {
        var cls = el.className.trim();
        if (cls && !cls.match(/\s/)) {
          // 单个 class，且不与兄弟元素重复
          var parent = el.parentNode;
          if (parent) {
            var sameCls = parent.querySelectorAll(tag + "." + cls);
            if (sameCls.length === 1) {
              parts.unshift(tag + "." + cls);
              el = el.parentNode;
              continue;
            }
          }
        }
      }
      // 用 nth-child
      if (el.parentNode) {
        var siblings = el.parentNode.children;
        var idx = 1;
        for (var i = 0; i < siblings.length; i++) {
          if (siblings[i] === el) { idx = i + 1; break; }
        }
        parts.unshift(tag + ":nth-child(" + idx + ")");
      } else {
        parts.unshift(tag);
      }
      el = el.parentNode;
    }
    return parts.join(" > ");
  }

  // 简化 selector（去掉 nth-child，更通用）
  function simplifySelector(selector) {
    return selector.replace(/:nth-child\(\d+\)/g, "").replace(/:nth-of-type\(\d+\)/g, "").replace(/ > /g, " ").trim();
  }

  // 高亮预览区元素
  function highlightElement(el) {
    var prev = document.querySelectorAll("#crawl-preview-content [data-crawl-highlight]");
    for (var i = 0; i < prev.length; i++) {
      prev[i].removeAttribute("data-crawl-highlight");
      prev[i].style.outline = "";
      prev[i].style.backgroundColor = "";
    }
    if (el) {
      el.setAttribute("data-crawl-highlight", "1");
      el.style.outline = "2px dashed #1890ff";
      el.style.backgroundColor = "rgba(24,144,255,0.08)";
    }
  }

  // -------- 步骤切换 --------
  function renderStep(step) {
    currentStep = step;
    document.getElementById("crawl-step-indicator").textContent = "步骤 " + step + "/5";

    // 更新步骤导航样式
    var steps = document.querySelectorAll(".step-item");
    for (var i = 0; i < steps.length; i++) {
      var s = parseInt(steps[i].getAttribute("data-step"), 10);
      if (s === step) {
        steps[i].style.color = "#1890ff";
        steps[i].style.backgroundColor = "#e6f7ff";
        steps[i].style.fontWeight = "bold";
      } else if (s < step) {
        steps[i].style.color = "#52c41a";
        steps[i].style.backgroundColor = "#f6ffed";
        steps[i].style.fontWeight = "normal";
      } else {
        steps[i].style.color = "#999";
        steps[i].style.backgroundColor = "transparent";
        steps[i].style.fontWeight = "normal";
      }
    }

    // 渲染表单内容
    var formPanel = document.getElementById("crawl-step-content");
    if (formPanel) formPanel.innerHTML = renderStepForm(step);

    // 绑定步骤表单的交互
    bindStepForm(step);
  }

  // -------- 各步骤表单 HTML --------
  function renderStepForm(step) {
    if (step === 1) return renderStep1();
    if (step === 2) return renderStep2();
    if (step === 3) return renderStep3();
    if (step === 4) return renderStep4();
    if (step === 5) return renderStep5();
    return "";
  }

  // Step ①: URL + 页面预览
  function renderStep1() {
    var r = draft.rule_config.list_rule;
    return (
      '<h3 style="margin-top:0;">① 输入目标站点 URL</h3>' +
      '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;margin-bottom:6px;font-size:13px;color:#555;">列表页 URL（示例：https://news.example.com/list）</label>' +
      '  <input type="text" id="f-url" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;" placeholder="https://example.com/news/list" value="' + (r.url_template || "") + '">' +
      '</div>' +
      '<div style="margin-bottom:12px;">' +
      '  <label><input type="checkbox" id="f-render" ' + (draft.rule_config.detail_rule.use_render ? "checked" : "") + '> 启用 JavaScript 动态渲染（适合 SPA/富交互页面，可能较慢）</label>' +
      '</div>' +
      '<button class="btn btn-primary" id="btn-preview" style="padding:8px 20px;">🔍 预览渲染</button>' +
      '<div style="margin-top:20px;padding:12px;background:#fffbe6;border-radius:6px;font-size:12px;color:#888;">' +
      '  <b>使用说明：</b><br>' +
      '  1. 输入列表页 URL，点击「预览渲染」查看页面内容<br>' +
      '  2. 渲染完成后，在右侧预览区点击元素可自动生成选择器<br>' +
      '  3. 步骤 ② 配置列表字段；步骤 ③ 配置详情页字段<br>' +
      '  4. 配置附件解析规则（可选）；最后保存并设置调度周期' +
      '</div>'
    );
  }

  // Step ②: 列表页字段配置
  function renderStep2() {
    var r = draft.rule_config.list_rule;
    var fields = r.fields || [];
    var html = '<h3 style="margin-top:0;">② 列表页字段配置</h3>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;font-size:13px;color:#555;margin-bottom:6px;">列表项选择器（点击右侧预览区中的某一条列表项自动填充）</label>' +
      '  <input type="text" id="f-item" style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;" value="' + (r.item_selector || "") + '" placeholder="li.news-item / article.story">' +
      '</div>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;font-size:13px;color:#555;margin-bottom:6px;">详情链接选择器</label>' +
      '  <input type="text" id="f-link" style="width:100%;padding:6px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;" value="' + (r.link_selector || "") + '" placeholder="a.title-link">' +
      '</div>';

    // 字段配置表
    html += '<h4 style="margin-top:20px;font-size:14px;">字段列表 <button onclick="crawlEditor.addField(2)" class="btn btn-sm" style="font-size:12px;margin-left:10px;">+ 添加字段</button></h4>';
    html += '<div id="list-fields" style="background:white;border:1px solid #e8ecf0;border-radius:4px;padding:10px;">';
    if (fields.length === 0) {
      html += '<div style="color:#999;font-size:12px;padding:15px;text-align:center;">点击「+ 添加字段」，或在预览区点击元素自动生成</div>';
    } else {
      for (var i = 0; i < fields.length; i++) {
        html += renderFieldRow("list", i, fields[i]);
      }
    }
    html += '</div>';

    // 分页配置
    var p = r.pagination || {};
    html += '<h4 style="margin-top:20px;font-size:14px;">分页配置</h4>';
    html += '<div style="padding:10px;background:white;border:1px solid #e8ecf0;border-radius:4px;">' +
      '  <label style="margin-right:15px;font-size:13px;">分页模式：</label>' +
      '  <select id="f-pagination-mode" style="padding:5px;font-size:13px;border:1px solid #ddd;border-radius:4px;">' +
      '    <option value="none"' + (p.mode === "none" ? " selected" : "") + '>不分页</option>' +
      '    <option value="next_button"' + (p.mode === "next_button" ? " selected" : "") + '>下一页按钮</option>' +
      '    <option value="page_param"' + (p.mode === "page_param" ? " selected" : "") + '>URL page 参数</option>' +
      '    <option value="page_number"' + (p.mode === "page_number" ? " selected" : "") + '>页码按钮列表</option>' +
      '  </select>' +
      '  <span style="margin-left:20px;font-size:13px;">最大页数：</span>' +
      '  <input type="number" id="f-max-pages" value="' + (p.max_pages || 10) + '" style="width:70px;padding:5px;font-size:13px;border:1px solid #ddd;border-radius:4px;">' +
      '</div>';

    return html;
  }

  // Step ③: 详情页字段
  function renderStep3() {
    var d = draft.rule_config.detail_rule || { fields: [] };
    var fields = d.fields || [];
    var html = '<h3 style="margin-top:0;">③ 详情页字段配置</h3>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label><input type="checkbox" id="f-detail-render" ' + (d.use_render ? "checked" : "") + '> 详情页启用 JavaScript 渲染</label>' +
      '</div>';

    html += '<h4 style="font-size:14px;">详情页字段 <button onclick="crawlEditor.addField(3)" class="btn btn-sm" style="font-size:12px;margin-left:10px;">+ 添加字段</button></h4>';
    html += '<div id="list-fields" style="background:white;border:1px solid #e8ecf0;border-radius:4px;padding:10px;">';
    if (fields.length === 0) {
      html += '<div style="color:#999;font-size:12px;padding:15px;text-align:center;">建议字段：标题 / 发布时间 / 正文 / 来源 / 作者</div>';
    } else {
      for (var i = 0; i < fields.length; i++) {
        html += renderFieldRow("detail", i, fields[i]);
      }
    }
    html += '</div>';
    return html;
  }

  // Step ④: 附件配置
  function renderStep4() {
    var atts = draft.rule_config.attachment_rules || [];
    var html = '<h3 style="margin-top:0;">④ 附件解析配置（可选）</h3>';
    html += '<div style="margin-bottom:15px;padding:10px;background:white;border:1px solid #e8ecf0;border-radius:4px;">' +
      '  <label style="margin-right:10px;font-size:13px;">解析类型：</label>' +
      '  <label style="margin-right:10px;"><input type="checkbox" id="f-att-pdf" ' + ((atts.indexOf("pdf") >= 0 || atts.length === 0) ? "checked" : "") + '> PDF (文本 + 表格)</label>' +
      '  <label style="margin-right:10px;"><input type="checkbox" id="f-att-image"> 图片 OCR</label>' +
      '  <label style="margin-right:10px;"><input type="checkbox" id="f-att-doc"> Word 文档</label>' +
      '</div>';
    html += '<div style="color:#888;font-size:12px;">检测到附件链接后，将自动下载并按此类型解析内容，提取文本/表格数据；可在字段映射中使用。</div>';
    return html;
  }

  // Step ⑤: 保存 + 调度
  function renderStep5() {
    var s = draft.schedule_config || {};
    var html = '<h3 style="margin-top:0;">⑤ 保存方案 & 调度配置</h3>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;font-size:13px;color:#555;margin-bottom:6px;">方案名称 *</label>' +
      '  <input type="text" id="f-plan-name" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;" value="' + (draft.plan_name || "") + '" placeholder="例如：新闻站每日采集">' +
      '</div>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;font-size:13px;color:#555;margin-bottom:6px;">目标域名</label>' +
      '  <input type="text" id="f-domain" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;" value="' + (draft.target_domain || "") + '">' +
      '</div>';

    html += '<div style="margin-bottom:12px;">' +
      '  <label style="display:block;font-size:13px;color:#555;margin-bottom:6px;">采集类型</label>' +
      '  <select id="f-type" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;">' +
      '    <option value="generic"' + (draft.spider_type === "generic" ? " selected" : "") + '>通用</option>' +
      '    <option value="gov"' + (draft.spider_type === "gov" ? " selected" : "") + '>政务通告</option>' +
      '    <option value="enterprise"' + (draft.spider_type === "enterprise" ? " selected" : "") + '>企业公示</option>' +
      '    <option value="violation"' + (draft.spider_type === "violation" ? " selected" : "") + '>违规通报</option>' +
      '    <option value="news"' + (draft.spider_type === "news" ? " selected" : "") + '>新闻资讯</option>' +
      '  </select>' +
      '</div>';

    html += '<h4 style="font-size:14px;margin-top:20px;">调度配置</h4>' +
      '<div style="padding:12px;background:white;border:1px solid #e8ecf0;border-radius:4px;">' +
      '  <label style="margin-right:15px;"><input type="checkbox" id="f-sched-enabled" ' + (s.enabled ? "checked" : "") + '> 启用定时执行</label>' +
      '  <label style="margin-right:15px;font-size:13px;">执行周期：</label>' +
      '  <select id="f-sched-cron" style="padding:6px;font-size:13px;border:1px solid #ddd;border-radius:4px;">' +
      '    <option value="0 0 2 * * ?" ' + (s.cron === "0 0 2 * * ?" ? "selected" : "") + '>每日凌晨 2 点</option>' +
      '    <option value="0 0 2 ? * MON" ' + (s.cron === "0 0 2 ? * MON" ? "selected" : "") + '>每周一凌晨 2 点</option>' +
      '    <option value="0 0 */6 * * ?" ' + (s.cron === "0 0 */6 * * ?" ? "selected" : "") + '>每 6 小时</option>' +
      '    <option value="0 0 * * * ?" ' + (s.cron === "0 0 * * * ?" ? "selected" : "") + '>每小时</option>' +
      '    <option value="custom">自定义</option>' +
      '  </select>' +
      '  <input type="text" id="f-cron-custom" style="margin-left:10px;padding:6px;font-size:13px;border:1px solid #ddd;border-radius:4px;width:200px;display:none;" placeholder="自定义 cron 表达式">' +
      '</div>';

    html += '<h4 style="font-size:14px;margin-top:20px;">去重配置</h4>' +
      '<div style="padding:12px;background:white;border:1px solid #e8ecf0;border-radius:4px;font-size:13px;">' +
      '  <label><input type="radio" name="dedup" value="url"' + (!draft.increment_config.dedup_mode || draft.increment_config.dedup_mode === "url" ? " checked" : "") + '> 按 URL 去重（推荐）</label><br><br>' +
      '  <label><input type="radio" name="dedup" value="field"' + (draft.increment_config.dedup_mode === "field" ? " checked" : "") + '> 按内容字段去重（基于标题/发布时间）</label><br><br>' +
      '  <label><input type="radio" name="dedup" value="none"' + (draft.increment_config.dedup_mode === "none" ? " checked" : "") + '> 不做增量（全量采集）</label>' +
      '</div>';

    return html;
  }

  // 字段行渲染
  function renderFieldRow(category, idx, field) {
    var f = field || {};
    return (
      '<div style="padding:8px;border-bottom:1px solid #f0f0f0;display:flex;gap:6px;align-items:center;font-size:12px;">' +
      '  <input type="text" data-k="name" placeholder="字段名 (title/content/publish_time)" value="' + (f.name || "") + '" style="flex:0 0 130px;padding:5px 6px;border:1px solid #ddd;border-radius:3px;font-size:12px;">' +
      '  <select data-k="extractor" style="flex:0 0 70px;padding:5px;border:1px solid #ddd;border-radius:3px;font-size:12px;">' +
      '    <option value="css"' + ((f.extractor || "css") === "css" ? " selected" : "") + '>CSS</option>' +
      '    <option value="regex"' + (f.extractor === "regex" ? " selected" : "") + '>正则</option>' +
      '    <option value="xpath"' + (f.extractor === "xpath" ? " selected" : "") + '>XPath</option>' +
      '  </select>' +
      '  <input type="text" data-k="selector" placeholder="选择器" value="' + (f.selector || "") + '" style="flex:1;padding:5px 6px;border:1px solid #ddd;border-radius:3px;font-size:12px;" data-category="' + category + '" data-idx="' + idx + '">' +
      '  <button onclick="crawlEditor.testSelector(\'' + category + '\',' + idx + ')" style="padding:5px 8px;border:1px solid #ddd;border-radius:3px;background:#f5f5f5;cursor:pointer;font-size:11px;">测试</button>' +
      '  <label style="font-size:12px;"><input type="checkbox" data-k="required" ' + (f.required ? "checked" : "") + '>必填</label>' +
      '  <button onclick="crawlEditor.removeField(\'' + category + '\',' + idx + ')" style="padding:5px 8px;border:1px solid #ffa39e;border-radius:3px;background:#fff1f0;color:#f5222d;cursor:pointer;font-size:11px;">删除</button>' +
      '</div>'
    );
  }

  // -------- 表单绑定 --------
  function bindStepForm(step) {
    // Step ①
    if (step === 1) {
      var btn = document.getElementById("btn-preview");
      if (btn) {
        btn.addEventListener("click", function () {
          var url = document.getElementById("f-url").value.trim();
          if (!url) { showMessage("请输入 URL", true); return; }
          draft.rule_config.list_rule.url_template = url;
          var useRender = document.getElementById("f-render").checked;
          draft.rule_config.detail_rule.use_render = useRender;

          // 自动提取域名
          try {
            var urlObj = new URL(url);
            draft.target_domain = urlObj.hostname;
          } catch (e) { /* ignore */ }

          var statusEl = document.getElementById("crawl-preview-status");
          var contentEl = document.getElementById("crawl-preview-content");
          if (statusEl) { statusEl.style.display = "block"; statusEl.textContent = "⏳ 正在渲染 " + url + "..."; }
          if (contentEl) contentEl.style.display = "none";

          api("/api/admin/crawl/preview/render", "POST", { url: url, render_js: useRender }).then(function (data) {
            if (data && data.code === 0 && data.data && data.data.html_preview) {
              if (statusEl) statusEl.style.display = "none";
              if (contentEl) {
                contentEl.style.display = "block";
                contentEl.innerHTML = data.data.html_preview;
                bindPreviewClicks(contentEl);
              }
              var samplesEl = document.getElementById("crawl-preview-samples");
              if (samplesEl) {
                var elems = data.data.clickable_elements || [];
                var preview = [];
                for (var j = 0; j < Math.min(5, elems.length); j++) {
                  preview.push('<div style="font-size:11px;color:#666;padding:3px 0;"><code style="background:#f5f5f5;padding:2px 4px;border-radius:2px;">' +
                    (elems[j].selector || "") + '</code> → ' + (elems[j].text || "").substring(0, 60) + '</div>');
                }
                if (preview.length > 0) {
                  samplesEl.style.display = "block";
                  samplesEl.innerHTML = '<b style="font-size:12px;color:#555;">📄 推荐点击元素：</b><br>' + preview.join("");
                }
              }
              showMessage("预览成功，耗时 " + (data.data.elapsed_ms || 0) + "ms");
            } else {
              if (statusEl) statusEl.textContent = "❌ 渲染失败：" + ((data && data.msg) || "未知错误");
              // fallback: 显示示例
              if (contentEl) {
                contentEl.style.display = "block";
                contentEl.innerHTML = '<div style="color:#888;padding:20px;text-align:center;">渲染失败或后端不可用。请检查网络或手动输入选择器。</div>';
              }
              showMessage("渲染失败", true);
            }
          }).catch(function (err) {
            if (statusEl) statusEl.textContent = "❌ " + err;
          });
        });
      }
    }

    // Step ②/③/④/⑤: 数据回写（失去焦点时更新 draft）
    var inputs = document.querySelectorAll("#crawl-form-panel input, #crawl-form-panel select, #crawl-form-panel textarea");
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].addEventListener("change", function () {
        syncFormToDraft();
      });
    }

    // Step ⑤: 自定义 cron 显示切换
    var cronSel = document.getElementById("f-sched-cron");
    if (cronSel) {
      cronSel.addEventListener("change", function () {
        var custom = document.getElementById("f-cron-custom");
        if (custom) custom.style.display = (cronSel.value === "custom") ? "inline-block" : "none";
      });
    }
  }

  // -------- 预览区点击 → 生成选择器 --------
  function bindPreviewClicks(container) {
    if (!container) return;
    var all = container.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      all[i].addEventListener("click", function (e) {
        e.stopPropagation();
        e.preventDefault();
        highlightElement(this);
        var selector = buildCssSelector(this);
        var text = (this.textContent || "").trim().substring(0, 80);

        // 智能推断：如果元素是 a → 可能是链接；如果是 h1-h6 → 标题
        var tag = this.tagName.toLowerCase();
        var hint = tag;
        if (tag === "a") hint = "链接";
        else if (/^h\d$/.test(tag)) hint = "标题";
        else if (tag === "time") hint = "时间";
        else if (tag === "li" || tag === "article") hint = "列表项";

        // 填充到当前激活的输入框
        var category = (currentStep === 2) ? "list" : (currentStep === 3 ? "detail" : "list");
        if (currentStep === 2) {
          var itemInput = document.getElementById("f-item");
          var linkInput = document.getElementById("f-link");
          if (tag === "li" || tag === "article" || tag === "div") {
            if (itemInput && !itemInput.value) {
              itemInput.value = simplifySelector(selector);
              showMessage("已填充「列表项」选择器（" + hint + "）");
            } else if (linkInput && !linkInput.value) {
              linkInput.value = selector;
              showMessage("已填充「详情链接」选择器");
            } else {
              showMessage("点击文本：" + text + "\n（可手动粘贴到选择器）", false);
            }
          } else if (tag === "a") {
            if (linkInput) linkInput.value = selector;
            showMessage("已识别链接 → 填充到「详情链接」");
          } else {
            // 动态添加字段行
            crawlEditor.addField(category, {
              selector: selector,
              name: hint === "标题" ? "title" : (hint === "时间" ? "publish_time" : "custom_" + Date.now()),
              extractor: "css",
              required: false,
            });
            showMessage("已自动创建字段，选择器：" + selector.substring(0, 40));
          }
        } else if (currentStep === 3) {
          // 详情页字段：直接添加字段
          crawlEditor.addField("detail", {
            selector: selector,
            name: hint === "标题" ? "title" : (hint === "时间" ? "publish_time" : "content"),
            extractor: "css",
            required: false,
          });
          showMessage("已添加详情页字段 → " + hint);
        }
        syncFormToDraft();
      });
    }
  }

  // -------- 表单 → draft 回写 --------
  function syncFormToDraft() {
    // Step ①
    var urlEl = document.getElementById("f-url");
    if (urlEl) draft.rule_config.list_rule.url_template = urlEl.value.trim();

    // Step ②: 列表字段
    var itemEl = document.getElementById("f-item");
    if (itemEl) draft.rule_config.list_rule.item_selector = itemEl.value.trim();
    var linkEl = document.getElementById("f-link");
    if (linkEl) draft.rule_config.list_rule.link_selector = linkEl.value.trim();

    // 列表字段
    var listFields = [];
    var listRows = document.querySelectorAll("#list-fields [data-idx]");
    // 用 parent div 识别字段行
    var fieldRows = document.querySelectorAll("#crawl-step-content div[data-k]");
    // 简化处理：根据最新字段值重写
    // 从 UI 读回所有字段行（列表区）
    var container = document.getElementById("list-fields");
    if (container) {
      var rows = container.children;
      for (var r = 0; r < rows.length; r++) {
        var row = rows[r];
        if (!row.getAttribute) continue;
        var name = row.querySelector('[data-k="name"]');
        var selector = row.querySelector('[data-k="selector"]');
        var extractor = row.querySelector('[data-k="extractor"]');
        var required = row.querySelector('[data-k="required"]');
        if (name && selector) {
          listFields.push({
            name: name.value.trim(),
            selector: selector.value.trim(),
            extractor: extractor ? extractor.value : "css",
            required: required ? required.checked : false,
            cleaners: ["strip_whitespace", "normalize_space"],
          });
        }
      }
    }

    // 分页
    var paginationMode = document.getElementById("f-pagination-mode");
    var maxPages = document.getElementById("f-max-pages");
    if (paginationMode) {
      draft.rule_config.list_rule.pagination = {
        mode: paginationMode.value,
        max_pages: parseInt(maxPages ? maxPages.value : "10") || 10,
      };
    }

    // Step ③: 详情字段
    var detailRender = document.getElementById("f-detail-render");
    if (detailRender) draft.rule_config.detail_rule.use_render = detailRender.checked;

    // Step ④: 附件
    var attChecks = [
      document.getElementById("f-att-pdf") ? document.getElementById("f-att-pdf").checked : true,
      document.getElementById("f-att-image") ? document.getElementById("f-att-image").checked : false,
      document.getElementById("f-att-doc") ? document.getElementById("f-att-doc").checked : false,
    ];
    var atts = [];
    if (attChecks[0]) atts.push("pdf");
    if (attChecks[1]) atts.push("image");
    if (attChecks[2]) atts.push("doc");
    draft.rule_config.attachment_rules = atts;

    // Step ⑤: 保存字段
    var pn = document.getElementById("f-plan-name");
    if (pn) draft.plan_name = pn.value.trim();
    var domainEl = document.getElementById("f-domain");
    if (domainEl) draft.target_domain = domainEl.value.trim();
    var typeEl = document.getElementById("f-type");
    if (typeEl) draft.spider_type = typeEl.value;

    var schedEnabled = document.getElementById("f-sched-enabled");
    var schedCron = document.getElementById("f-sched-cron");
    if (schedEnabled) {
      draft.schedule_config.enabled = schedEnabled.checked;
      var cronVal = schedCron.value;
      if (cronVal === "custom") {
        var custom = document.getElementById("f-cron-custom");
        cronVal = custom ? custom.value.trim() : "0 0 2 * * ?";
      }
      draft.schedule_config.cron = cronVal;
    }

    // dedup
    var dedupRadios = document.getElementsByName("dedup");
    for (var r2 = 0; r2 < dedupRadios.length; r2++) {
      if (dedupRadios[r2].checked) {
        draft.increment_config.dedup_mode = dedupRadios[r2].value;
        break;
      }
    }
  }

  // -------- 暴露 API（供页面按钮调用） --------
  window.crawlEditor = {
    prev: function () {
      syncFormToDraft();
      if (currentStep > 1) renderStep(currentStep - 1);
    },
    next: function () {
      syncFormToDraft();
      // 步骤验证
      if (currentStep === 1) {
        if (!draft.rule_config.list_rule.url_template) {
          showMessage("请先输入 URL 并点击预览", true); return;
        }
      }
      if (currentStep === 5) {
        showMessage("已在最后一步。点击下方「保存并启用」或「保存为草稿」", false);
        return;
      }
      renderStep(currentStep + 1);
    },
    addField: function (category, presets) {
      syncFormToDraft();
      var p = presets || {};
      var target;
      if (category === 2 || category === "list") {
        target = draft.rule_config.list_rule.fields;
      } else if (category === 3 || category === "detail") {
        target = draft.rule_config.detail_rule.fields;
      } else {
        target = draft.rule_config.list_rule.fields;
      }
      target.push({
        name: p.name || "field_" + (target.length + 1),
        selector: p.selector || "",
        extractor: p.extractor || "css",
        required: p.required || false,
        cleaners: ["strip_whitespace", "normalize_space"],
      });
      renderStep(currentStep);
    },
    removeField: function (category, idx) {
      syncFormToDraft();
      var target;
      if (category === "list") target = draft.rule_config.list_rule.fields;
      else target = draft.rule_config.detail_rule.fields;
      target.splice(idx, 1);
      renderStep(currentStep);
    },
    testSelector: function (category, idx) {
      // 使用预览区已有的 html 校验
      var url = draft.rule_config.list_rule.url_template;
      if (!url) { showMessage("请先在步骤①输入 URL", true); return; }
      syncFormToDraft();
      var field;
      if (category === "list") field = draft.rule_config.list_rule.fields[idx];
      else field = draft.rule_config.detail_rule.fields[idx];
      if (!field || !field.selector) { showMessage("请先输入选择器", true); return; }

      showMessage("正在校验选择器...");
      api("/api/admin/crawl/preview/selector", "POST", {
        url: url,
        selector: field.selector,
        extractor: field.extractor,
        sample_limit: 5,
      }).then(function (data) {
        if (data && data.code === 0 && data.data) {
          var samples = data.data.samples || [];
          var count = data.data.match_count || 0;
          var msg = "匹配到 " + count + " 个元素";
          if (samples.length > 0) {
            msg += "\n示例:\n";
            for (var i = 0; i < Math.min(3, samples.length); i++) {
              msg += "  " + (typeof samples[i] === "string" ? samples[i].substring(0, 80) : JSON.stringify(samples[i]).substring(0, 80)) + "\n";
            }
          }
          window.alert(msg);
        } else {
          showMessage("校验失败：" + ((data && data.msg) || ""), true);
        }
      });
    },
    saveDraft: function () {
      syncFormToDraft();
      if (!draft.plan_name) draft.plan_name = "草稿_" + new Date().toLocaleString();
      if (!draft.target_domain) draft.target_domain = "(未填)";
      api("/api/admin/crawl/plans", "POST", draft).then(function (data) {
        if (data && data.code === 0) {
          showMessage("已保存草稿，方案 ID: " + data.data.plan_id);
        } else {
          showMessage("保存失败：" + ((data && data.msg) || ""), true);
        }
      });
    },
    testRun: function () {
      syncFormToDraft();
      showMessage("正在执行测试运行...");
      // 先保存草稿，再调用测试 API
      if (!draft.plan_name) draft.plan_name = "测试方案_" + new Date().toLocaleString();
      if (!draft.target_domain) draft.target_domain = "(未填)";
      api("/api/admin/crawl/plans", "POST", draft).then(function (data) {
        if (data && data.code === 0 && data.data) {
          var planId = data.data.plan_id;
          api("/api/admin/crawl/plans/" + planId + "/test", "POST", {}).then(function (d2) {
            if (d2 && d2.code === 0 && d2.data) {
              var items = d2.data.items || [];
              var msg = "测试完成！共采集 " + (d2.data.items_total || 0) + " 条，匹配率: " + ((d2.data.field_match_rate || 0) * 100).toFixed(0) + "%";
              if (items.length > 0) {
                msg += "\n\n示例:\n" + JSON.stringify(items.slice(0, 2), null, 2).substring(0, 400);
              }
              window.alert(msg);
            } else {
              showMessage("测试失败：" + ((d2 && d2.msg) || ""), true);
            }
          });
        } else {
          showMessage("保存草稿失败：" + ((data && data.msg) || ""), true);
        }
      });
    },
  };

  // 启动: 默认第一步
  renderStep(1);
})();
