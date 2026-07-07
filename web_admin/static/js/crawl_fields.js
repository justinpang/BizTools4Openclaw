/* =========================================================================
 * crawl_fields.js — 字段模板库管理页
 *   - 三类预设字段：政务通告 / 企业公示 / 违规通报（内置模板，只读）
 *   - 自定义字段：新增 / 编辑 / 删除，持久化到后端 via API
 * ========================================================================= */
(function () {
  "use strict";

  function api(path, method, body) {
    var opts = {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body && method && method !== "GET") opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  // -------- 内置字段预设模板 --------
  var PRESET_TEMPLATES = {
    gov: {
      title: "🏛 政务通告",
      fields: [
        { name: "title",        label: "标题",     type: "text",   suggest: "h1, .title, #news-title" },
        { name: "publish_time", label: "发布时间", type: "date",   suggest: ".time, .publish-date, time" },
        { name: "source",       label: "来源机构", type: "text",   suggest: ".source, .from" },
        { name: "doc_number",   label: "文号",     type: "text",   suggest: ".doc-no, .number" },
        { name: "content",      label: "正文",     type: "html",   suggest: ".content, article, .body" },
        { name: "attachments",  label: "附件",     type: "links",  suggest: 'a[href*="pdf"], a.attachment' },
      ],
    },
    enterprise: {
      title: "🏢 企业公示",
      fields: [
        { name: "company_name",     label: "企业名称",     type: "text",   suggest: ".company, h1, .name" },
        { name: "credit_code",      label: "统一社会信用代码", type: "text", suggest: ".credit-code, .code" },
        { name: "legal_rep",        label: "法定代表人",   type: "text",   suggest: ".legal, .rep, .person" },
        { name: "registered_cap",   label: "注册资本",     type: "text",   suggest: ".capital, .registered" },
        { name: "address",          label: "注册地址",     type: "text",   suggest: ".address" },
        { name: "publish_time",     label: "公示日期",     type: "date",   suggest: ".publish-time, time" },
      ],
    },
    violation: {
      title: "⚠ 违规通报",
      fields: [
        { name: "title",            label: "通报标题",     type: "text",   suggest: "h1, .title" },
        { name: "case_number",      label: "案件编号",     type: "text",   suggest: ".case, .number" },
        { name: "violator",         label: "违规主体",     type: "text",   suggest: ".company, .violator" },
        { name: "violation_type",   label: "违规类型",     type: "text",   suggest: ".violation, .type" },
        { name: "punishment",       label: "处罚结果",     type: "html",   suggest: ".punish, .result" },
        { name: "punishment_amount",label: "处罚金额(元)", type: "number", suggest: ".amount, .fine" },
        { name: "authority",        label: "处罚机关",     type: "text",   suggest: ".authority, .dept" },
        { name: "publish_time",     label: "发布时间",     type: "date",   suggest: ".time, time" },
      ],
    },
  };

  var customFields = [];

  // -------- 渲染 --------
  function renderCategories() {
    var el = document.getElementById("crawl-field-categories");
    if (!el) return;
    var html = [];
    html.push('<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:15px;">');
    for (var key in PRESET_TEMPLATES) {
      if (!PRESET_TEMPLATES.hasOwnProperty(key)) continue;
      var cat = PRESET_TEMPLATES[key];
      html.push('<div style="padding:15px;background:#f8fafc;border:1px solid #e8ecf0;border-radius:6px;">');
      html.push('  <h3 style="margin:0 0 10px 0;font-size:15px;">' + cat.title + '</h3>');
      html.push('  <div style="font-size:12px;color:#888;margin-bottom:10px;">共 ' + cat.fields.length + ' 个字段模板（只读，点击查看）</div>');
      html.push('  <button class="btn btn-sm" onclick="crawlFields.toggleCat(\'' + key + '\')">显示/隐藏字段</button>');
      html.push('  <div id="cat-fields-' + key + '" style="margin-top:10px;display:none;"></div>');
      html.push('</div>');
    }
    html.push('</div>');
    el.innerHTML = html.join("");

    // 预填充内容
    for (var k2 in PRESET_TEMPLATES) {
      if (!PRESET_TEMPLATES.hasOwnProperty(k2)) continue;
      var out = [];
      var list = PRESET_TEMPLATES[k2].fields;
      for (var j = 0; j < list.length; j++) {
        var f = list[j];
        out.push('<div style="padding:6px 8px;background:white;border:1px solid #e8ecf0;border-radius:4px;margin-bottom:5px;font-size:12px;">');
        out.push('  <b>' + f.name + '</b> <span style="color:#666;">(' + f.label + ' · ' + f.type + ')</span>');
        out.push('  <div style="color:#888;margin-top:3px;font-size:11px;">建议选择器: <code>' + f.suggest + '</code></div>');
        out.push('</div>');
      }
      var c = document.getElementById("cat-fields-" + k2);
      if (c) c.innerHTML = out.join("");
    }
  }

  function renderCustomFields() {
    var el = document.getElementById("crawl-fields-list");
    if (!el) return;
    var html = [];
    html.push('<h3 style="margin-top:25px;">🎯 自定义字段库</h3>');
    if (!customFields || customFields.length === 0) {
      html.push('<div style="padding:20px;color:#888;text-align:center;background:#fafbfc;border-radius:4px;border:1px dashed #ccd;">暂无自定义字段，点击右上角「+ 新增自定义字段」创建</div>');
    } else {
      html.push('<table style="width:100%;border-collapse:collapse;margin-top:10px;">');
      html.push('  <thead><tr style="background:#f5f7fa;">');
      html.push('    <th style="padding:8px;text-align:left;border-bottom:1px solid #e8ecf0;font-size:13px;">字段名</th>');
      html.push('    <th style="padding:8px;text-align:left;border-bottom:1px solid #e8ecf0;font-size:13px;">类型</th>');
      html.push('    <th style="padding:8px;text-align:left;border-bottom:1px solid #e8ecf0;font-size:13px;">默认选择器</th>');
      html.push('    <th style="padding:8px;text-align:left;border-bottom:1px solid #e8ecf0;font-size:13px;">必填</th>');
      html.push('    <th style="padding:8px;text-align:left;border-bottom:1px solid #e8ecf0;font-size:13px;">操作</th>');
      html.push('  </tr></thead><tbody>');
      for (var i = 0; i < customFields.length; i++) {
        var f = customFields[i];
        html.push('<tr style="background:' + (i % 2 === 0 ? "white" : "#fafbfc") + ';">');
        html.push('  <td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:13px;"><b>' + f.name + '</b> <span style="color:#888;font-size:11px;">(' + f.label + ')</span></td>');
        html.push('  <td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + f.type + '</td>');
        html.push('  <td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:12px;color:#666;"><code>' + (f.suggest || f.selector || "") + '</code></td>');
        html.push('  <td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:13px;">' + (f.required ? "✅" : "—") + '</td>');
        html.push('  <td style="padding:8px;border-bottom:1px solid #e8ecf0;font-size:13px;">');
        html.push('    <a href="javascript:crawlFields.editField(\'' + f.id + '\')" style="margin-right:10px;">编辑</a>');
        html.push('    <a href="javascript:crawlFields.deleteField(\'' + f.id + '\')" style="color:#f5222d;">删除</a>');
        html.push('  </td>');
        html.push('</tr>');
      }
      html.push("</tbody></table>");
    }
    el.innerHTML = html.join("");
  }

  // -------- 加载自定义字段 --------
  function loadCustom() {
    api("/api/admin/crawl/fields/templates").then(function (data) {
      if (data && data.code === 0 && data.data && data.data.templates && data.data.templates.custom) {
        customFields = data.data.templates.custom;
      } else {
        // fallback: 直接 API 调用
        api("/api/admin/crawl/fields/custom").then(function (d2) {
          if (d2 && d2.code === 0 && d2.data) customFields = d2.data.items || [];
          renderCustomFields();
        });
        return;
      }
      renderCustomFields();
    }).catch(function () {
      renderCustomFields();
    });
  }

  // -------- 暴露 API --------
  window.crawlFields = {
    toggleCat: function (key) {
      var el = document.getElementById("cat-fields-" + key);
      if (el) el.style.display = (el.style.display === "none") ? "block" : "none";
    },
    addField: function () {
      var name = window.prompt("字段名（英文字母，例: title / publish_time / content）");
      if (!name) return;
      var label = window.prompt("字段中文标签（例: 标题 / 发布时间 / 正文）", name);
      if (label == null) return;
      var type = window.prompt("字段类型（text / html / date / number / links）", "text") || "text";
      var suggest = window.prompt("默认选择器建议", "");
      var required = window.confirm("是否必填字段？（OK=是 / 取消=否）");

      api("/api/admin/crawl/fields/custom", "POST", {
        name: name,
        label: label || name,
        type: type,
        required: required,
        suggest_selector: suggest,
      }).then(function (data) {
        if (data && data.code === 0) {
          showMessage("字段 " + name + " 已添加");
          loadCustom();
        } else {
          showMessage("添加失败：" + (data.msg || ""), true);
        }
      });
    },
    editField: function (id) {
      var newName = window.prompt("修改字段名");
      if (!newName) return;
      api("/api/admin/crawl/fields/custom/" + id, "PUT", { name: newName, label: newName }).then(function (data) {
        if (data && data.code === 0) {
          showMessage("已更新");
          loadCustom();
        } else {
          showMessage("更新失败", true);
        }
      });
    },
    deleteField: function (id) {
      if (!window.confirm("⚠ 确认删除此字段？将影响依赖此字段的方案。")) return;
      api("/api/admin/crawl/fields/custom/" + id, "DELETE").then(function (data) {
        if (data && data.code === 0) {
          showMessage("已删除");
          loadCustom();
        } else {
          showMessage("删除失败", true);
        }
      });
    },
  };

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

  // 启动
  renderCategories();
  loadCustom();
})();
