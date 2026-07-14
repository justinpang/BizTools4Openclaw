/* ==========================================================================
 * T32: crawl_step_editor.js — 可视化采集配置编辑器
 *   核心函数暴露到 window 全局作用域（可被 HTML onclick 直接调用）
 *   API 前缀：/api/admin
 * ========================================================================== */

(function() {
  "use strict";

  // ============================================================ 全局状态
  var state = {
    mode: "browse",
    steps: [],
    activeStepId: null,
    loadedHtml: "",
    browserHistory: [],
    browserHistoryIdx: -1,
    upstreamCache: { page_access: null },
    planId: null,
    pickKind: null, // "list" | "detail_link" | "table" | null
    planConfig: {
      target_domain: "",
      max_items: 200,
      cron: "",
      save_middle_result: true,
      funnel_visible: true,
      enable_clean: true,
    },
  };

  // ============================================================ 工具函数
  function api(path, method, body) {
    var opts = {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body && method && method !== "GET") opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  function toast(msg, type) {
    var el = document.getElementById("crawl-toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "crawl-toast crawl-toast-" + (type || "info");
    el.style.display = "block";
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.style.display = "none"; }, 2800);
  }

  function getQueryParam(name) {
    var m = (window.location.search || "").match(new RegExp("[?&]" + name + "=([^&]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function uid() {
    return "s_" + Date.now() + "_" + Math.floor(Math.random() * 1e6);
  }

  // ============================================================ 浏览器核心功能

  // 智能注入 HTML 到 iframe：处理原始 HTML 可能是完整文档或片段
  function _buildIframeContent(rawHtml, baseHref) {
    var ourCss =
      'body{margin:0;padding:12px;font-family:"Microsoft YaHei",Arial,sans-serif;font-size:14px;line-height:1.6;color:#333;background:#fff;}' +
      'table{border-collapse:collapse;border-spacing:0;margin:12px 0;}' +
      'table td,table th{border:1px solid #ddd;padding:6px 10px;text-align:left;}' +
      'table th{background:#f5f5f5;font-weight:600;}' +
      'table tr:nth-child(even){background:#fafafa;}' +
      'ul,ol{margin:8px 0;padding-left:24px;}' +
      'li{margin:4px 0;}' +
      'a{color:#2563eb;text-decoration:none;}' +
      'a:hover{text-decoration:underline;}' +
      'h1,h2,h3,h4,h5{margin:12px 0 8px 0;font-weight:600;color:#111;}' +
      '.dqwz,.breadcrumb{background:#f0f7ff;padding:10px;border-radius:4px;font-size:12px;color:#666;}' +
      '.main,.page-con{max-width:100%;}' +
      '.list{list-style:none;padding:0;margin:12px 0;}' +
      '.list li{padding:8px 12px;border-bottom:1px solid #eee;}' +
      '.list li a{color:#333;}' +
      'img{max-width:100%;height:auto;}' +
      '.lmy_main_l{float:left;width:220px;margin-right:16px;background:#f8fafc;padding:12px;border-radius:6px;}' +
      '.lmy_main_r{overflow:hidden;}' +
      '.lmy_main_rt{font-size:18px;font-weight:600;color:#0f172a;border-bottom:2px solid #2563eb;padding-bottom:8px;margin-bottom:12px;}' +
      '.lmy_main_rb{background:#fff;padding:16px;}' +
      '.lmy_main_rb li{list-style:none;padding:8px 0;border-bottom:1px dashed #e5e7eb;}' +
      '.lmy_main_rb li .fl{color:#334155;}' +
      '.lmy_main_rb li .fr{color:#94a3b8;font-size:12px;float:right;}' +
      /* 拾取模式的可视化样式 */
      'body[data-pick-mode="list"] li,' +
      'body[data-pick-mode="list"] tr,' +
      'body[data-pick-mode="list"] .item,' +
      'body[data-pick-mode="list"] [class*="list"] > *,' +
      'body[data-pick-mode="list"] [class*="List"] > *' +
      '{outline:2px dashed #2563eb !important;cursor:crosshair !important;background:rgba(37,99,235,0.05) !important;}' +
      'body[data-pick-mode="list"] li:hover,' +
      'body[data-pick-mode="list"] tr:hover,' +
      'body[data-pick-mode="list"] .item:hover' +
      '{background:rgba(37,99,235,0.15) !important;outline-color:#dc2626 !important;}' +
      'body[data-pick-mode="detail_link"] a' +
      '{outline:2px dashed #16a34a !important;cursor:pointer !important;background:rgba(22,163,74,0.05) !important;}' +
      'body[data-pick-mode="detail_link"] a:hover' +
      '{background:rgba(22,163,74,0.15) !important;}' +
      'body[data-pick-mode="table"] table,' +
      'body[data-pick-mode="table"] table td' +
      '{outline:2px dashed #9333ea !important;cursor:crosshair !important;}' +
      'body[data-pick-mode="table"] table:hover' +
      '{background:rgba(147,51,234,0.08) !important;}';

    var clickScript =
      '(function(){' +
      // 请求父窗口告知当前 pick 模式状态
      'var pm=window.location.search.match(/[?&]pick=([^&]+)/);' +
      'if(pm && pm[1] && pm[1]!=="null"){try{document.body.setAttribute("data-pick-mode",pm[1]);}catch(e){}}' +
      // 监听父窗口的 pick 模式变化
      'window.addEventListener("message",function(ev){' +
      'if(ev.data && ev.data.type==="set_pick_mode"){' +
      'try{document.body.setAttribute("data-pick-mode",ev.data.kind||"");}' +
      'catch(e){}}});' +
      // 点击事件处理
      'function _getPath(el){var path=[];var cur=el;for(var i=0;i<6 && cur && cur.nodeType===1 && cur.tagName!=="BODY";i++){' +
      'var part=cur.tagName.toLowerCase();if(cur.id&&cur.id.length<40){part+="#"+cur.id;path.unshift(part);break;}' +
      'var cls=(cur.className||"");if(typeof cls==="string" && cls.length>0){var cs=cls.trim().split(/\\s+/).filter(function(x){return x && x.length<30 && !/^(hover|active|selected|show|open)$/i.test(x);});if(cs.length>0)part+="."+cs[0];}' +
      'path.unshift(part);cur=cur.parentNode;}' +
      'return path.join(" > ");}' +
      'function _getParentSelector(el,targetTag){' +
      'var cur=el;for(var i=0;i<8 && cur && cur.nodeType===1 && cur.tagName!=="BODY";i++){' +
      'if(cur.tagName && cur.tagName.toLowerCase()===targetTag){return _getPath(cur);}' +
      'cur=cur.parentNode;}return null;}' +
      'document.addEventListener("click",function(e){' +
      'try{' +
      'var tg=e.target;if(!tg)return;' +
      'var mode=document.body.getAttribute("data-pick-mode");' +
      // 如果不是 pick 模式，也传递点击（由父窗口决定是否处理）
      'var selector=_getPath(tg);' +
      'var href=tg.getAttribute && tg.getAttribute("href");' +
      'var text=(tg.innerText||tg.textContent||"").trim().slice(0,120);' +
      'var tagName=tg.tagName.toLowerCase();' +
      'var parentLi=_getParentSelector(tg,"li");' +
      'var parentTr=_getParentSelector(tg,"tr");' +
      'var parentTable=_getParentSelector(tg,"table");' +
      'var parentUl=_getParentSelector(tg,"ul");' +
      'var parentOl=_getParentSelector(tg,"ol");' +
      'var msg={type:"crawl_click",tag:tagName,text:text,href:href,selector:selector,parent_li:parentLi,parent_tr:parentTr,parent_table:parentTable,parent_ul:parentUl,parent_ol:parentOl,mode:mode};' +
      'if(mode && mode!=="null"){e.preventDefault();e.stopPropagation();}' +
      'window.parent.postMessage(msg,"*");' +
      '}catch(err){}});' +
      '})();';

    var lowerHtml = (rawHtml || "").toLowerCase();
    var isFullDoc = lowerHtml.indexOf("<!doctype") >= 0 || lowerHtml.indexOf("<html") >= 0;

    if (isFullDoc) {
      var headIdx = lowerHtml.indexOf("</head>");
      if (headIdx >= 0) {
        var inject =
          '<base href="' + baseHref + '" target="_blank">' +
          '<meta name="viewport" content="width=device-width,initial-scale=1">' +
          '<style>' + ourCss + '</style>' +
          '<script>' + clickScript + '\x3c/script>';
        return rawHtml.substring(0, headIdx) + inject + rawHtml.substring(headIdx);
      }
      var bodyOpenIdx = lowerHtml.indexOf("<body");
      if (bodyOpenIdx >= 0) {
        var injectInBody =
          '<base href="' + baseHref + '" target="_blank">' +
          '<style>' + ourCss + '</style>' +
          '<script>' + clickScript + '\x3c/script>';
        var bodyCloseIdx = lowerHtml.indexOf(">", bodyOpenIdx);
        return rawHtml.substring(0, bodyCloseIdx + 1) + injectInBody + rawHtml.substring(bodyCloseIdx + 1);
      }
    }

    return '<!DOCTYPE html><html><head><meta charset="utf-8">' +
      '<base href="' + baseHref + '" target="_blank">' +
      '<style>' + ourCss + '</style>' +
      '</head><body>' +
      '<script>' + clickScript + '\x3c/script>' +
      (rawHtml || "") +
      '</body></html>';
  }

  function loadBrowserUrl(url, httpMethod, previewOnly) {
    var urlInput = document.getElementById("crawl-url-input");
    url = (url || urlInput.value || "").trim();
    if (!url) { toast("请先输入 URL", "warn"); return; }
    urlInput.value = url;
    var placeholder = document.getElementById("browser-empty-placeholder");
    if (placeholder) placeholder.classList.add("hidden");
    var loadingMask = document.getElementById("browser-loading-mask");
    if (loadingMask) loadingMask.classList.remove("hidden");
    toast("正在渲染页面...", "info");

    api("/api/admin/crawl/steps/preview-render", "POST", { url: url, http_method: httpMethod || "GET" })
      .then(function (data) {
        if (loadingMask) loadingMask.classList.add("hidden");
        if (data && data.code === 0) {
          var out = data.data || {};
          state.loadedHtml = out.html_preview || "";
          var iframe = document.getElementById("crawl-iframe");
          if (iframe) {
            try {
              var baseUrl = out.base_href || url;
              var pathIndex = baseUrl.lastIndexOf("/");
              var baseHref = pathIndex >= 0 ? baseUrl.substring(0, pathIndex + 1) : baseUrl + "/";
              var injected = _buildIframeContent(out.html_preview || "", baseHref);
              iframe.srcdoc = injected;
            } catch (e) {
              toast("渲染失败：" + e, "error"); return;
            }
          }
          var urlEl = document.getElementById("browser-current-url");
          if (urlEl) urlEl.textContent = "🔗 " + url.slice(0, 80);
          var bfStatus = document.getElementById("bf-status");
          if (bfStatus) bfStatus.textContent = (out.status_code || 200);
          var bfTitle = document.getElementById("bf-title");
          if (bfTitle) bfTitle.textContent = (out.title || "").slice(0, 60);
          var bfLinks = document.getElementById("bf-links");
          if (bfLinks) {
            var match = (out.html_preview || "").match(/<a[^>]*>/gi);
            bfLinks.textContent = match ? match.length : 0;
          }
          // previewOnly=true（如"在此预览该详情页"按钮调用时）：
          // 仅将 HTML 加载到浏览器预览，但不自动创建/更新 page_access 步骤的 URL
          if (!previewOnly) {
            var pageAccess = state.steps.find(function (s) { return s.step_type === "page_access"; });
            if (!pageAccess) {
              pageAccess = newStep("page_access", { url: url, render_wait_ms: 2000, http_method: "GET", use_render: true }, 0);
              if (pageAccess) state.activeStepId = pageAccess.step_id;
            } else {
              pageAccess.config.url = url;
              pageAccess.config.render_wait_ms = pageAccess.config.render_wait_ms || 2000;
              pageAccess.config.http_method = pageAccess.config.http_method || "GET";
              pageAccess.config.use_render = pageAccess.config.hasOwnProperty("use_render") ? pageAccess.config.use_render : true;
            }
            state.upstreamCache.page_access = out;
            toast("✅ 页面渲染完成（已创建/更新 页面访问步骤）", "success");
          } else {
            toast("✅ 页面预览完成", "success");
          }
          if (state.browserHistoryIdx < 0 || state.browserHistory[state.browserHistoryIdx].url !== url) {
            state.browserHistory.push({ url: url, title: out.title || "" });
            state.browserHistoryIdx = state.browserHistory.length - 1;
          }
          renderSteps();
          renderStepDetail();
        } else {
          toast("❌ 渲染失败：" + ((data || {}).msg || ""), "error");
          if (placeholder) placeholder.classList.remove("hidden");
        }
      }).catch(function (err) {
        if (loadingMask) loadingMask.classList.add("hidden");
        if (placeholder) placeholder.classList.remove("hidden");
        toast("❌ 渲染异常：" + err, "error");
      });
  }

  function browserBack() {
    if (state.browserHistoryIdx > 0) {
      state.browserHistoryIdx--;
      loadBrowserUrl(state.browserHistory[state.browserHistoryIdx].url, "GET");
    }
  }

  function browserForward() {
    if (state.browserHistoryIdx < state.browserHistory.length - 1) {
      state.browserHistoryIdx++;
      loadBrowserUrl(state.browserHistory[state.browserHistoryIdx].url, "GET");
    }
  }

  // ============================================================ 模式切换（浏览/拾取/录制）
  function setMode(mode) {
    state.mode = mode || "browse";
    // 切换按钮高亮
    var btns = document.querySelectorAll(".mode-btn");
    btns.forEach(function (b) {
      if (b.getAttribute("data-mode") === state.mode) {
        b.classList.add("active");
        b.style.background = "#2563eb";
        b.style.color = "#fff";
        b.style.borderColor = "#2563eb";
      } else {
        b.classList.remove("active");
        b.style.background = "";
        b.style.color = "";
        b.style.borderColor = "";
      }
    });
    // 更新状态栏文字
    var statusEl = document.getElementById("browser-status");
    if (statusEl) {
      if (state.mode === "record") statusEl.textContent = "⚡ 录制模式 — 点击页面元素可录制为指令";
      else if (state.mode === "pick") statusEl.textContent = "🧲 拾取模式 — 点击「🎯 识别列表」或「🔗 选择链接」开始";
      else statusEl.textContent = "👁 浏览模式 — 可查看页面内容";
    }
    // 向 iframe 发送当前模式
    var iframe = document.getElementById("crawl-iframe");
    if (iframe && iframe.contentWindow) {
      try {
        if (state.mode === "browse") {
          iframe.contentWindow.postMessage({ type: "set_pick_mode", kind: "" }, "*");
        }
      } catch (e) { /* 忽略 */ }
    }
  }

  // ============================================================ 拾取模式（Pick Mode）
  function setPickMode(kind) {
    state.pickKind = kind;
    if (kind) {
      setMode("pick");
      var label = kind === "list" ? "🎯 点击预览中的列表项/表格行 → 自动识别选择器" :
                  kind === "detail_link" ? "🔗 点击预览中的链接 → 自动填充 URL" :
                  kind === "table" ? "📊 点击预览中的表格 → 自动识别表格选择器" :
                  "🧲 拾取模式";
      var statusEl = document.getElementById("browser-status");
      if (statusEl) statusEl.textContent = label;
      toast(label, "info");

      // 向 iframe 发送消息，激活拾取样式
      var iframe = document.getElementById("crawl-iframe");
      if (iframe && iframe.contentWindow) {
        try { iframe.contentWindow.postMessage({ type: "set_pick_mode", kind: kind }, "*"); }
        catch (e) { /* 忽略 */ }
      }
    } else {
      setMode("default");
      var iframe2 = document.getElementById("crawl-iframe");
      if (iframe2 && iframe2.contentWindow) {
        try { iframe2.contentWindow.postMessage({ type: "set_pick_mode", kind: "" }, "*"); }
        catch (e) { /* 忽略 */ }
      }
    }
  }

  // 处理从 iframe 发来的点击消息
  function handleIframeClick(msg) {
    if (!state.pickKind) return;
    var href = msg.href || "";
    var text = msg.text || "";
    var tag = msg.tag || "";

    // === 详情跳转模式 ===
    if (state.pickKind === "detail_link") {
      if (!href) { toast("⚠️ 此元素无 href，请点击实际链接", "warn"); return; }
      var fullUrl = _resolveUrl(href, document.getElementById("crawl-url-input").value || "");
      var step = state.steps.find(function (s) { return s.step_type === "detail_jump"; });
      if (!step) {
        step = newStep("detail_jump", { url: fullUrl, detail_fields: [{ name: "title", extractor: "css", expression: "h1, .title" }], use_render: true }, state.steps.length);
      } else {
        step.config.url = fullUrl;
      }
      state.activeStepId = step.step_id;
      state.pickKind = null;
      setMode("default");
      // 取消 iframe 的高亮样式
      var iframe = document.getElementById("crawl-iframe");
      if (iframe && iframe.contentWindow) {
        try { iframe.contentWindow.postMessage({ type: "set_pick_mode", kind: "" }, "*"); }
        catch (e) { /* 忽略 */ }
      }
      renderSteps();
      renderStepDetail();
      toast("✅ 已识别详情页 URL: " + fullUrl.slice(0, 60), "success");
      return;
    }

    // === 列表识别模式：基于用户点击的元素来推断选择器 ===
    if (state.pickKind === "list") {
      // 优先使用用户点击元素所在的父容器信息
      var itemSel = null;
      var linkSel = "a";

      // 点击的是 <a>，但可能在 <li> 或 <tr> 内
      if (msg.parent_li) itemSel = msg.parent_li;
      else if (msg.parent_tr) itemSel = msg.parent_tr;
      // 用户点击的是 <li> 或 <tr> 本身
      else if (tag === "li") itemSel = msg.selector;
      else if (tag === "tr") itemSel = msg.selector;
      // 降级：如果点击的元素有 class，使用该 class
      else if (msg.selector && msg.selector.indexOf(".") >= 0) itemSel = msg.selector;
      // 最后降级：使用 HTML 启发式分析
      else {
        var guess = _guessListSelectors(state.loadedHtml || "");
        itemSel = guess.item_selector;
        linkSel = guess.link_selector;
      }

      var step = state.steps.find(function (s) { return s.step_type === "list_detect"; });
      if (!step) {
        var idx = state.steps.findIndex(function (s) { return s.step_type === "page_access"; });
        step = newStep("list_detect", {
          item_selector: itemSel, link_selector: linkSel, link_attribute: "href",
          crawl_scope: "latest", top_n_count: 50
        }, idx >= 0 ? idx + 1 : state.steps.length);
      } else {
        step.config.item_selector = itemSel;
        step.config.link_selector = linkSel;
      }
      state.activeStepId = step.step_id;
      state.pickKind = null;
      setMode("default");
      var iframe2 = document.getElementById("crawl-iframe");
      if (iframe2 && iframe2.contentWindow) {
        try { iframe2.contentWindow.postMessage({ type: "set_pick_mode", kind: "" }, "*"); }
        catch (e) { /* 忽略 */ }
      }
      renderSteps();
      renderStepDetail();
      toast("✅ 已识别列表选择器: item=" + itemSel + ", link=" + linkSel, "success");
      return;
    }

    // === 表格识别模式 ===
    if (state.pickKind === "table") {
      var tableSel = msg.parent_table || (tag === "table" ? msg.selector : null) ||
        _guessTableSelector(state.loadedHtml || "");
      var step = state.steps.find(function (s) { return s.step_type === "command_extract_table"; });
      if (!step) {
        step = newStep("command_extract_table", { table_selector: tableSel }, state.steps.length);
      } else {
        step.config.table_selector = tableSel;
      }
      state.activeStepId = step.step_id;
      state.pickKind = null;
      setMode("default");
      var iframe3 = document.getElementById("crawl-iframe");
      if (iframe3 && iframe3.contentWindow) {
        try { iframe3.contentWindow.postMessage({ type: "set_pick_mode", kind: "" }, "*"); }
        catch (e) { /* 忽略 */ }
      }
      renderSteps();
      renderStepDetail();
      toast("✅ 已识别表格选择器: " + tableSel, "success");
      return;
    }
  }

  // 从 href 和 base url 解析完整 URL
  function _resolveUrl(href, baseUrl) {
    if (!href) return "";
    if (href.indexOf("http://") === 0 || href.indexOf("https://") === 0) return href;
    // 相对路径 → 基于 baseUrl 拼接
    try {
      var base = new URL(baseUrl);
      return (new URL(href, base)).href;
    } catch (e) {
      // 退化为简单拼接
      if (href[0] === "/") {
        var slashIdx = baseUrl.indexOf("/", 8);
        var host = slashIdx >= 0 ? baseUrl.substring(0, slashIdx) : baseUrl;
        return host + href;
      }
      var idx = baseUrl.lastIndexOf("/");
      return (idx >= 0 ? baseUrl.substring(0, idx + 1) : baseUrl + "/") + href;
    }
  }

  // 基于原始 HTML 启发式识别列表选择器
  // 优先级：ul.list / div.list > ul/ol > div.lmy_main_rb > li > 表格行
  function _guessListSelectors(html) {
    // 检测常见列表 class/id 模式
    var listPatterns = ["class=\"list\"", "class=\"lmy_main_rb\"", "class=\"news_list\"", "class=\"news-list\"",
                       "class=\"article-list\"", "class=\"item-list\"", "id=\"list\"", "class=\"ul1\""];
    var listSel = "";
    for (var i = 0; i < listPatterns.length; i++) {
      if (html.indexOf(listPatterns[i]) >= 0) {
        // 识别包含这个 class 的元素类型
        var pat = listPatterns[i];
        var idx = html.toLowerCase().indexOf(pat);
        if (idx >= 0) {
          // 往前找最近的 <tag
          var before = html.substring(Math.max(0, idx - 20), idx);
          var tagMatch = before.match(/<\s*([a-zA-Z]+)[^>]*$/);
          var tagName = tagMatch ? tagMatch[1].toLowerCase() : "ul";
          if (pat.indexOf("class=\"") >= 0) {
            listSel = tagName + "." + pat.substring(7, pat.length - 1);
          } else if (pat.indexOf("id=\"") >= 0) {
            listSel = tagName + "#" + pat.substring(4, pat.length - 1);
          }
          break;
        }
      }
    }

    if (listSel) {
      // 猜测项选择器：在列表容器内的 li 或 div.item
      return { item_selector: listSel + " li", link_selector: "a" };
    }

    // 检测表格（<table>）
    if (html.indexOf("<table") >= 0) {
      return { item_selector: "table tr", link_selector: "a" };
    }

    // 默认：ul li
    if (html.indexOf("<ul") >= 0) {
      return { item_selector: "ul li", link_selector: "a" };
    }
    if (html.indexOf("<ol") >= 0) {
      return { item_selector: "ol li", link_selector: "a" };
    }

    // 最后 fallback
    return { item_selector: "li, .item", link_selector: "a" };
  }

  // 基于原始 HTML 启发式识别表格选择器
  function _guessTableSelector(html) {
    // 查找带 class 的 table
    var match = html.match(/<table[^>]*class="[^"]+"[^>]*>/i);
    if (match) {
      var classMatch = match[0].match(/class="([^"]+)"/i);
      if (classMatch) return "table." + classMatch[1].split(" ")[0];
    }
    // 查找带 id 的 table
    var idMatch = html.match(/<table[^>]*id="([^"]+)"[^>]*>/i);
    if (idMatch) return "table#" + idMatch[1];
    // 默认
    return "table";
  }

  // ============================================================ 步骤管理

  var STEP_TYPE_META = {
    page_access: { name: "页面访问", defaultConfig: { url: "", render_wait_ms: 2000, http_method: "GET", use_render: true } },
    list_detect: { name: "列表识别", defaultConfig: { item_selector: "li, .item", link_selector: "a", link_attribute: "href", crawl_scope: "latest", top_n_count: 50 } },
    detail_jump: { name: "详情跳转", defaultConfig: { url: "", detail_fields: [{ name: "title", extractor: "css", expression: "h1, .title" }], use_render: true, render_wait_ms: 2000 } },
    attachment_parse: { name: "附件解析", defaultConfig: { url: "", extract_pdf: true } },
    field_mapping: { name: "字段映射", defaultConfig: { map: {} } },
    result_preview: { name: "结果预览", defaultConfig: { preview_count: 10 } },
    command_list_latest: { name: "智能指令：最新N条", defaultConfig: { n: 20 } },
    command_list_filter: { name: "智能指令：按条件筛选", defaultConfig: { filter: "" } },
    command_extract_table: { name: "智能指令：表格结构化", defaultConfig: { table_selector: "table" } },
    command_batch_fields: { name: "智能指令：批量字段", defaultConfig: { fields: [] } },
    command_regex_extract: { name: "智能指令：正则提取", defaultConfig: { pattern: "" } },
    command_pagination_loop: { name: "智能指令：翻页循环", defaultConfig: { next_selector: ".next", max_pages: 20 } },
    command_scroll_load: { name: "智能指令：滚动加载", defaultConfig: { scroll_count: 5 } },
    command_condition_stop: { name: "智能指令：条件终止", defaultConfig: { condition: "" } },
    command_table_latest_jump: { name: "智能指令：表格最新记录跳转", defaultConfig: {
      table_selector: "table", top_n_count: 10, auto_detect_columns: true,
      link_column_name: "", time_column_name: "", title_column_name: "", sort_mode: "desc"
    } },
  };

  function newStep(stepType, overrideConfig, insertIdx) {
    var meta = STEP_TYPE_META[stepType];
    if (!meta) { toast("未知步骤类型：" + stepType, "warn"); return null; }
    var step = {
      step_id: uid(),
      step_order: state.steps.length,
      step_type: stepType,
      title: meta.name,
      config: JSON.parse(JSON.stringify(meta.defaultConfig)),
      test_result: null,
    };
    if (overrideConfig) {
      for (var k in overrideConfig) step.config[k] = overrideConfig[k];
    }
    if (typeof insertIdx === "number" && insertIdx >= 0) {
      state.steps.splice(insertIdx, 0, step);
    } else {
      state.steps.push(step);
    }
    state.steps.forEach(function (s, i) { s.step_order = i; });
    return step;
  }

  function renderSteps() {
    var wrap = document.getElementById("steps-list");
    if (!wrap) return;
    if (state.steps.length === 0) {
      wrap.innerHTML = '<div class="muted" style="padding:24px;text-align:center;">暂无步骤，点击右上角「+ 新增」或「⚡ 插入指令」开始编排</div>';
      return;
    }
    var typeIcons = {
      page_access: "🌐", list_detect: "📋", detail_jump: "📄",
      attachment_parse: "📎", field_mapping: "🔧", result_preview: "👁",
      command_list_latest: "🆕", command_list_filter: "🔍",
      command_extract_table: "📊", command_batch_fields: "📇",
      command_regex_extract: "✂️", command_pagination_loop: "➡️",
      command_scroll_load: "⤵️", command_condition_stop: "⏹",
      command_table_latest_jump: "📋➡️",
    };
    var html = "";
    for (var i = 0; i < state.steps.length; i++) {
      var s = state.steps[i];
      var activeClass = s.step_id === state.activeStepId ? " step-card-active" : "";
      var icon = typeIcons[s.step_type] || "📌";
      var summary = _stepSummary(s);
      html +=
        '<div class="step-card' + activeClass + '" data-step-id="' + s.step_id + '" style="padding:10px 12px;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:8px;cursor:pointer;background:#fff;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
        '<div><strong>' + icon + ' 步骤' + (i + 1) + ': ' + (s.title || "") + '</strong>' +
        '<div class="muted" style="font-size:12px;margin-top:4px;">' + (s.step_type || "") + '</div>' +
        '<div style="font-size:12px;color:#64748b;margin-top:6px;padding:6px 8px;background:#f1f5f9;border-radius:4px;">' + summary + '</div>' +
        '</div>' +
        '<button class="btn btn-sm step-delete-btn" data-step-id="' + s.step_id + '" style="color:#dc262b;">删除</button>' +
        '</div></div>';
    }
    wrap.innerHTML = html;

    var cards = wrap.querySelectorAll(".step-card");
    cards.forEach(function (card) {
      card.addEventListener("click", function (e) {
        if (e.target.classList.contains("step-delete-btn")) {
          var delId = e.target.getAttribute("data-step-id");
          var delIdx = state.steps.findIndex(function (s) { return s.step_id === delId; });
          if (delIdx >= 0) {
            state.steps.splice(delIdx, 1);
            state.steps.forEach(function (s, i) { s.step_order = i; });
            if (state.activeStepId === delId) state.activeStepId = null;
            renderSteps();
            toast("已删除步骤", "success");
          }
        } else {
          activateStep(card.getAttribute("data-step-id"));
        }
      });
    });
  }

  // 根据步骤类型生成简短说明（用于卡片内显示）
  function _stepSummary(step) {
    var t = step.step_type, c = step.config || {};
    if (t === "page_access") return "URL: " + (c.url ? (c.url.length > 50 ? c.url.slice(0, 50) + "..." : c.url) : "(未设置，在上方输入框填写)");
    if (t === "list_detect") return "项选择器: " + (c.item_selector || "(未识别)") + " | 链接选择器: " + (c.link_selector || "(未识别)");
    if (t === "detail_jump") return "详情页 URL: " + (c.url ? (c.url.length > 50 ? c.url.slice(0, 50) + "..." : c.url) : "(在预览中点击链接)");
    if (t === "attachment_parse") return "提取附件并解析";
    if (t === "field_mapping") return "字段映射: " + Object.keys(c.map || {}).length + " 个字段";
    if (t === "result_preview") return "预览最近 " + (c.preview_count || 10) + " 条结果";
    if (t === "command_list_latest") return "只保留最新 " + (c.n || 20) + " 条";
    if (t === "command_list_filter") return "按条件筛选: " + (c.filter || "(未设置)");
    if (t === "command_extract_table") return "表格选择器: " + (c.table_selector || "(未识别)");
    if (t === "command_batch_fields") return "批量字段数: " + ((c.fields || []).length);
    if (t === "command_regex_extract") return "正则: " + ((c.pattern || "(未设置)").length > 30 ? c.pattern.slice(0, 30) + "..." : (c.pattern || "(未设置)"));
    if (t === "command_pagination_loop") return "翻页选择器: " + (c.next_selector || "(未识别)");
    if (t === "command_scroll_load") return "滚动 " + (c.scroll_count || 5) + " 次";
    if (t === "command_condition_stop") return "终止条件: " + (c.condition || "(未设置)");
    if (t === "command_table_latest_jump") return "表格: " + (c.table_selector || "table") + " / 保留: " + (c.top_n_count || 10) + " 条";
    return "点击右侧编辑配置";
  }

  function activateStep(stepId) {
    state.activeStepId = stepId;
    renderSteps();
    renderStepDetail();
  }

  function renderStepDetail() {
    var wrap = document.getElementById("step-detail-body");
    if (!wrap) return;
    var labelEl = document.getElementById("step-detail-label");
    var step = state.steps.find(function (s) { return s.step_id === state.activeStepId; });

    // 更新标签栏
    if (labelEl) {
      if (step) labelEl.textContent = step.title + " · " + step.step_type;
      else labelEl.textContent = "（未选择步骤）";
    }

    // 更新测试/删除按钮状态
    var testBtn = document.getElementById("step-detail-test");
    var delBtn = document.getElementById("step-detail-delete");
    if (testBtn) testBtn.disabled = !step;
    if (delBtn) delBtn.disabled = !step;

    if (!step) {
      wrap.innerHTML = '<div class="muted" style="padding:24px;text-align:center;">从左侧步骤列表中点击一张卡片，在此处编辑该步骤的参数。</div>';
      return;
    }
    step.config = step.config || {};

    // 根据步骤类型渲染不同的配置界面
    var html = _renderStepConfig(step);

    // 底部：高级 JSON 编辑
    html += '<div style="margin-top:16px;padding:10px;background:#fef3c7;border-radius:6px;border:1px solid #fde68a;">' +
      '<div style="font-size:12px;color:#92400e;margin-bottom:6px;">⚙️ 高级：原始 JSON 配置（可手动修改）</div>' +
      '<textarea id="step-config-textarea" style="width:100%;min-height:120px;padding:8px;border:1px solid #e5e7eb;border-radius:4px;font-family:monospace;font-size:12px;">' +
      JSON.stringify(step.config, null, 2) +
      '</textarea>' +
      '</div>';

    wrap.innerHTML = html;

    // 绑定输入事件
    _bindStepInputs(step);

    // 绑定 JSON textarea
    var ta = document.getElementById("step-config-textarea");
    if (ta) {
      ta.addEventListener("input", function () {
        try {
          var parsed = JSON.parse(ta.value);
          step.config = parsed;
          // 重新渲染步骤卡片以更新摘要
          renderSteps();
        } catch (e) { /* 格式错误，暂不更新 */ }
      });
    }
  }

  // 根据步骤类型渲染配置表单
  function _renderStepConfig(step) {
    var t = step.step_type;
    var c = step.config || {};
    var tip = '<div class="smart-info" style="padding:10px;background:#eff6ff;border-radius:6px;border:1px solid #dbeafe;font-size:12px;color:#1e40af;margin-bottom:12px;">';

    if (t === "page_access") {
      var previewHtml = "";
      if (step.test_result && step.test_result.output && step.test_result.output.html_preview) {
        var hp = step.test_result.output.html_preview;
        previewHtml = '<div style="margin-top:12px;padding:12px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:6px;">' +
          '<div style="font-size:12px;color:#065f46;margin-bottom:8px;">📄 页面预览内容 (从上方浏览器加载的内容):</div>' +
          '<div style="max-height:250px;overflow:auto;background:white;padding:12px;border-radius:4px;border:1px solid #d1d5db;font-size:12px;">' +
          hp.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br/>") +
          "</div></div>";
      }
      var previewResult = "";
      if (step.test_result && step.test_result.output) {
        var outPa = step.test_result.output;
        var srcBadge = "";
        var src = outPa.source_type || (outPa.use_render ? "js_render" : "http");
        if (src === "js_render") srcBadge = '<span style="background:#2563eb;color:white;padding:2px 8px;border-radius:10px;font-size:11px;">⚡ JS 渲染</span>';
        else if (src === "http_fallback") srcBadge = '<span style="background:#f59e0b;color:white;padding:2px 8px;border-radius:10px;font-size:11px;">🔄 JS 失败→HTTP 回退</span>';
        else if (src === "http") srcBadge = '<span style="background:#6b7280;color:white;padding:2px 8px;border-radius:10px;font-size:11px;">📡 HTTP 请求</span>';
        else if (src === "external_html") srcBadge = '<span style="background:#06b6d4;color:white;padding:2px 8px;border-radius:10px;font-size:11px;">📥 外部 HTML</span>';
        previewResult = '<div style="margin-top:8px;padding:10px;background:#f0fdf4;border-radius:4px;border:1px solid #bbf7d0;font-size:12px;color:#166534;">' +
          '<div style="margin-bottom:4px;">' + srcBadge + ' <strong>已抓取页面</strong> - URL: ' + (outPa.url || "(未设置)") + '</div>' +
          '<div style="margin-top:4px;">' +
          (outPa.status_code ? '📡 状态码: ' + outPa.status_code + '　' : '') +
          (outPa.html_length ? '📦 HTML 大小: ' + outPa.html_length + ' 字符' : '') +
          (outPa.title ? '　📖 标题: ' + String(outPa.title).slice(0, 50) : '') +
          '</div></div>';
      }
      return tip + '💡 在浏览器上方输入 URL，然后点击「加载预览」。该步骤的 URL 会自动同步。' +
        '<br/>当前 URL 会自动同步，也可手动编辑下方输入框。</div>' +
        _urlField("page_access_url", "目标网址", c.url || "", 420) +
        '<div style="margin-top:8px;">' +
        '<button class="btn btn-sm" onclick="window.crawlLoadPreview()" style="margin-right:6px;">🔍 从浏览器加载</button>' +
        '<span class="muted" style="font-size:11px;">(将上方浏览器中已加载的内容同步到此步骤)</span>' +
        '</div>' +
        '<div style="margin-top:16px;padding:12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;">' +
        '<div style="font-size:13px;color:#1e3a8a;font-weight:bold;margin-bottom:8px;">⚡ 渲染选项（影响抓取内容的完整性）</div>' +
        '<div style="font-size:11px;color:#6b7280;margin-bottom:10px;">' +
        '现代网站的列表/表格通常由 JavaScript 动态生成。' +
        '<strong style="color:#dc2626;">启用 JS 渲染可获取 5-10 倍更多内容</strong>，但会稍慢。' +
        '</div>' +
        _checkField("page_access_use_render", "启用 JavaScript 渲染（推荐）", c.use_render !== false && c.use_render !== "false" && c.use_render !== 0) +
        _numField("page_access_render_wait", "JS 等待时间（毫秒，越大内容越完整）", c.render_wait_ms || 2000) +
        '</div>' +
        previewResult +
        previewHtml;
    }

    if (t === "list_detect") {
      return tip + '💡 点击下方「🎯 识别列表」按钮，然后在预览页面中点击一个列表项/表格行，自动识别选择器。' +
        '<br/>也可手动填写 CSS 选择器。</div>' +
        _textField("list_item_selector", "项选择器 (每行一项)", c.item_selector || "", 340) +
        _textField("list_link_selector", "链接选择器 (用于跳转)", c.link_selector || "a", 340) +
        _selectField("list_scope", "采集范围", [["latest", "最新 N 条"], ["all", "全部"]], c.crawl_scope || "latest") +
        _numField("list_top_n", "保留条数", c.top_n_count || 50) +
        _btnRow([["🎯 识别列表选择器", "window.crawlPickList()"]]);
    }

    if (t === "detail_jump") {
      return tip + '💡 点击下方「🔗 从预览选择链接」按钮，然后在预览页面中点击要跳转的链接，自动识别并填充 URL。' +
        '<br/>也可直接粘贴详情页 URL。</div>' +
        _urlField("detail_jump_url", "详情页 URL", c.url || "", 340) +
        _btnRow([["🔗 从预览选择链接", "window.crawlPickDetailLink()"], ["👁 在此预览该详情页", "window.crawlPreviewDetail('" + step.step_id + "')"]]) +
        // 渲染选项（与 page_access 样式保持一致）
        '<div style="margin-top:16px;padding:12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;">' +
        '<div style="font-size:13px;color:#1e3a8a;font-weight:bold;margin-bottom:8px;">⚡ 渲染选项（影响抓取内容的完整性）</div>' +
        '<div style="font-size:11px;color:#6b7280;margin-bottom:10px;">现代网站的列表/表格通常由 JavaScript 动态生成。启用 JS 渲染可获取 5-10 倍更多内容，但会稍慢。</div>' +
        _checkField("detail_jump_use_render", "启用 JavaScript 渲染（推荐）", c.use_render !== false && c.use_render !== "false" && c.use_render !== 0) +
        _numField("detail_jump_render_wait", "JS 等待时间（毫秒，越大内容越完整）", c.render_wait_ms || 2000) + '</div>';
    }

    if (t === "attachment_parse") {
      var filePreview = c._filePreview ? '<div style="margin-top:10px;padding:10px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;font-size:12px;color:#07598b;">📄 ' + (c._filePreview || "").replace(/</g, "&lt;") + ' 已选择</div>' : '';
      return tip + '💡 从当前页面中识别并解析 PDF/DOC/Excel 附件。可以从页面提取，或直接指定附件 URL，也可以上传本地文件进行测试。</div>' +
        _urlField("attach_url", "附件 URL（可选，不填则从页面自动识别）", c.url || "", 400) +
        _label("attach_file", "或上传本地文件测试（仅测试，不参与实际采集）") +
        '<input type="file" id="attach_file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt" ' +
        '  style="width:100%;max-width:400px;padding:6px 10px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;" ' +
        '  onchange="window.crawlAttachFileSelected(this)">' +
        filePreview +
        _checkField("attach_pdf", "解析 PDF 内容", c.extract_pdf !== false) +
        _checkField("attach_doc", "解析 DOC/DOCX 内容", c.extract_doc !== false) +
        _checkField("attach_excel", "解析 XLS/XLSX 内容", c.extract_excel !== false) +
        _label("attach_link_selector", "附件链接选择器") +
        '<input type="text" id="attach_link_selector" data-step-config value="' + (c.link_selector || "a[href$='.pdf'],a[href$='.doc'],a[href$='.docx']").replace(/"/g, "&quot;") + '" ' +
        '  style="width:100%;max-width:400px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;">' +
        '<div style="margin-top:8px;font-size:12px;color:#475569;">提示：点击下方「🔍 测试」按钮将实际解析附件内容</div>';
    }

    if (t === "field_mapping") {
      // 准备映射表：从 config.map 读取，或从 _tempMap 中读取临时编辑态
      var mapObj = (c.map && typeof c.map === "object") ? c.map : {};
      var keys = Object.keys(mapObj);
      if (keys.length === 0) {
        keys = ["title", "content"];
        if (!mapObj.title) mapObj.title = "items[0].title";
        if (!mapObj.content) mapObj.content = "attachments[0].text";
      }
      var rowsHtml = "";
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        var v = mapObj[k];
        rowsHtml += '<tr data-field-map-row="1">' +
          '<td style="padding:6px 8px;"><input type="text" data-fm-target value="' + k.replace(/"/g, "&quot;") + '" ' +
          '  style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;"></td>' +
          '<td style="padding:6px 8px;"><input type="text" data-fm-source value="' + String(v || "").replace(/"/g, "&quot;") + '" ' +
          '  style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;"></td>' +
          '<td style="padding:6px 8px;width:50px;text-align:center;">' +
          '  <button type="button" class="btn btn-sm btn-warn" onclick="window.crawlRemoveMapRow(this)" style="padding:4px 8px;font-size:12px;">🗑</button>' +
          '</td></tr>';
      }

      // 从 upstreamCache.results 中读取可用的 PDF 表格和表头，供用户点击选择
      var pickerHtml = "";
      var results = (state.upstreamCache && state.upstreamCache.results) ? state.upstreamCache.results : [];
      if (!results || results.length === 0) {
        // 也可以从 attachment_parse 步骤的测试结果中查找
        for (var si = 0; si < state.steps.length; si++) {
          if (state.steps[si].test_result && state.steps[si].test_result.output && state.steps[si].test_result.output.results) {
            results = state.steps[si].test_result.output.results;
            break;
          }
        }
      }
      if (results && results.length > 0) {
        pickerHtml = '<div style="margin-top:14px;padding:12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;">';
        pickerHtml += '<div style="font-size:13px;font-weight:600;color:#075985;margin-bottom:8px;">🎯 从已解析的 PDF 中快速插入表达式：</div>';
        for (var ri = 0; ri < results.length; ri++) {
          var res = results[ri];
          if (!res) continue;
          pickerHtml += '<div style="padding:6px 8px;background:#fff;border:1px solid #e0e7ff;border-radius:4px;margin-bottom:8px;">';
          pickerHtml += '<div style="font-size:12px;color:#1e3a8a;margin-bottom:4px;">📄 ' + (res.filename || ("附件 " + ri)) + '</div>';
          // 文本
          pickerHtml += '<button type="button" class="btn btn-sm" onclick="window.crawlCopyExpr(\'attachments[' + ri + '].text\')" ' +
            'style="padding:4px 8px;font-size:11px;margin:2px;background:#3b82f6;color:#fff;border:none;border-radius:4px;cursor:pointer;">+ 全文文本</button>';
          // 表格
          if (res.tables && res.tables.length > 0) {
            var firstHeaders = (res.tables[0] && res.tables[0].headers) || [];
            if (res.merged_rows && res.merged_rows.length > 0) {
              for (var mhIdx = 0; mhIdx < firstHeaders.length; mhIdx++) {
                var mExpr = 'attachments[' + ri + '].merged_rows[row][' + mhIdx + ']';
                var mDisplayName = firstHeaders[mhIdx] || ("列 " + mhIdx);
                pickerHtml += '<button type="button" class="btn btn-sm" onclick="window.crawlCopyExpr(\'' + mExpr.replace(/'/g, "\\'") + '\')" ' +
                  'style="padding:4px 8px;font-size:11px;margin:2px;background:#10b981;color:#fff;border:none;border-radius:4px;cursor:pointer;" title="' + mExpr + '">' +
                  '+ 全部表 ' + String(mDisplayName).substring(0, 10) + '</button>';
              }
            }
            for (var tIdx = 0; tIdx < res.tables.length; tIdx++) {
              var t = res.tables[tIdx];
              var headers = t.headers || [];
              for (var hIdx = 0; hIdx < headers.length; hIdx++) {
                var expr = 'attachments[' + ri + '].tables[' + tIdx + '].rows[row][' + hIdx + ']';
                var displayName = headers[hIdx] || ("列 " + hIdx);
                pickerHtml += '<button type="button" class="btn btn-sm" onclick="window.crawlCopyExpr(\'' + expr.replace(/'/g, "\\'") + '\')" ' +
                  'style="padding:4px 8px;font-size:11px;margin:2px;background:#0891b2;color:#fff;border:none;border-radius:4px;cursor:pointer;" title="' + expr + '">' +
                  '+ 表' + (tIdx + 1) + ' ' + String(displayName).substring(0, 10) + '</button>';
              }
            }
          }
          // metadata
          if (res.metadata && typeof res.metadata === "object") {
            var metaK = Object.keys(res.metadata);
            for (var mk = 0; mk < metaK.length; mk++) {
              var mExpr = 'attachments[' + ri + '].metadata.' + metaK[mk];
              pickerHtml += '<button type="button" class="btn btn-sm" onclick="window.crawlCopyExpr(\'' + mExpr.replace(/'/g, "\\'") + '\')" ' +
                'style="padding:4px 8px;font-size:11px;margin:2px;background:#f59e0b;color:#fff;border:none;border-radius:4px;cursor:pointer;">' +
                '+ ' + String(metaK[mk]).substring(0, 10) + '</button>';
            }
          }
          pickerHtml += "</div>";
        }
        pickerHtml += "</div>";
      } else {
        pickerHtml = '<div style="margin-top:14px;padding:10px;background:#fef3c7;border:1px solid #fbbf24;border-radius:6px;font-size:12px;color:#78350f;">💡 提示：先完成「附件解析」步骤的测试，这里会显示 PDF 中识别出的表格和元数据，供快速点击生成映射表达式。</div>';
      }

      return tip + '💡 将提取内容映射到目标字段。可引用 items / attachments / 固定值。</div>' +
        '<div style="padding:10px;background:#f8fafc;border-radius:6px;font-size:11px;color:#475569;line-height:1.7;">' +
        '<strong>表达式语法：</strong><br/>' +
        '• <code>attachments[0].text</code> — 附件 0 全文文本<br/>' +
        '• <code>attachments[0].merged_rows[row][0]</code> — <strong>所有表格合并后每行第 0 列（推荐用于多页 PDF）</strong><br/>' +
        '• <code>attachments[0].tables[0].rows[row][0]</code> — 表格 0（单页）每行第 0 列<br/>' +
        '• <code>attachments[0].tables[0].rows[1][0]</code> — 表格 0 第 1 行第 0 列（单格取值）<br/>' +
        '• <code>attachments[0].metadata.Author</code> — 附件元数据（作者/标题/日期等）<br/>' +
        '• <code>items[0].title</code> — items 列表第 0 项的 title 字段<br/>' +
        '• <code>=固定文本</code> — 直接输出一段固定文本</div>' +
        pickerHtml +
        '<table style="width:100%;margin-top:12px;border-collapse:collapse;font-size:12px;">' +
        '<thead><tr>' +
        '<th style="padding:6px 8px;text-align:left;background:#eef2ff;border:1px solid #c7d2fe;">目标字段名</th>' +
        '<th style="padding:6px 8px;text-align:left;background:#eef2ff;border:1px solid #c7d2fe;">来源表达式</th>' +
        '<th style="padding:6px 8px;width:50px;background:#eef2ff;border:1px solid #c7d2fe;"></th>' +
        '</tr></thead>' +
        '<tbody>' + rowsHtml + '</tbody></table>' +
        '<div style="margin-top:8px;"><button type="button" class="btn btn-sm" onclick="window.crawlAddMapRow()" ' +
        'style="padding:6px 10px;font-size:12px;">+ 添加字段</button></div>';
    }

    if (t === "result_preview") {
      var resultHtml = "";
      if (step.test_result && step.test_result.output) {
        var out = step.test_result.output;
        var items = out.items || [];
        var atts = out.attachments || [];
        var previewLimit = out.sample_size || c.preview_count || 50;
        if (items.length > 0 || atts.length > 0) {
          resultHtml = '<div style="margin-top:16px;padding:14px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;">';
          resultHtml += '<div style="font-weight:bold;color:#065f46;font-size:13px;margin-bottom:10px;">📊 已抓取到 ' + (items.length || 0) + ' 条记录，' + (atts.length || 0) + ' 个附件（预览上限 ' + previewLimit + ' 条）</div>';
          if (items.length > 0) {
            resultHtml += '<div style="font-size:12px;color:#166534;margin-bottom:6px;">记录内容:</div>';
            resultHtml += '<div style="max-height:300px;overflow:auto;background:white;padding:8px;border:1px solid #d1d5db;border-radius:4px;">';
            var rpShowCount = Math.min(items.length, previewLimit);
            for (var ri = 0; ri < rpShowCount; ri++) {
              var it = items[ri];
              if (typeof it === "object" && it !== null) {
                resultHtml += '<div style="margin-bottom:8px;padding:8px;background:#f9fafb;border-radius:4px;font-size:11px;">' +
                  '<div style="color:#6b7280;margin-bottom:4px;"># ' + (ri + 1) + '</div>' +
                  '<pre style="font-size:11px;margin:0;white-space:pre-wrap;word-break:break-all;">' +
                  JSON.stringify(it, null, 2).replace(/</g, "&lt;") +
                  "</pre></div>";
              } else {
                resultHtml += '<div style="padding:8px;background:#f9fafb;border-radius:4px;font-size:11px;">#' + (ri + 1) + ": " + String(it).replace(/</g, "&lt;") + "</div>";
              }
            }
            resultHtml += "</div>";
          }
          if (atts.length > 0) {
            resultHtml += '<div style="font-size:12px;color:#166534;margin:10px 0 6px 0;">附件:</div>';
            resultHtml += '<div style="max-height:200px;overflow:auto;background:white;padding:8px;border:1px solid #d1d5db;border-radius:4px;">';
            for (var ai = 0; ai < Math.min(atts.length, 3); ai++) {
              var att = atts[ai];
              resultHtml += '<div style="padding:6px 8px;background:#f9fafb;border-radius:4px;font-size:11px;margin-bottom:4px;">' +
                '<div>📄 ' + (att.filename || att.source_url || ("附件 " + (ai + 1))) + "</div>";
              if (att.text) resultHtml += '<div style="color:#6b7280;margin-top:4px;">文本: ' + String(att.text).replace(/</g, "&lt;") + "</div>";
              resultHtml += "</div>";
            }
            resultHtml += "</div>";
          }
          resultHtml += "</div>";
        }
      }
      return tip + '💡 查看从前面步骤提取并映射后的最终结果。通常作为编排的最后步骤。' +
        '<br/>当前步骤会自动从上游步骤获取数据进行显示。</div>' +
        _numField("result_count", "预览条数", c.preview_count || 10) +
        resultHtml;
    }

    // 智能指令类
    if (t === "command_list_latest") return _numField("cmd_n", "保留最新条数", c.n || 20);
    if (t === "command_list_filter") return _textField("cmd_filter", "筛选条件 (关键词或正则)", c.filter || "", 340);
    if (t === "command_extract_table") return tip + '💡 点击下方按钮，然后在预览中点击表格区域，自动识别表格选择器。</div>' +
      _textField("cmd_table_selector", "表格 CSS 选择器", c.table_selector || "table", 340) +
      _btnRow([["🎯 识别表格", "window.crawlPickTable()"]]);
    if (t === "command_batch_fields") return '<div class="muted" style="font-size:12px;">批量字段定义（在下方 JSON 中编辑 fields 数组）</div>';
    if (t === "command_regex_extract") return _textField("cmd_regex", "正则表达式", c.pattern || "", 340);
    if (t === "command_pagination_loop") return _textField("cmd_next_selector", "下一页按钮选择器", c.next_selector || ".next", 340) +
      _numField("cmd_max_pages", "最大翻页数", c.max_pages || 20);
    if (t === "command_scroll_load") return _numField("cmd_scroll_count", "滚动次数", c.scroll_count || 5);
    if (t === "command_condition_stop") return _textField("cmd_condition", "终止条件", c.condition || "", 340);

    if (t === "command_table_latest_jump") {
      return tip + '💡 从表格中自动识别最新记录，生成可用于详情跳转的 items 列表。建议工作流：页面访问 → 表格最新记录跳转 → 详情跳转 → 字段映射。</div>' +
        _textField("cmd_table_sel", "表格 CSS 选择器", c.table_selector || "table", 340) +
        _numField("cmd_top_n", "取前 N 条记录", c.top_n_count || 10) +
        _label("cmd_sort", "排序模式") +
        '<select id="cmd_sort" data-step-config style="width:340px;padding:6px 10px;border:1px solid #cbd5e1;border-radius:4px;">' +
        '  <option value="desc"' + ((c.sort_mode || "desc") === "desc" ? " selected" : "") + '>desc (最新在前)</option>' +
        '  <option value="asc"' + ((c.sort_mode || "desc") === "asc" ? " selected" : "") + '>asc (最旧在前)</option>' +
        '  <option value="none"' + ((c.sort_mode || "desc") === "none" ? " selected" : "") + '>none (保持原顺序)</option>' +
        '</select>' +
        _label("cmd_auto", "自动识别列") +
        '<input type="checkbox" id="cmd_auto" data-step-config ' + ((c.auto_detect_columns !== false) ? "checked" : "") + ' style="margin-right:6px;">' +
        '<span class="muted" style="font-size:12px;">自动识别时间列/链接列/标题列</span>' +
        '<div style="margin-top:10px;font-size:12px;color:#64748b;">如需手动指定列名，请在下方 JSON 中编辑 link_column_name/time_column_name/title_column_name</div>';
    }

    return '<div class="muted" style="font-size:12px;">在下方 JSON 中编辑配置</div>';
  }

  // --- 表单字段构建工具 ---
  function _label(key, labelText) {
    return '<label for="' + key + '" style="display:block;margin:10px 0 4px 0;font-size:12px;color:#475569;font-weight:600;">' + labelText + '</label>';
  }
  function _textField(key, label, val, w) {
    return _label(key, label) + '<input type="text" id="' + key + '" data-step-config value="' + (val || "").replace(/"/g, "&quot;") + '" ' +
      'style="width:100%;max-width:' + (w || 380) + 'px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:4px;font-size:13px;background:#fff;color:#1e293b;box-shadow:inset 0 1px 2px rgba(0,0,0,0.05);">' +
      '<div style="font-size:11px;color:#94a3b8;margin-top:3px;">CSS 选择器 / 文本值</div>';
  }
  function _urlField(key, label, val, w) {
    return _label(key, label) + '<input type="text" id="' + key + '" data-step-config value="' + (val || "").replace(/"/g, "&quot;") + '" placeholder="https://example.com/page" ' +
      'style="width:100%;max-width:' + (w || 380) + 'px;padding:8px 10px;border:1px solid #2563eb;border-radius:4px;font-size:13px;background:#fff;color:#1e293b;box-shadow:inset 0 1px 2px rgba(0,0,0,0.05);">' +
      '<div style="font-size:11px;color:#94a3b8;margin-top:3px;">点击上方「加载预览」按钮后，URL 会自动同步到此字段</div>';
  }
  function _numField(key, label, val) {
    return _label(key, label) + '<input type="number" id="' + key + '" data-step-config value="' + (val || 0) + '" ' +
      'style="width:100%;max-width:140px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:4px;font-size:13px;background:#fff;color:#1e293b;">';
  }
  function _selectField(key, label, opts, cur) {
    var o = "";
    for (var i = 0; i < opts.length; i++) {
      var selected = opts[i][0] === cur ? " selected" : "";
      o += '<option value="' + opts[i][0] + '"' + selected + '>' + opts[i][1] + '</option>';
    }
    return _label(key, label) + '<select id="' + key + '" data-step-config ' +
      'style="width:100%;max-width:200px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:4px;font-size:13px;background:#fff;color:#1e293b;">' + o + '</select>';
  }
  function _checkField(key, label, checked) {
    return '<label style="display:flex;align-items:center;gap:8px;margin:10px 0;font-size:13px;color:#334155;cursor:pointer;">' +
      '<input type="checkbox" id="' + key + '" data-step-config' + (checked ? " checked" : "") + ' style="width:16px;height:16px;">' + label + '</label>';
  }
  function _btnRow(btns) {
    var h = '<div style="margin-top:18px;display:flex;flex-wrap:wrap;gap:8px;">';
    for (var i = 0; i < btns.length; i++) {
      h += '<button type="button" class="btn btn-sm" onclick="' + btns[i][1] + '" style="padding:8px 14px;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">' + btns[i][0] + '</button>';
    }
    h += '</div>';
    return h;
  }

  // 把表单字段的值绑定回 step.config
  function _bindStepInputs(step) {
    var inputs = document.querySelectorAll("[data-step-config]");
    inputs.forEach(function (inp) {
      var id = inp.id;
      var targetKey = _mapInputToConfigKey(id);
      if (!targetKey) return;
      inp.addEventListener("input", function () {
        var val = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? parseFloat(inp.value) : inp.value);
        step.config[targetKey] = val;
        // 同步更新 JSON textarea
        var ta = document.getElementById("step-config-textarea");
        if (ta) ta.value = JSON.stringify(step.config, null, 2);
        renderSteps();
      });
      inp.addEventListener("change", function () {
        var val = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? parseFloat(inp.value) : inp.value);
        step.config[targetKey] = val;
        var ta = document.getElementById("step-config-textarea");
        if (ta) ta.value = JSON.stringify(step.config, null, 2);
        renderSteps();
      });
    });
    // 对 field_mapping 步骤，额外绑定动态字段输入
    if (step && step.step_type === "field_mapping") {
      setTimeout(bindFieldMapInputs, 50);
    }
  }

  // input id → config key 映射
  function _mapInputToConfigKey(id) {
    var m = {
      "page_access_url": "url", "page_access_use_render": "use_render", "page_access_render_wait": "render_wait_ms",
      "list_item_selector": "item_selector", "list_link_selector": "link_selector", "list_scope": "crawl_scope", "list_top_n": "top_n_count",
      "detail_jump_url": "url", "detail_jump_use_render": "use_render", "detail_jump_render_wait": "render_wait_ms",
      "attach_pdf": "extract_pdf", "attach_doc": "extract_doc", "attach_excel": "extract_excel",
      "attach_url": "url", "attach_link_selector": "link_selector",
      "result_count": "preview_count",
      "cmd_n": "n", "cmd_filter": "filter", "cmd_table_selector": "table_selector",
      "cmd_regex": "pattern", "cmd_next_selector": "next_selector", "cmd_max_pages": "max_pages",
      "cmd_scroll_count": "scroll_count", "cmd_condition": "condition",
      // command_table_latest_jump 字段映射
      "cmd_table_sel": "table_selector", "cmd_top_n": "top_n_count",
      "cmd_sort": "sort_mode", "cmd_auto": "auto_detect_columns",
    };
    return m[id];
  }

  // ============================================================ 测试功能

  // 从所有前面步骤累积上游数据（用于单步测试）
  function _buildUpstreamData(step) {
    var upstream = {};
    // 仅当当前步骤不是 page_access 本身时，才考虑传递 state.loadedHtml 作为 html_preview
    // 且该 HTML 必须确实对应 page_access 步骤的 URL（而不是被详情页预览覆盖过的）
    var pageAccessStep = state.steps.find(function (s) { return s.step_type === "page_access"; });
    var pageAccessUrl = (pageAccessStep && pageAccessStep.config) ? (pageAccessStep.config.url || "") : "";
    var currentUrl = (document.getElementById("crawl-url-input") || {}).value || "";
    if (step.step_type !== "page_access" &&
        state.loadedHtml &&
        (pageAccessUrl === currentUrl || !pageAccessUrl)) {
      upstream.html_preview = state.loadedHtml;
      // 同时传递 URL 信息，供后续步骤（如附件解析）补全相对 URL
      if (currentUrl) {
        upstream.url = currentUrl;
        upstream.base_href = currentUrl;
      }
    }
    // 从 page_access 步骤的配置中获取 URL（如果上方没有设置）
    if (!upstream.url && pageAccessUrl) {
      upstream.url = pageAccessUrl;
      upstream.base_href = pageAccessUrl;
    }
    // 从 upstreamCache.page_access 中获取更完整的信息（preview-render 的结果）
    if (state.upstreamCache && state.upstreamCache.page_access) {
      var pa = state.upstreamCache.page_access;
      if (pa.url && !upstream.url) upstream.url = pa.url;
      if (pa.base_href && !upstream.base_href) upstream.base_href = pa.base_href;
      if (pa.final_url && !upstream.final_url) upstream.final_url = pa.final_url;
    }
    // 累积所有前面步骤的 test_result.output
    var currentIdx = state.steps.findIndex(function (s) { return s.step_id === step.step_id; });
    for (var i = 0; i < currentIdx; i++) {
      var prev = state.steps[i];
      if (prev && prev.test_result && prev.test_result.output) {
        var out = prev.test_result.output;
        // 保留每个步骤有价值的字段
        if (out.items) upstream.items = out.items;
        if (out.mapped_items) upstream.mapped_items = out.mapped_items;
        if (out.results) upstream.results = out.results;
        if (out.attachments) upstream.attachments = out.attachments;
        if (out.html_preview) upstream.html_preview = out.html_preview;
        if (out.url) upstream.url = out.url;
        if (out.final_url) upstream.final_url = out.final_url;
        if (out.base_href) upstream.base_href = out.base_href;
        if (out.containers) upstream.containers = out.containers;
      }
    }
    // 也保留上游缓存
    if (state.upstreamCache) {
      for (var k in state.upstreamCache) {
        if (!(k in upstream)) upstream[k] = state.upstreamCache[k];
      }
    }
    return upstream;
  }

  function doTestStep(step) {
    if (!step) { toast("请先选择步骤", "warn"); return; }
    // 如果用户上传了本地文件到 attachment_parse，直接调用文件解析
    if (step.step_type === "attachment_parse" && state.attachmentFileBase64) {
      doTestAttachmentWithFile(state.attachmentFileBase64, state.attachmentFileName || "uploaded");
      return;
    }
    toast("正在测试：" + step.title, "info");
    
    // 累积前面步骤的输出作为上游数据
    var upstream = _buildUpstreamData(step);
    
    api("/api/admin/crawl/steps/step-test", "POST", {
      step_type: step.step_type,
      config: step.config || {},
      page_html: state.loadedHtml || "",
      upstream_data: upstream,
    }).then(function (data) {
      if (data && data.code === 0) {
        var summary = document.getElementById("step-test-summary");
        var text = document.getElementById("test-status-text");
        var results = document.getElementById("test-results");
        if (text) text.textContent = "测试通过：" + step.title;
        if (results) {
          // 对 attachment_parse 进行友好渲染
          if (step.step_type === "attachment_parse" && data.data && data.data.output && data.data.output.results && data.data.output.results.length > 0) {
            var first = data.data.output.results[0];
            results.innerHTML = renderAttachmentResult(first);
            // 缓存供下游字段映射使用
            state.upstreamCache = state.upstreamCache || {};
            state.upstreamCache.results = data.data.output.results;
            state.upstreamCache.attachments = data.data.output.results;
          } else if (step.step_type === "field_mapping" && data.data && data.data.output) {
            // 字段映射：渲染映射结果
            var out = data.data.output;
            var mapped = out.mapped_items || out.items || [];
            var html = '<div style="padding:10px;">';
            html += '<div style="margin-bottom:8px;padding:8px 12px;background:#dcfce7;border-radius:4px;font-size:12px;color:#166534;">✅ 字段映射完成，共 ' + mapped.length + ' 条记录</div>';
            for (var i = 0; i < Math.min(mapped.length, 5); i++) {
              html += '<div style="margin:8px 0;padding:8px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;"><strong style="font-size:12px;color:#1e293b;">记录 ' + (i + 1) + ':</strong><pre style="font-size:12px;margin-top:6px;background:#fff;padding:6px;border-radius:4px;white-space:pre-wrap;word-break:break-all;">' +
                JSON.stringify(mapped[i], null, 2).replace(/</g, "&lt;") + '</pre></div>';
            }
            if (out.map) {
              html += '<div style="margin-top:8px;padding:8px 12px;background:#f5f3ff;border-radius:4px;font-size:11px;color:#4c1d95;"><strong>映射规则:</strong><pre style="font-size:11px;margin-top:4px;">' +
                JSON.stringify(out.map, null, 2).replace(/</g, "&lt;") + '</pre></div>';
            }
            html += "</div>";
            results.innerHTML = html;
            state.upstreamCache = state.upstreamCache || {};
            state.upstreamCache.mapped = mapped;
            state.upstreamCache.items = mapped;
          } else if (step.step_type === "list_detect" && data.data && data.data.output && data.data.output.items && data.data.output.items.length > 0) {
            // 列表识别：显示识别到的项
            var itemsLd = data.data.output.items;
            var htmlLd = '<div style="padding:10px;">';
            htmlLd += '<div style="margin-bottom:8px;padding:8px 12px;background:#dbeafe;border-radius:4px;font-size:12px;color:#1e40af;">✅ 列表识别完成，共 ' + itemsLd.length + ' 条</div>';
            for (var li = 0; li < Math.min(itemsLd.length, 5); li++) {
              htmlLd += '<div style="margin:8px 0;padding:8px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;"><strong style="font-size:12px;">项 ' + (li + 1) + ':</strong><pre style="font-size:11px;margin-top:6px;background:#fff;padding:6px;border-radius:4px;white-space:pre-wrap;word-break:break-all;">' +
                JSON.stringify(itemsLd[li], null, 2).replace(/</g, "&lt;") + '</pre></div>';
            }
            htmlLd += "</div>";
            results.innerHTML = htmlLd;
            state.upstreamCache = state.upstreamCache || {};
            state.upstreamCache.items = itemsLd;
          } else if (step.step_type === "detail_jump" && data.data && data.data.output) {
            var itemsDj = data.data.output.items || data.data.output.detail_items || [];
            var htmlDj = '<div style="padding:10px;">';
            htmlDj += '<div style="margin-bottom:8px;padding:8px 12px;background:#fef3c7;border-radius:4px;font-size:12px;color:#92400e;">✅ 详情跳转测试完成，共 ' + itemsDj.length + ' 条</div>';
            for (var di = 0; di < Math.min(itemsDj.length, 3); di++) {
              htmlDj += '<div style="margin:8px 0;padding:8px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;"><strong style="font-size:12px;">详情 ' + (di + 1) + ':</strong><pre style="font-size:11px;margin-top:6px;background:#fff;padding:6px;border-radius:4px;white-space:pre-wrap;word-break:break-all;">' +
                JSON.stringify(itemsDj[di], null, 2).replace(/</g, "&lt;") + '</pre></div>';
            }
            htmlDj += "</div>";
            results.innerHTML = htmlDj;
            state.upstreamCache = state.upstreamCache || {};
            state.upstreamCache.items = itemsDj;
          } else if (step.step_type === "page_access" && data.data && data.data.output) {
            var outPa = data.data.output;
            var srcBadge2 = "";
            var src2 = outPa.source_type || (outPa.use_render ? "js_render" : "http");
            if (src2 === "js_render") srcBadge2 = '<span style="background:#2563eb;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">⚡ JS 渲染</span>';
            else if (src2 === "http_fallback") srcBadge2 = '<span style="background:#f59e0b;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">🔄 HTTP 回退</span>';
            else if (src2 === "http") srcBadge2 = '<span style="background:#6b7280;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">📡 HTTP 请求</span>';
            var htmlPa = '<div style="padding:10px;">';
            htmlPa += '<div style="margin-bottom:10px;padding:10px 12px;background:#dbeafe;border-radius:4px;font-size:12px;color:#1e40af;">' +
              srcBadge2 + ' <strong>✅ 页面访问成功</strong>' +
              '</div>';
            htmlPa += '<div style="padding:10px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;">' +
              '<strong>URL:</strong> ' + (outPa.url || outPa.final_url || "(未设置)").replace(/</g, "&lt;") + '<br/>' +
              '<strong>状态码:</strong> ' + (outPa.status_code || "(无)") + '　' +
              '<strong>HTML 大小:</strong> ' + (outPa.html_length || String(outPa.html_preview ? outPa.html_preview.length : 0)) + ' 字符<br/>' +
              (outPa.title ? '<strong>页面标题:</strong> ' + String(outPa.title).replace(/</g, "&lt;") : '') +
              "</div>";
            if (outPa.html_preview) {
              htmlPa += '<div style="margin-top:10px;padding:8px;background:white;border:1px solid #d1d5db;border-radius:4px;max-height:200px;overflow:auto;font-size:11px;">' +
                '<div style="font-weight:bold;color:#374151;margin-bottom:4px;">📄 HTML 预览:</div>' +
                String(outPa.html_preview).replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br/>") +
                "</div>";
            }
            htmlPa += "</div>";
            results.innerHTML = htmlPa;
            state.upstreamCache = state.upstreamCache || {};
            state.upstreamCache.html_preview = outPa.html_preview;
            state.upstreamCache.url = outPa.url || outPa.final_url;
            state.upstreamCache.html_length = outPa.html_length || outPa.html_preview.length;
            state.upstreamCache.source_type = src2;
          } else {
            results.innerHTML = '<pre style="background:#f8fafc;padding:8px;border-radius:4px;font-size:12px;overflow:auto;max-height:300px;">' +
              JSON.stringify(data.data || {}, null, 2).replace(/</g, "&lt;") + '</pre>';
          }
        }
        if (summary) summary.style.display = "block";
        step.test_result = data.data;
        toast("测试通过", "success");
      } else {
        toast("测试失败：" + ((data || {}).msg || ""), "error");
      }
    }).catch(function (err) { toast("测试异常：" + err, "error"); });
  }

  function doIncrementalTest() {
    if (state.steps.length === 0) { toast("请先添加步骤", "warn"); return; }
    toast("正在执行增量测试...", "info");
    api("/api/admin/crawl/steps/full-test-incremental", "POST", {
      steps: state.steps.map(function (s, i) {
        return { step_id: s.step_id, step_order: i + 1, step_type: s.step_type, config: s.config, title: s.title };
      }),
    }).then(function (data) {
      if (data && data.code === 0) {
        // 显示详细结果
        renderFullTestResult(data.data, "增量测试");
      } else {
        toast("测试失败：" + ((data || {}).msg || ""), "error");
      }
    }).catch(function (err) { toast("测试异常：" + err, "error"); });
  }

  function doTestFull() {
    if (state.steps.length === 0) { toast("请先添加步骤", "warn"); return; }
    // 打开浮层显示测试中状态
    var mask = document.getElementById("full-test-modal-mask");
    var body = document.getElementById("full-test-modal-body");
    if (mask && body) {
      mask.style.display = "block";
      body.innerHTML = '<div class="muted" style="padding:40px;text-align:center;"><div style="font-size:18px;margin-bottom:8px;">⚙️ 正在执行全链路测试...</div><div style="color:#64748b;font-size:13px;">请稍候，测试将按顺序执行每个步骤</div></div>';
      document.getElementById("full-test-modal-foot").textContent = "执行中...";
    }
    // 构造请求体：
    // 只有当 state.loadedHtml 确实对应 page_access 步骤的 URL 时，才作为 preloaded_html 传递
    // 其他情况（如用户在浏览器预览了详情页、或 state.loadedHtml 为空），不传递，
    // 让后端按步骤独立抓取。这样避免 detail_jump 的 HTML 被错误注入到 list_detect。
    var testPayload = {
      package: {
        steps: state.steps.map(function (s, i) {
          return { step_id: s.step_id, step_order: i + 1, step_type: s.step_type, config: s.config, title: s.title };
        })
      }
    };
    var pageAccessStep = state.steps.find(function (s) { return s.step_type === "page_access"; });
    var pageAccessUrl = (pageAccessStep && pageAccessStep.config) ? (pageAccessStep.config.url || "") : "";
    var currentUrl = (document.getElementById("crawl-url-input") || {}).value || "";
    // 只有当：1) loadedHtml 存在；2) 当前浏览器 URL 与 page_access 步骤 URL 一致（或 page_access URL 为空但我们正在初始化）
    if (state.loadedHtml && String(state.loadedHtml).trim().length > 10 &&
        (pageAccessUrl === currentUrl || !pageAccessUrl)) {
      testPayload.preloaded_html = state.loadedHtml;
      for (var ki = 0; ki < state.steps.length; ki++) {
        if (state.steps[ki].step_type === "page_access") {
          state.steps[ki].config = state.steps[ki].config || {};
          state.steps[ki].config._using_preloaded = true;
        }
      }
    }
    var rpStep = state.steps.find(function(s) { return s.step_type === "result_preview"; });
    console.log("[doTestFull] result_preview config:", rpStep ? rpStep.config : null);
    console.log("[doTestFull] preview_count:", rpStep ? rpStep.config.preview_count : null);
    
    var maxItems = rpStep ? rpStep.config.preview_count : null;
    if (maxItems) {
      testPayload.max_items = maxItems;
      console.log("[doTestFull] setting max_items to preview_count:", maxItems);
    }
    
    api("/api/admin/crawl/steps/full-test", "POST", testPayload).then(function (data) {
      if (data && data.code === 0) {
        renderFullTestResult(data.data, "全链路测试");
      } else {
        var err = ((data || {}).msg || "未知错误");
        var bodyEl = document.getElementById("full-test-modal-body");
        if (bodyEl) {
          bodyEl.innerHTML = '<div style="padding:24px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;"><div style="color:#dc2626;font-weight:bold;margin-bottom:8px;">❌ 测试失败</div><div style="color:#991b1b;font-size:13px;">' + err.replace(/</g, "&lt;") + '</div></div>';
          document.getElementById("full-test-modal-foot").textContent = "测试失败";
        }
        toast("测试失败：" + err, "error");
      }
    }).catch(function (err) {
      var bodyEl2 = document.getElementById("full-test-modal-body");
      if (bodyEl2) {
        bodyEl2.innerHTML = '<div style="padding:24px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;"><div style="color:#dc2626;font-weight:bold;margin-bottom:8px;">❌ 测试异常</div><div style="color:#991b1b;font-size:13px;">' + String(err).replace(/</g, "&lt;") + '</div></div>';
      }
      toast("测试异常：" + err, "error");
    });
  }

  function closeFullTest() {
    var mask = document.getElementById("full-test-modal-mask");
    if (mask) mask.style.display = "none";
  }

  function renderFullTestResult(result, title) {
    var mask = document.getElementById("full-test-modal-mask");
    var body = document.getElementById("full-test-modal-body");
    var foot = document.getElementById("full-test-modal-foot");
    var titleEl = document.getElementById("full-test-modal-title");
    if (!mask || !body) {
      toast(title + "完成", "success");
      return;
    }
    mask.style.display = "block";
    titleEl.textContent = "🔗 " + title + "结果";

    var steps = result && result.steps ? result.steps : [];
    var success = result && result.success;
    var duration = (result && result.duration_ms) || 0;
    var finalItems = result && result.final_items;
    var totalSteps = steps.length;
    var successSteps = steps.filter(function (s) { return s.success; }).length;

    var html = "";

    // ============= 顶部摘要 =============
    var statusColor = success ? "#16a34a" : "#dc2626";
    var statusIcon = success ? "✅" : "⚠️";
    var statusText = success ? "测试成功" : "部分步骤失败";
    html += '<div style="padding:16px 20px;background:#f8fafc;border-radius:8px;margin-bottom:16px;border:1px solid #e2e8f0;">';
    html += '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">';
    html += '<div style="font-size:24px;">' + statusIcon + '</div>';
    html += '<div style="flex:1;min-width:200px;">';
    html += '<div style="font-weight:bold;font-size:16px;color:' + statusColor + ';">' + statusText + '</div>';
    html += '<div style="font-size:13px;color:#475569;margin-top:4px;">共 ' + totalSteps + ' 个步骤，成功 ' + successSteps + ' 个，总耗时 ' + (duration / 1000).toFixed(2) + ' 秒</div>';
    html += '</div>';
    html += '</div>';
    html += '</div>';

    // ============= 各步骤详细结果 =============
    html += '<div style="margin-bottom:16px;">';
    html += '<div style="font-weight:bold;color:#1e293b;margin-bottom:8px;font-size:14px;">📋 各步骤执行结果</div>';

    function esc(s) { return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function stripHtml(s) { return String(s == null ? "" : s).replace(/<[^>]+>/g, "").trim(); }
    function objField(item, names) {
      for (var i = 0; i < names.length; i++) {
        if (item && typeof item === "object" && item[names[i]] != null && String(item[names[i]]).trim() !== "") return String(item[names[i]]);
      }
      return "";
    }

    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      var stepOk = step.success;
      var stepIcon = stepOk ? "✅" : "❌";
      var stepColor = stepOk ? "#16a34a" : "#dc2626";
      var stepBg = stepOk ? "#f0fdf4" : "#fef2f2";
      var stepBorder = stepOk ? "#bbf7d0" : "#fecaca";

      html += '<div style="margin-bottom:10px;background:' + stepBg + ';border:1px solid ' + stepBorder + ';border-radius:6px;padding:12px 14px;">';
      html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;">';
      html += '<span style="font-size:18px;">' + stepIcon + '</span>';
      html += '<span style="font-weight:bold;color:#1e293b;">步骤 ' + (i + 1) + ': ' + esc(step.step_title || step.step_type) + '</span>';
      html += '<span style="font-size:11px;color:#64748b;background:white;padding:2px 8px;border-radius:10px;margin-left:auto;">' + ((step.duration_ms || 0) / 1000).toFixed(2) + 's</span>';
      html += '</div>';

      if (step.message) {
        html += '<div style="font-size:13px;color:' + stepColor + ';margin-bottom:10px;padding:6px 10px;background:white;border-radius:4px;border-left:3px solid ' + stepColor + ';">💬 ' + esc(step.message) + '</div>';
      }

      // ============= 按步骤类型渲染详细输出 =============
      var out = step.output || {};
      if (typeof out === "object" && out !== null) {
        var type = step.step_type;

        // -------- 1) page_access：URL、状态码、HTML 大小、JS 渲染状态 --------
        if (type === "page_access") {
          var url = out.final_url || out.url || "";
          if (url) {
            html += '<div style="font-size:12px;margin:6px 0;padding:6px 10px;background:white;border-radius:4px;border:1px solid #e2e8f0;">';
            html += '<span style="display:inline-block;font-weight:bold;color:#3b82f6;margin-right:6px;">🔗 抓取目标：</span>';
            html += '<span style="color:#1e40af;">' + esc(url) + '</span>';
            html += '</div>';
          }
          // JS 渲染状态标签
          var srcRt = out.source_type || (out.use_render ? "js_render" : "http");
          var rtBadge = "";
          if (srcRt === "js_render") rtBadge = '<span style="background:#2563eb;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">⚡ JS 渲染</span>';
          else if (srcRt === "http_fallback") rtBadge = '<span style="background:#f59e0b;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">🔄 HTTP 回退</span>';
          else if (srcRt === "http") rtBadge = '<span style="background:#6b7280;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">📡 HTTP 请求</span>';
          else if (srcRt === "external_html") rtBadge = '<span style="background:#06b6d4;color:white;padding:3px 8px;border-radius:10px;font-size:11px;">📥 外部 HTML</span>';
          html += '<div style="font-size:12px;margin:4px 0 8px;color:#475569;">' +
            (rtBadge ? rtBadge + '　' : '') +
            (out.status_code ? '📡 状态码: ' + esc(out.status_code) + '　' : '') +
            (out.html_length ? '📦 HTML: ' + esc(out.html_length) + ' 字符' : (out.html_preview ? '📦 HTML: ' + String(out.html_preview.length) + ' 字符' : '')) +
            (out.title ? '　📖 标题: ' + esc(String(out.title).slice(0, 50)) : '') +
            '</div>';
          if (out.html_preview && out.html_preview.trim()) {
            var previewText = stripHtml(out.html_preview);
            var previewLen = previewText.length;
            var showLen = 2000;
            var isLong = previewLen > showLen;
            var expandBtnId = "pf-pa-" + i;
            if (previewText && previewText.trim()) {
              html += '<div style="font-size:11px;margin-top:8px;padding:8px 10px;background:white;border-radius:4px;border:1px solid #cbd5e1;max-height:260px;overflow:auto;">';
              html += '<div style="font-weight:bold;color:#1e293b;margin-bottom:4px;">📄 页面文本预览（' + previewLen + ' 字符）：</div>';
              if (isLong) {
                html += '<div id="' + expandBtnId + '-vis" style="color:#334155;line-height:1.6;white-space:pre-wrap;word-break:break-word;">' +
                  esc(previewText.substring(0, showLen)) +
                  ' <a href="#" onclick="var v=document.getElementById(\'' + expandBtnId + '-vis\');var m=document.getElementById(\'' + expandBtnId + '-more\');v.style.display=v.style.display===\'none\'?\'inline\':\'none\';m.style.display=m.style.display===\'none\'?\'inline\':\'none\';return false;" style="color:#2563eb;font-weight:bold;text-decoration:underline;">▼ 展开完整内容</a>' +
                  '</div>';
                html += '<div id="' + expandBtnId + '-more" style="display:none;color:#334155;line-height:1.6;white-space:pre-wrap;word-break:break-word;">' +
                  esc(previewText.substring(showLen)) +
                  ' <a href="#" onclick="var v=document.getElementById(\'' + expandBtnId + '-vis\');var m=document.getElementById(\'' + expandBtnId + '-more\');v.style.display=v.style.display===\'none\'?\'inline\':\'none\';m.style.display=m.style.display===\'none\'?\'inline\':\'none\';return false;" style="color:#2563eb;font-weight:bold;text-decoration:underline;">▲ 收起</a>' +
                  '</div>';
              } else {
                html += '<div style="color:#334155;line-height:1.6;white-space:pre-wrap;word-break:break-word;">' + esc(previewText) + '</div>';
              }
              html += '</div>';
            }
          } else if (!out.html_preview || out.html_preview.trim() === "") {
            html += '<div style="font-size:11px;margin-top:6px;padding:6px 10px;background:#fef3c7;border-radius:4px;border:1px solid #f59e0b;color:#92400e;">⚠️ 没有抓取到 HTML 内容，请检查 URL 是否可访问，或启用 JavaScript 渲染</div>';
          }
        }

        // -------- 2) list_detect：识别到的表格/列表内容 --------
        else if (type === "list_detect") {
          var items = out.items || [];
          var containers = out.containers || [];
          if (containers.length > 0) {
            html += '<div style="font-size:12px;color:#475569;margin-bottom:6px;padding:6px 10px;background:white;border-radius:4px;border:1px solid #e2e8f0;">';
            html += '<strong>🧺 识别到 ' + containers.length + ' 个候选容器，从中提取出 ' + items.length + ' 条记录</strong>';
            html += '</div>';
          }
          if (items.length > 0) {
            // 构造简单表格：第一行表头（keys），之后每行展示内容
            var first = items[0];
            var displayKeys = [];
            if (typeof first === "object" && first !== null) {
              for (var k in first) {
                if (k && !k.startsWith("_") && typeof first[k] !== "object") {
                  displayKeys.push(k);
                }
              }
            }
            if (displayKeys.length === 0) {
              displayKeys = ["title", "text", "link", "url", "name"];
            }

            var showCount = Math.min(items.length, 10);
            html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;"><strong>📋 记录（显示前 ' + showCount + ' 条 / 共 ' + items.length + ' 条）：</strong></div>';

            // 以"卡片列表"形式展示，每条记录一张卡片
            for (var j = 0; j < showCount; j++) {
              var itm = items[j];
              if (typeof itm === "string") {
                html += '<div style="font-size:12px;padding:6px 10px;background:white;border-radius:4px;margin-bottom:4px;border:1px solid #e2e8f0;">' + esc(itm) + '</div>';
              } else if (typeof itm === "object" && itm !== null) {
                html += '<div style="padding:8px 10px;background:white;border-radius:4px;margin-bottom:4px;border:1px solid #cbd5e1;border-left:3px solid #10b981;">';
                html += '<div style="font-size:11px;color:#059669;font-weight:bold;margin-bottom:4px;"># ' + (j + 1) + '</div>';
                var gotAny = false;
                // 关键字段优先展示
                var primaryLink = objField(itm, ["link", "url", "href"]);
                if (primaryLink) {
                  html += '<div style="font-size:11px;color:#1e40af;margin-bottom:3px;word-break:break-all;">🔗 ' + esc(primaryLink) + '</div>';
                }
                var primaryTitle = objField(itm, ["title", "text", "name", "headline"]);
                if (primaryTitle) {
                  var pt = String(primaryTitle);
                  if (pt.length > 120) pt = pt.substring(0, 120) + "...";
                  html += '<div style="font-size:12px;color:#1e293b;margin-bottom:3px;font-weight:500;">📝 ' + esc(pt) + '</div>';
                  gotAny = true;
                }
                // 其他字段
                for (var dk = 0; dk < displayKeys.length; dk++) {
                  var dkk = displayKeys[dk];
                  if (["link", "url", "href", "title", "text", "name", "headline"].indexOf(dkk) === -1 &&
                      itm[dkk] != null && String(itm[dkk]).trim() !== "") {
                    var val = String(itm[dkk]);
                    if (val.length > 80) val = val.substring(0, 80) + "...";
                    html += '<div style="font-size:11px;color:#475569;margin-bottom:2px;"><span style="color:#64748b;">' + esc(dkk) + '：</span>' + esc(val) + '</div>';
                    gotAny = true;
                  }
                }
                if (!gotAny) {
                  var jsonStr = JSON.stringify(itm);
                  if (jsonStr.length > 120) jsonStr = jsonStr.substring(0, 120) + "...";
                  html += '<div style="font-size:11px;color:#475569;">' + esc(jsonStr) + '</div>';
                }
                html += '</div>';
              }
            }
            if (items.length > showCount) {
              html += '<div style="font-size:11px;color:#64748b;text-align:center;padding:4px;">... 还有 ' + (items.length - showCount) + ' 条记录未展示</div>';
            }
          } else {
            html += '<div style="font-size:12px;color:#64748b;padding:8px;background:white;border-radius:4px;border:1px dashed #cbd5e1;text-align:center;">未识别到记录（请检查选择器或在页面访问中抓取更完整的 HTML）</div>';
          }
        }

        // -------- 3) detail_jump：每条记录的详情页 URL 和内容 --------
        else if (type === "detail_jump") {
          var detailItems = out.items || [];
          if (detailItems.length > 0) {
            html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;"><strong>📄 详情页记录（' + detailItems.length + ' 条）</strong></div>';
            for (var di = 0; di < Math.min(detailItems.length, 5); di++) {
              var ditm = detailItems[di];
              if (!ditm || typeof ditm !== "object") continue;
              html += '<div style="padding:8px 10px;background:white;border-radius:4px;margin-bottom:5px;border:1px solid #cbd5e1;border-left:3px solid #0ea5e9;">';
              html += '<div style="font-size:11px;color:#0284c7;font-weight:bold;margin-bottom:4px;"># ' + (di + 1) + '</div>';
              // 详情页 URL
              var detailUrl = ditm._source_url || ditm.link || ditm.url || "";
              if (detailUrl) {
                html += '<div style="font-size:11px;color:#1e40af;margin-bottom:4px;word-break:break-all;">🔗 URL：' + esc(detailUrl) + '</div>';
              }
              // 状态码
              if (ditm._page_status) {
                html += '<div style="font-size:11px;color:#475569;margin-bottom:4px;">📡 状态码：' + esc(ditm._page_status) + '</div>';
              }
              // 页面内容预览
              if (ditm._page_preview) {
                var dp = String(ditm._page_preview);
                if (dp.length > 200) dp = dp.substring(0, 200) + "...";
                html += '<div style="font-size:11px;color:#334155;background:#f8fafc;padding:6px 8px;border-radius:3px;margin-top:4px;white-space:pre-wrap;word-break:break-word;">📄 ' + esc(dp) + '</div>';
              }
              // 其他提取字段（除去 _前缀）
              var extraKeysShown = 0;
              for (var ek in ditm) {
                if (ek && ek.charAt(0) !== "_" && ["link", "url"].indexOf(ek) === -1 &&
                    ditm[ek] != null && String(ditm[ek]).trim() !== "" && extraKeysShown < 5) {
                  var eval2 = String(ditm[ek]);
                  if (eval2.length > 80) eval2 = eval2.substring(0, 80) + "...";
                  html += '<div style="font-size:11px;color:#475569;margin-top:2px;"><span style="color:#64748b;">' + esc(ek) + '：</span>' + esc(eval2) + '</div>';
                  extraKeysShown++;
                }
              }
              html += '</div>';
            }
            if (detailItems.length > 5) {
              html += '<div style="font-size:11px;color:#64748b;text-align:center;padding:4px;">... 还有 ' + (detailItems.length - 5) + ' 条记录未展示</div>';
            }
          } else {
            html += '<div style="font-size:12px;color:#64748b;padding:8px;background:white;border-radius:4px;border:1px dashed #cbd5e1;text-align:center;">无详情页数据（上游步骤未识别到记录或 URL 为空）</div>';
          }
        }

        // -------- 4) attachment_parse：附件 URL、文件信息、解析内容 --------
        else if (type === "attachment_parse") {
          var atts = out.attachments || out.results || [];
          var attUrls = out.attachment_urls || [];
          if (atts.length > 0 || attUrls.length > 0) {
            html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;"><strong>📎 附件解析：共 ' + (atts.length || attUrls.length) + ' 个文件</strong></div>';
            // 如果只有 URL 但没有解析结果
            if (atts.length === 0 && attUrls.length > 0) {
              html += '<div style="font-size:11px;color:#64748b;padding:6px 10px;background:white;border-radius:4px;border:1px solid #e2e8f0;">';
              html += '<strong style="color:#475569;">📝 发现的附件链接（未成功解析内容）：</strong><br>';
              for (var ui = 0; ui < attUrls.length; ui++) {
                html += '<div style="margin:3px 0;color:#1e40af;word-break:break-all;">· ' + esc(attUrls[ui]) + '</div>';
              }
              html += '</div>';
            }
            for (var ai = 0; ai < Math.min(atts.length, 3); ai++) {
              var att = atts[ai];
              if (!att) continue;
              var attName = att.filename || att.source_url || ("附件 " + (ai + 1));
              var attUrl = att.source_url || "";
              var attType = att.mime_type || att.file_type || "未知";
              var attSize = att.file_size_bytes || 0;
              var attText = att.text || "";
              var attTables = att.tables || [];

              html += '<div style="padding:10px 12px;background:white;border-radius:6px;margin-bottom:6px;border:1px solid #cbd5e1;border-left:3px solid #f59e0b;">';
              html += '<div style="font-size:11px;color:#b45309;font-weight:bold;margin-bottom:6px;">📄 #' + (ai + 1) + ' ' + esc(attName) + '</div>';
              if (attUrl) {
                html += '<div style="font-size:11px;color:#1e40af;margin-bottom:3px;word-break:break-all;">🔗 ' + esc(attUrl) + '</div>';
              }
              html += '<div style="font-size:11px;color:#475569;margin-bottom:3px;">📦 类型: ' + esc(attType) + (attSize ? ' | 大小: ' + esc(attSize) + ' 字节' : '') + (att.parse_status ? ' | 状态: ' + esc(att.parse_status) : '') + '</div>';

              if (attText) {
                var textShow = String(attText);
                if (textShow.length > 300) textShow = textShow.substring(0, 300) + "... (已截断，共 " + String(attText).length + " 字符)";
                html += '<div style="font-size:11px;color:#334155;background:#fefce8;padding:6px 8px;border-radius:4px;margin-top:6px;white-space:pre-wrap;word-break:break-word;">';
                html += '<strong style="color:#78350f;">📝 解析文本：</strong><br>';
                html += esc(textShow);
                html += '</div>';
              }

              if (attTables && attTables.length > 0) {
                for (var ti = 0; ti < Math.min(attTables.length, 2); ti++) {
                  var tbl = attTables[ti];
                  var headers = tbl.headers || [];
                  var rows = tbl.rows || [];
                  if (rows.length > 0) {
                    html += '<div style="font-size:11px;color:#334155;margin-top:6px;background:#f0f9ff;padding:6px 8px;border-radius:4px;">';
                    html += '<strong style="color:#1e40af;">📊 表格 ' + (ti + 1) + '（' + rows.length + ' 行）：</strong>';
                    // 展示为简易 HTML 表格
                    html += '<table style="border-collapse:collapse;margin-top:4px;font-size:10px;width:100%;">';
                    // 表头
                    if (headers.length > 0) {
                      html += '<tr>';
                      for (var hdi = 0; hdi < Math.min(headers.length, 8); hdi++) {
                        html += '<th style="border:1px solid #bfdbfe;padding:3px 6px;background:#dbeafe;color:#1e40af;font-weight:bold;text-align:left;">' + esc(headers[hdi]) + '</th>';
                      }
                      html += '</tr>';
                    }
                    // 前 5 行数据
                    for (var tri = 0; tri < Math.min(rows.length, 5); tri++) {
                      var r = rows[tri];
                      html += '<tr>';
                      var rowArr = Array.isArray(r) ? r : (typeof r === "object" && r !== null ? Object.values(r) : [String(r)]);
                      var cellCount = Math.min(rowArr.length, headers.length > 0 ? headers.length : 8);
                      for (var tci = 0; tci < cellCount; tci++) {
                        var cell = rowArr[tci];
                        var cv = cell == null ? "" : String(cell);
                        if (cv.length > 40) cv = cv.substring(0, 40) + "...";
                        html += '<td style="border:1px solid #e0f2fe;padding:3px 6px;color:#334155;">' + esc(cv) + '</td>';
                      }
                      html += '</tr>';
                    }
                    html += '</table>';
                    if (rows.length > 5) {
                      html += '<div style="font-size:10px;color:#64748b;margin-top:3px;">... 还有 ' + (rows.length - 5) + ' 行未展示</div>';
                    }
                    html += '</div>';
                  }
                }
              }

              if (!attText && (!attTables || attTables.length === 0)) {
                html += '<div style="font-size:11px;color:#a16207;padding:4px 6px;background:#fef3c7;border-radius:3px;margin-top:4px;">⚠️ 未解析出文本或表格内容（可能下载失败或格式不支持）</div>';
              }
              if (att.error) {
                html += '<div style="font-size:11px;color:#b91c1c;padding:4px 6px;background:#fee2e2;border-radius:3px;margin-top:4px;">❌ 错误: ' + esc(String(att.error).substring(0, 100)) + '</div>';
              }

              html += '</div>';
            }
            if (atts.length > 3) {
              html += '<div style="font-size:11px;color:#64748b;text-align:center;padding:4px;">... 还有 ' + (atts.length - 3) + ' 个附件未展示</div>';
            }
          } else {
            html += '<div style="font-size:12px;color:#64748b;padding:8px;background:white;border-radius:4px;border:1px dashed #cbd5e1;text-align:center;">未发现可解析的附件</div>';
          }
        }

        // -------- 5) field_mapping：每条记录的完整字段映射 --------
        else if (type === "field_mapping") {
          var mpItems = out.mapped_items || out.items || [];
          if (mpItems.length > 0) {
            html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;"><strong>🔀 字段映射结果：' + mpItems.length + ' 条记录</strong></div>';
            for (var mi = 0; mi < Math.min(mpItems.length, 5); mi++) {
              var mitm = mpItems[mi];
              if (mitm == null) continue;
              html += '<div style="padding:8px 12px;background:white;border-radius:4px;margin-bottom:5px;border:1px solid #cbd5e1;border-left:3px solid #a855f7;">';
              html += '<div style="font-size:11px;color:#7c3aed;font-weight:bold;margin-bottom:6px;">📋 记录 ' + (mi + 1) + '</div>';
              if (typeof mitm === "object" && mitm !== null) {
                var showCount2 = 0;
                for (var mk in mitm) {
                  if (mk && mk.charAt(0) !== "_" && mitm[mk] != null && showCount2 < 15) {
                    var mval = String(mitm[mk]);
                    if (mval.length > 120) mval = mval.substring(0, 120) + "...";
                    html += '<div style="font-size:11px;margin-bottom:2px;"><span style="display:inline-block;min-width:80px;color:#64748b;font-weight:500;">' + esc(mk) + '：</span><span style="color:#1e293b;word-break:break-word;">' + esc(mval) + '</span></div>';
                    showCount2++;
                  }
                }
              } else {
                html += '<div style="font-size:11px;color:#475569;">' + esc(String(mitm)) + '</div>';
              }
              html += '</div>';
            }
            if (mpItems.length > 5) {
              html += '<div style="font-size:11px;color:#64748b;text-align:center;padding:4px;">... 还有 ' + (mpItems.length - 5) + ' 条记录未展示</div>';
            }
          } else {
            html += '<div style="font-size:12px;color:#64748b;padding:8px;background:white;border-radius:4px;border:1px dashed #cbd5e1;text-align:center;">无映射数据</div>';
          }
        }

        // -------- 6) result_preview --------
        else if (type === "result_preview") {
          var rpItems = out.items || [];
          var rpAtts = out.attachments || [];
          var rpLimit = out.sample_size || 50;
          if (rpItems.length > 0 || rpAtts.length > 0) {
            html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;"><strong>📊 最终预览：' + rpItems.length + ' 条记录 / ' + rpAtts.length + ' 个附件（上限 ' + rpLimit + ' 条）</strong></div>';
            var rpShow = Math.min(rpItems.length, rpLimit);
            for (var rpi = 0; rpi < rpShow; rpi++) {
              var rpitm = rpItems[rpi];
              html += '<div style="padding:8px 12px;background:white;border-radius:4px;margin-bottom:5px;border:1px solid #bbf7d0;">';
              html += '<div style="font-size:11px;color:#15803d;font-weight:bold;margin-bottom:4px;">📋 记录 ' + (rpi + 1) + '</div>';
              var rps = typeof rpitm === "string" ? rpitm : JSON.stringify(rpitm, null, 2);
              if (rps.length > 500) rps = rps.substring(0, 500) + "\n... (已截断)";
              html += '<pre style="font-size:11px;color:#1e293b;margin:0;white-space:pre-wrap;word-break:break-word;">' + esc(rps) + '</pre>';
              html += '</div>';
            }
            if (rpItems.length > rpShow) {
              html += '<div style="font-size:11px;color:#64748b;text-align:center;padding:4px;">... 还有 ' + (rpItems.length - rpShow) + ' 条记录未展示</div>';
            }
          } else {
            html += '<div style="font-size:12px;color:#475569;"><strong>📊 结果预览配置已验证（上游步骤无数据，或当前步骤无 items 输出）</strong></div>';
          }
        }

        // -------- 其他类型：通用输出 --------
        else {
          var otherKeys = Object.keys(out);
          if (otherKeys.length > 0) {
            html += '<div style="font-size:12px;color:#475569;padding:6px 10px;background:white;border-radius:4px;border:1px solid #e2e8f0;">';
            html += '<strong>📤 输出字段：</strong><br>';
            for (var ok = 0; ok < otherKeys.length; ok++) {
              var ov = out[otherKeys[ok]];
              var ovStr = typeof ov === "string" ? ov : JSON.stringify(ov);
              if (ovStr.length > 80) ovStr = ovStr.substring(0, 80) + "...";
              html += '<div style="font-size:11px;margin-top:3px;color:#334155;">· <span style="color:#64748b;">' + esc(otherKeys[ok]) + '：</span>' + esc(ovStr) + '</div>';
            }
            html += '</div>';
          }
        }
      }

      html += '</div>';
    }
    html += '</div>';

    // ============= 最终抓取内容 =============
    function renderFinalRecords(itemsArr) {
      if (!itemsArr || itemsArr.length === 0) return "";
      // 从 result_preview 步骤获取 preview_count 作为展示上限
      var finalLimit = 50;
      for (var si = 0; si < steps.length; si++) {
        if (steps[si].step_type === "result_preview" && steps[si].output) {
          finalLimit = steps[si].output.sample_size || finalLimit;
          break;
        }
      }
      var out = "";
      var showCount = Math.min(itemsArr.length, finalLimit);
      for (var fi = 0; fi < showCount; fi++) {
        var fitem = itemsArr[fi];
        var fstr = typeof fitem === "string" ? fitem : JSON.stringify(fitem, null, 2);
        if (fstr.length > 500) fstr = fstr.substring(0, 500) + "\n... (已截断)";
        out += '<div style="padding:10px 12px;background:white;border-radius:6px;margin-bottom:6px;border:1px solid #dcfce7;">';
        out += '<div style="font-size:11px;color:#15803d;margin-bottom:4px;font-weight:bold;">📋 记录 ' + (fi + 1) + '</div>';
        out += '<pre style="font-size:12px;color:#1e293b;margin:0;white-space:pre-wrap;word-break:break-all;">' + esc(fstr) + '</pre>';
        out += '</div>';
      }
      if (itemsArr.length > showCount) {
        out += '<div style="font-size:12px;color:#64748b;text-align:center;margin-top:6px;">... 还有 ' + (itemsArr.length - showCount) + ' 条记录未展示</div>';
      }
      return out;
    }

    var finalArr = null;
    if (Array.isArray(finalItems)) finalArr = finalItems;
    else if (finalItems && typeof finalItems === "object") {
      if (Array.isArray(finalItems.items) && finalItems.items.length > 0) finalArr = finalItems.items;
      else if (Array.isArray(finalItems.mapped_items) && finalItems.mapped_items.length > 0) finalArr = finalItems.mapped_items;
    }
    if (!finalArr && steps.length > 0) {
      var lastS = steps[steps.length - 1];
      var lastO = lastS.output || {};
      if (lastO.items && lastO.items.length > 0) finalArr = lastO.items;
      else if (lastO.mapped_items && lastO.mapped_items.length > 0) finalArr = lastO.mapped_items;
    }

    if (finalArr && finalArr.length > 0) {
      html += '<div style="margin-top:16px;padding:16px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;">';
      html += '<div style="font-weight:bold;color:#166534;margin-bottom:10px;font-size:15px;">🎯 最终抓取内容（共 ' + finalArr.length + ' 条）</div>';
      html += renderFinalRecords(finalArr);
      html += '</div>';
    }

    body.innerHTML = html;
    if (foot) {
      foot.textContent = "测试完成 - " + title;
    }
    toast(title + "完成", "success");
  }

  // ============================================================ 保存与版本管理

  function doSave() {
    if (state.steps.length === 0) { toast("请先添加步骤", "warn"); return; }
    var planName = (document.getElementById("crawl-plan-name") || {}).value || "未命名方案";
    toast("正在保存方案...", "info");
    var savePayload = {
      plan_id: state.planId || null,
      plan_name: planName,
      steps: state.steps.map(function (s) { return { step_type: s.step_type, config: s.config, title: s.title }; }),
      config: state.planConfig,
    };
    api("/api/admin/crawl/steps/save-plan", "POST", savePayload).then(function (data) {
      if (data && data.code === 0) {
        state.planId = data.data.plan_id;
        document.getElementById("crawl-plan-name").value = planName;
        toast("保存成功，方案 ID: " + state.planId, "success");
      } else {
        toast("保存失败：" + ((data || {}).msg || ""), "error");
      }
    }).catch(function (err) { toast("保存异常：" + err, "error"); });
  }

  function openVersionModal() {
    var mask = document.getElementById("version-modal-mask");
    if (mask) mask.style.display = "block";
    if (!state.planId) {
      var list = document.getElementById("version-modal-list");
      if (list) list.innerHTML = '<div class="muted" style="padding:24px;text-align:center;">（方案尚未保存，无历史版本）</div>';
      return;
    }
    toast("正在加载版本列表...", "info");
    api("/api/admin/crawl/steps/versions?plan_id=" + encodeURIComponent(state.planId), "GET")
      .then(function (data) {
        if (data && data.code === 0) {
          var list = document.getElementById("version-modal-list");
          if (list) {
            var items = data.data.versions || [];
            if (items.length === 0) {
              list.innerHTML = '<div class="muted" style="padding:24px;text-align:center;">（暂无历史版本）</div>';
            } else {
              list.innerHTML = items.map(function (v) {
                return '<div class="version-item" style="padding:10px;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:8px;background:#fff;">' +
                  '<div><strong>版本 ' + v.version + '</strong> <span class="muted" style="font-size:12px;">' + (v.saved_at || "") + '</span></div>' +
                  '<div class="muted" style="font-size:12px;margin-top:4px;">步骤数: ' + (v.step_count || 0) + '</div>' +
                  '</div>';
              }).join("");
            }
          }
        } else {
          toast("加载版本失败：" + ((data || {}).msg || ""), "error");
        }
      }).catch(function (err) { toast("加载版本异常：" + err, "error"); });
  }

  function closeVersionModal() {
    var mask = document.getElementById("version-modal-mask");
    if (mask) mask.style.display = "none";
  }

  // ============================================================ 模板与加载

  function loadPackageFromDict(dict) {
    if (dict && dict.steps) {
      state.steps = dict.steps.map(function (s, i) {
        return {
          step_id: uid(),
          step_order: i,
          step_type: s.step_type,
          title: s.title || s.step_type,
          config: s.config || {},
        };
      });
    } else {
      state.steps = [];
    }
    // 自动选中第一个步骤，以便用户可以看到配置详情
    state.activeStepId = state.steps.length > 0 ? state.steps[0].step_id : null;
    // 自动填充 URL 输入框（从 page_access 步骤提取）
    for (var i = 0; i < state.steps.length; i++) {
      if (state.steps[i].step_type === "page_access" && state.steps[i].config && state.steps[i].config.url) {
        var urlInput = document.getElementById("crawl-url-input");
        if (urlInput) urlInput.value = state.steps[i].config.url;
        break;
      }
    }
    renderSteps();
    renderStepDetail();
    // 显示提示，告知用户方案已加载
    if (state.steps.length > 0) {
      toast("已加载方案，共 " + state.steps.length + " 个步骤", "info");
    }
  }

  function applyTemplate(templateId) {
    toast("正在应用模板...", "info");
    api("/api/admin/crawl/steps/template-apply", "POST", {
      template_id: templateId,
      plan_name: (document.getElementById("crawl-plan-name") || {}).value || "",
      spider_type: "generic_web",
    }).then(function (data) {
      if (data && data.code === 0) {
        loadPackageFromDict(data.data);
        var mask = document.getElementById("step-modal-mask");
        if (mask) mask.style.display = "none";
        toast("模板已应用", "success");
      } else {
        toast("模板应用失败：" + ((data || {}).msg || ""), "error");
      }
    }).catch(function (err) { toast("模板应用异常：" + err, "error"); });
  }

  // ============================================================ 暴露到全局作用域
  // 这些函数可以被 HTML onclick 属性直接调用

  window.crawlLoadPreview = function() { loadBrowserUrl(null, "GET"); };
  window.crawlGoBack = function() { browserBack(); };
  window.crawlGoForward = function() { browserForward(); };
  window.crawlReload = function() { loadBrowserUrl(null, "GET"); };
  window.crawlSetMode = function(mode) { setMode(mode); };
  window.crawlPickList = function() { setPickMode("list"); };
  window.crawlPickDetailLink = function() { setPickMode("detail_link"); };
  window.crawlPickTable = function() { setPickMode("table"); };
  window.crawlPreviewDetail = function(stepId) {
    var step = state.steps.find(function(s) { return s.step_id === stepId; });
    if (step && step.config && step.config.url) {
      document.getElementById("crawl-url-input").value = step.config.url;
      // previewOnly=true: 仅在浏览器预览，不修改 page_access 步骤的 URL（防止串扰）
      loadBrowserUrl(step.config.url, "GET", true);
    } else {
      toast("请先设置详情页 URL", "warn");
    }
  };
  window.crawlOpenModal = function() {
    var mask = document.getElementById("step-modal-mask");
    if (mask) mask.style.display = "block";
  };
  window.crawlCloseModal = function() {
    var mask = document.getElementById("step-modal-mask");
    if (mask) mask.style.display = "none";
  };
  window.crawlAddStep = function(stepType) {
    var idx = state.steps.findIndex(function (s) { return s.step_id === state.activeStepId; });
    var step = newStep(stepType, {}, idx >= 0 ? idx + 1 : state.steps.length);
    if (step) {
      renderSteps();
      activateStep(step.step_id);
      toast("已新增步骤：" + step.title, "success");
    }
    var mask = document.getElementById("step-modal-mask");
    if (mask) mask.style.display = "none";
  };
  window.crawlApplyTemplate = function(templateId) {
    applyTemplate(templateId);
  };
  window.crawlTestCurrent = function() {
    var active = state.steps.find(function (s) { return s.step_id === state.activeStepId; });
    doTestStep(active);
  };
  window.crawlTestIncremental = function() { doIncrementalTest(); };
  window.crawlTestFull = function() { doTestFull(); };
  window.crawlCloseFullTest = function() { closeFullTest(); };
  window.crawlSavePlan = function() { doSave(); };
  window.crawlShowVersions = function() { openVersionModal(); };
  window.crawlCloseVersions = function() { closeVersionModal(); };

  // --- 方案配置弹窗 ---
  function openPlanConfigModal() {
    var mask = document.getElementById("plan-config-modal-mask");
    if (mask) mask.style.display = "block";
    // 填充当前配置
    var domainInput = document.getElementById("crawl-config-target-domain");
    if (domainInput) domainInput.value = state.planConfig.target_domain || "";
    var maxItemsInput = document.getElementById("crawl-config-max-items");
    if (maxItemsInput) maxItemsInput.value = state.planConfig.max_items || 200;
    var cronInput = document.getElementById("crawl-config-cron");
    if (cronInput) cronInput.value = state.planConfig.cron || "";
    var middleCb = document.getElementById("crawl-config-save-middle-result");
    if (middleCb) middleCb.checked = !!state.planConfig.save_middle_result;
    var funnelCb = document.getElementById("crawl-config-funnel-visible");
    if (funnelCb) funnelCb.checked = !!state.planConfig.funnel_visible;
    var enableCleanCb = document.getElementById("crawl-config-enable-clean");
    if (enableCleanCb) enableCleanCb.checked = !!state.planConfig.enable_clean;
  }
  function closePlanConfigModal() {
    var mask = document.getElementById("plan-config-modal-mask");
    if (mask) mask.style.display = "none";
  }
  function doSavePlanConfig() {
    var domainInput = document.getElementById("crawl-config-target-domain");
    var maxItemsInput = document.getElementById("crawl-config-max-items");
    var cronInput = document.getElementById("crawl-config-cron");
    var middleCb = document.getElementById("crawl-config-save-middle-result");
    var funnelCb = document.getElementById("crawl-config-funnel-visible");
    var enableCleanCb = document.getElementById("crawl-config-enable-clean");
    state.planConfig.target_domain = domainInput ? (domainInput.value || "").trim() : state.planConfig.target_domain;
    var mi = parseInt((maxItemsInput ? maxItemsInput.value : "200"), 10);
    state.planConfig.max_items = isNaN(mi) ? 200 : mi;
    state.planConfig.cron = cronInput ? (cronInput.value || "").trim() : state.planConfig.cron;
    state.planConfig.save_middle_result = middleCb ? middleCb.checked : true;
    state.planConfig.funnel_visible = funnelCb ? funnelCb.checked : true;
    state.planConfig.enable_clean = enableCleanCb ? enableCleanCb.checked : true;

    // 保存到服务器（如果已保存过方案，则同步更新）
    if (state.planId) {
      toast("正在同步配置...", "info");
      api("/api/admin/crawl/plans/" + encodeURIComponent(state.planId) + "/update-config", "POST", { config: state.planConfig }).then(function (data) {
        if (data && data.code === 0) {
          toast("配置已保存", "success");
          closePlanConfigModal();
        } else {
          toast("保存失败：" + ((data || {}).msg || ""), "error");
        }
      }).catch(function (err) { toast("保存异常：" + err, "error"); });
    } else {
      toast("已更新本地配置，点击「保存方案」后同步到服务器", "info");
      closePlanConfigModal();
    }
  }
  window.crawlShowPlanConfig = function() { openPlanConfigModal(); };
  window.crawlClosePlanConfig = function() { closePlanConfigModal(); };
  window.crawlSavePlanConfig = function() { doSavePlanConfig(); };

  // --- PDF 附件处理 ---
  window.crawlAttachFileSelected = function(input) {
    if (!input.files || input.files.length === 0) return;
    var file = input.files[0];
    if (file.size > 20 * 1024 * 1024) {
      toast("文件过大（> 20MB），请选择更小的文件", "error");
      return;
    }
    var active = state.steps.find(function (s) { return s.step_id === state.activeStepId; });
    if (active) {
      active.config._filePreview = file.name + " (" + Math.round(file.size / 1024) + " KB)";
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      var dataUrl = e.target.result;
      var base64 = dataUrl.indexOf(",") >= 0 ? dataUrl.split(",")[1] : dataUrl;
      state.attachmentFileBase64 = base64;
      state.attachmentFileName = file.name;
      toast("已选择文件：" + file.name, "success");
      // 立即测试
      doTestAttachmentWithFile(base64, file.name);
    };
    reader.readAsDataURL(file);
  };

  function doTestAttachmentWithFile(base64, filename) {
    toast("正在解析附件：" + filename, "info");
    api("/api/admin/crawl/preview/attachment", "POST", {
      file_base64: base64,
      filename: filename,
    }).then(function (data) {
      if (data && data.code === 0) {
        var summary = document.getElementById("step-test-summary");
        var text = document.getElementById("test-status-text");
        var results = document.getElementById("test-results");
        if (text) text.textContent = "附件解析成功：" + filename;
        if (results) {
          results.innerHTML = renderAttachmentResult(data.data);
        }
        if (summary) summary.style.display = "block";
        // 缓存到 upstreamCache 供后续字段映射使用
        state.upstreamCache = state.upstreamCache || {};
        state.upstreamCache.results = data.data && data.data.tables ? [data.data] : [];
        if (data.data && data.data.tables && data.data.tables.length > 0) {
          state.upstreamCache.results = [{
            filename: data.data.filename,
            text: data.data.text,
            tables: data.data.tables,
            metadata: data.data.metadata,
          }];
        }
        toast("附件解析成功", "success");
      } else {
        toast("解析失败：" + ((data || {}).msg || ""), "error");
      }
    }).catch(function (err) { toast("解析异常：" + err, "error"); });
  }

  function renderAttachmentResult(data) {
    if (!data) return '<div class="muted">无数据</div>';
    var html = '<div style="padding:10px;">';
    html += '<div style="margin-bottom:12px;padding:8px 12px;background:#f0f9ff;border-radius:4px;font-size:12px;">';
    html += '<strong>📄 文件:</strong> ' + (data.filename || "(未命名)") + " | ";
    html += '<strong>类型:</strong> ' + (data.file_type || "") + " | ";
    html += '<strong>大小:</strong> ' + (data.file_size_bytes ? Math.round(data.file_size_bytes / 1024) + " KB" : "-") + " | ";
    html += '<strong>状态:</strong> ' + (data.parse_status || "-");
    if (data.error) html += ' | <strong style="color:#dc2626;">错误:</strong> ' + String(data.error);
    html += "</div>";

    // 文本预览
    if (data.text) {
      var preview = String(data.text);
      var truncated = preview.length > 2000;
      if (truncated) preview = preview.substring(0, 2000);
      html += '<details open="true" style="margin-bottom:12px;">';
      html += '<summary style="cursor:pointer;padding:6px 8px;background:#eef2ff;border-radius:4px;font-size:13px;font-weight:600;">📝 文本内容 (' + (data.text ? String(data.text).length : 0) + ' 字符)</summary>';
      html += '<div style="position:relative;">';
      html += '<button type="button" class="btn btn-sm" onclick="window.crawlAddTextMapping()" style="position:absolute;right:8px;top:8px;padding:4px 8px;font-size:11px;background:#475569;color:#fff;border:none;border-radius:4px;cursor:pointer;">+ 将全文映射为字段</button>';
      html += '<pre style="background:#fff;padding:10px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow:auto;margin-top:8px;">' +
        preview.replace(/</g, "&lt;").replace(/>/g, "&gt;") + (truncated ? "\n\n... [已截断，完整内容用于字段映射]" : "") + '</pre>';
      html += "</div></details>";
    }

    // 表格预览 —— 支持点击单元格生成字段映射
    if (data.tables && data.tables.length > 0) {
      html += '<details open="true" style="margin-bottom:12px;">';
      html += '<summary style="cursor:pointer;padding:6px 8px;background:#ecfdf5;border-radius:4px;font-size:13px;font-weight:600;">📊 表格数据 (' + data.tables.length + ' 个表) — 点击单元格自动生成映射表达式</summary>';
      
      var useMergedRows = (data.merged_rows && data.merged_rows.length > 0);
      var allRows = useMergedRows ? data.merged_rows : [];
      var firstHeaders = (data.tables[0] && data.tables[0].headers) || [];
      
      if (useMergedRows) {
        html += '<div style="margin:8px 0;padding:8px;background:#dcfce7;border:1px solid #86efac;border-radius:4px;">';
        html += '<div style="font-size:12px;color:#166534;margin-bottom:6px;">📋 合并表格（所有页面）' +
          ' (行: ' + allRows.length + ', 列: ' + (firstHeaders.length || (allRows[0] || []).length || 0) + ')' +
          ' — 点击表头自动插入遍历表达式</div>';
        html += '<div style="overflow:auto;max-height:300px;"><table style="width:100%;border-collapse:collapse;font-size:11px;">';
        if (firstHeaders.length > 0) {
          html += "<tr>";
          for (var mhi = 0; mhi < firstHeaders.length; mhi++) {
            var mHeaderExpr = 'attachments[0].merged_rows[row][' + mhi + ']';
            html += '<th onclick="window.crawlCopyExpr(\'' + mHeaderExpr.replace(/'/g, "\\'") + '\', this)"' +
              ' style="padding:4px 6px;border:1px solid #166534;background:#166534;color:#fff;text-align:left;cursor:pointer;"' +
              ' title="点击复制: ' + mHeaderExpr + '">' +
              String(firstHeaders[mhi]).replace(/</g, "&lt;") + '<br/>' +
              '<span style="font-size:10px;font-weight:400;color:#bbf7d0;">[遍历所有行]</span></th>';
          }
          html += "</tr>";
        }
        for (var mri = 0; mri < Math.min(allRows.length, 5); mri++) {
          html += "<tr>";
          for (var mci = 0; mci < (allRows[mri] || []).length; mci++) {
            var mCellExpr = 'attachments[0].merged_rows[' + mri + '][' + mci + ']';
            var mBgColor = mri % 2 === 0 ? "#f0fdf4" : "#fff";
            html += '<td onclick="window.crawlCopyExpr(\'' + mCellExpr.replace(/'/g, "\\'") + '\', this)"' +
              ' style="padding:4px 6px;border:1px solid #86efac;background:' + mBgColor + ';vertical-align:top;cursor:pointer;transition:background 0.2s;"' +
              ' onmouseover="this.style.background=\'#fef3c7\';" onmouseout="this.style.background=\'' + mBgColor + '\';"' +
              ' title="点击复制: ' + mCellExpr + '">' +
              String(allRows[mri][mci] || "").replace(/</g, "&lt;") +
              '<br/><span style="font-size:10px;color:#86efac;">[' + mri + ',' + mci + ']</span></td>';
          }
          html += "</tr>";
        }
        html += "</table></div></div>";
      }
      
      for (var ti = 0; ti < data.tables.length; ti++) {
        var tbl = data.tables[ti];
        var rows = tbl.rows || [];
        html += '<div style="margin:8px 0;padding:8px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;">';
        html += '<div style="font-size:12px;color:#475569;margin-bottom:6px;">表格 ' + (ti + 1) +
          ' (行: ' + (tbl.row_count || rows.length) + ', 列: ' + (tbl.column_count || (rows[0] || []).length || 0) + ')' +
          ' — 点击单元格自动插入映射表达式</div>';
        html += '<div style="overflow:auto;max-height:300px;"><table style="width:100%;border-collapse:collapse;font-size:11px;">';
        // 表头
        if (tbl.headers && tbl.headers.length > 0) {
          html += "<tr>";
          for (var hi = 0; hi < tbl.headers.length; hi++) {
            var headerExpr = 'attachments[0].tables[' + ti + '].rows[row][' + hi + ']';
            html += '<th onclick="window.crawlCopyExpr(\'' + headerExpr.replace(/'/g, "\\'") + '\', this)"' +
              ' style="padding:4px 6px;border:1px solid #475569;background:#475569;color:#fff;text-align:left;cursor:pointer;"' +
              ' title="点击复制: ' + headerExpr + '">' +
              String(tbl.headers[hi]).replace(/</g, "&lt;") + '<br/>' +
              '<span style="font-size:10px;font-weight:400;color:#e0e7ff;">[表头 ' + hi + ']</span></th>';
          }
          html += "</tr>";
        }
        // 数据行
        for (var ri = 0; ri < Math.min(rows.length, 8); ri++) {
          html += "<tr>";
          for (var ci = 0; ci < rows[ri].length; ci++) {
            var cellExpr = 'attachments[0].tables[' + ti + '].rows[' + ri + '][' + ci + ']';
            var bgColor = ri % 2 === 0 ? "#f8fafc" : "#fff";
            html += '<td onclick="window.crawlCopyExpr(\'' + cellExpr.replace(/'/g, "\\'") + '\', this)"' +
              ' style="padding:4px 6px;border:1px solid #cbd5e1;background:' + bgColor + ';vertical-align:top;cursor:pointer;transition:background 0.2s;"' +
              ' onmouseover="this.style.background=\'#fef3c7\';" onmouseout="this.style.background=\'' + bgColor + '\';"' +
              ' title="点击复制: ' + cellExpr + '">' +
              String(rows[ri][ci] || "").replace(/</g, "&lt;") +
              '<br/><span style="font-size:10px;color:#94a3b8;">[' + ri + ',' + ci + ']</span></td>';
          }
          html += "</tr>";
        }
        html += "</table></div>";
        if (rows.length > 8) html += '<div style="font-size:11px;color:#94a3b8;margin-top:4px;">（仅显示前 8 行，共 ' + rows.length + ' 行）</div>';
        html += "</div>";
      }
      html += "</details>";
    }

    // metadata
    if (data.metadata) {
      var metaKeys = Object.keys(data.metadata);
      if (metaKeys.length > 0) {
        html += '<details style="margin-bottom:8px;"><summary style="cursor:pointer;padding:6px 8px;background:#fffbeb;border-radius:4px;font-size:13px;font-weight:600;">🏷 元数据 (' + metaKeys.length + ' 项) — 点击复制表达式</summary>';
        html += '<div style="padding:8px;font-size:12px;color:#475569;">';
        for (var mi2 = 0; mi2 < metaKeys.length; mi2++) {
          var metaExpr = 'attachments[0].metadata.' + metaKeys[mi2];
          html += '<div style="padding:4px 0;cursor:pointer;" onclick="window.crawlCopyExpr(\'' + metaExpr.replace(/'/g, "\\'") + '\', this)" onmouseover="this.style.background=\'#fef3c7\';" onmouseout="this.style.background=\'transparent\';">' +
            '<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;">' + metaExpr + '</code> = <strong>' +
            String(data.metadata[metaKeys[mi2]]).replace(/</g, "&lt;") + '</strong></div>';
        }
        html += "</div></details>";
      }
    }

    html += "</div>";
    return html;
  }

  // --- PDF 内容点击工具函数 ---
  window.crawlCopyExpr = function(expr, el) {
    // 1. 高亮当前元素
    if (el) {
      var originalBg = el.style.background;
      el.style.background = "#86efac";
      setTimeout(function () { el.style.background = originalBg; }, 300);
    }
    // 2. 如果当前激活步骤是 field_mapping，自动填入 source 字段
    var active = state.steps.find(function (s) { return s.step_id === state.activeStepId; });
    if (active && active.step_type === "field_mapping") {
      var inputs = document.querySelectorAll('[data-fm-source]');
      if (inputs && inputs.length > 0) {
        // 找到第一个空的 source input，填入表达式
        for (var i = 0; i < inputs.length; i++) {
          if (!inputs[i].value || inputs[i].value.trim() === "") {
            inputs[i].value = expr;
            syncFieldMapToConfig();
            toast("已插入映射表达式: " + expr, "success");
            return;
          }
        }
        // 没有空字段，添加新行
        window.crawlAddMapRow();
        setTimeout(function () {
          var newInputs = document.querySelectorAll('[data-fm-source]');
          if (newInputs && newInputs.length > 0) {
            newInputs[newInputs.length - 1].value = expr;
            syncFieldMapToConfig();
          }
        }, 50);
        toast("已添加新字段行并填入: " + expr, "success");
        return;
      }
    }
    // 3. 其他情况：复制到剪贴板
    try {
      var ta = document.createElement("textarea");
      ta.value = expr;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      toast("已复制表达式: " + expr, "success");
    } catch (e) {
      toast("表达式: " + expr + "（请手动复制）", "info");
    }
  };

  window.crawlAddTextMapping = function() {
    window.crawlCopyExpr("attachments[0].text");
  };

  // --- 字段映射编辑器 ---
  window.crawlAddMapRow = function() {
    var tbody = document.querySelector('[data-field-map-row="1"]') ? document.querySelector('[data-field-map-row="1"]').parentNode : null;
    if (!tbody) return;
    var tr = document.createElement("tr");
    tr.setAttribute("data-field-map-row", "1");
    tr.innerHTML =
      '<td style="padding:6px 8px;"><input type="text" data-fm-target value="" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;"></td>' +
      '<td style="padding:6px 8px;"><input type="text" data-fm-source value="" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;"></td>' +
      '<td style="padding:6px 8px;width:50px;text-align:center;"><button type="button" class="btn btn-sm btn-warn" onclick="window.crawlRemoveMapRow(this)" style="padding:4px 8px;font-size:12px;">🗑</button></td>';
    tbody.appendChild(tr);
    syncFieldMapToConfig();
    bindFieldMapInputs();
  };

  window.crawlRemoveMapRow = function(btn) {
    var tr = btn;
    while (tr && tr.parentNode && tr.tagName !== "TR") tr = tr.parentNode;
    if (tr && tr.parentNode) tr.parentNode.removeChild(tr);
    syncFieldMapToConfig();
  };

  function syncFieldMapToConfig() {
    var active = state.steps.find(function (s) { return s.step_id === state.activeStepId; });
    if (!active || active.step_type !== "field_mapping") return;
    var newMap = {};
    var rows = document.querySelectorAll('[data-field-map-row="1"]');
    for (var i = 0; i < rows.length; i++) {
      var targetInput = rows[i].querySelector('[data-fm-target]');
      var sourceInput = rows[i].querySelector('[data-fm-source]');
      var target = targetInput ? targetInput.value.trim() : "";
      var source = sourceInput ? sourceInput.value : "";
      if (target) newMap[target] = source;
    }
    active.config.map = newMap;
    // 同步 JSON 编辑器
    var ta = document.getElementById("step-config-textarea");
    if (ta) ta.value = JSON.stringify(active.config, null, 2);
    renderSteps();
  }

  function bindFieldMapInputs() {
    var inputs = document.querySelectorAll('[data-fm-target], [data-fm-source]');
    for (var i = 0; i < inputs.length; i++) {
      // 避免重复绑定
      if (inputs[i]._fmBound) continue;
      inputs[i]._fmBound = true;
      inputs[i].addEventListener("input", syncFieldMapToConfig);
      inputs[i].addEventListener("change", syncFieldMapToConfig);
    }
  }

  // ============================================================ 初始化

  function init() {
    var planId = getQueryParam("plan_id");
    state.planId = planId || null;
    // 监听 iframe 发来的点击事件
    if (window.addEventListener) {
      window.addEventListener("message", function (ev) {
        var data = ev.data;
        if (data && data.type === "crawl_click") {
          handleIframeClick(data);
        }
      });
    }
    // 监听步骤详情面板按钮
    var detailTestBtn = document.getElementById("step-detail-test");
    if (detailTestBtn) {
      detailTestBtn.addEventListener("click", function () {
        var active = state.steps.find(function (s) { return s.step_id === state.activeStepId; });
        doTestStep(active);
      });
    }
    var detailDelBtn = document.getElementById("step-detail-delete");
    if (detailDelBtn) {
      detailDelBtn.addEventListener("click", function () {
        var delIdx = state.steps.findIndex(function (s) { return s.step_id === state.activeStepId; });
        if (delIdx >= 0) {
          state.steps.splice(delIdx, 1);
          state.steps.forEach(function (s, i) { s.step_order = i; });
          state.activeStepId = null;
          renderSteps();
          renderStepDetail();
          toast("已删除步骤", "success");
        }
      });
    }
    if (planId) {
      api("/api/admin/crawl/steps/plan?plan_id=" + encodeURIComponent(planId), "GET").then(function (data) {
        if (data && data.code === 0 && data.data) {
          var pd = data.data;
          document.getElementById("crawl-plan-name").value = pd.plan_name || "已加载方案";
          // 加载配置字段：target_domain, max_items, cron, save_middle_result 等
          if (pd.config && typeof pd.config === "object") {
            state.planConfig = Object.assign({}, state.planConfig, pd.config);
          } else {
            // 兼容旧字段（直接放在对象层级）
            state.planConfig.target_domain = pd.target_domain || state.planConfig.target_domain;
            state.planConfig.max_items = pd.max_items || state.planConfig.max_items;
            state.planConfig.cron = pd.cron || state.planConfig.cron;
            if (typeof pd.save_middle_result === "boolean") state.planConfig.save_middle_result = pd.save_middle_result;
            if (typeof pd.funnel_visible === "boolean") state.planConfig.funnel_visible = pd.funnel_visible;
            if (typeof pd.enable_clean === "boolean") state.planConfig.enable_clean = pd.enable_clean;
          }
          if (pd.steps && pd.steps.length > 0) {
            loadPackageFromDict({ steps: pd.steps });
            state.planId = planId;
            if (pd.url) {
              document.getElementById("crawl-url-input").value = pd.url;
            }
          } else {
            loadPackageFromDict(null);
            if (pd.url) {
              document.getElementById("crawl-url-input").value = pd.url;
            }
          }
        } else {
          loadPackageFromDict(null);
          toast("加载方案失败：" + ((data || {}).msg || "未知错误"), "error");
        }
      }).catch(function (err) {
        loadPackageFromDict(null);
        toast("加载方案异常：" + err, "error");
      });
    } else {
      loadPackageFromDict(null);
    }
    renderSteps();
    renderStepDetail();
    setMode("browse");
  }

  // 等待 DOM 就绪后初始化
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    // 延迟一点确保 DOM 元素已存在
    setTimeout(init, 100);
  }

})();
