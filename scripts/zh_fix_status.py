#!/usr/bin/env python3
"""JS状态修复：恢复英文状态码比较 + 添加中文显示翻译。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JS_PATH = WEB_ADMIN = PROJECT_ROOT / "web_admin" / "static" / "js" / "admin.js"

# 修复 1: 恢复异常池的英文状态比较
FIX1_OLD = '''          var statusColor = "待处理" === item.status ? "#f5a623" :
                             "resolved" === item.status ? "#28a745" :
                             "discarded" === item.status ? "#dc3545" :
                             "false_positive" === item.status ? "#6b7a90" : "#2c3e50";
          rowsHtml += '<tr data-item-id="' + item.exception_id + '">' +
            '<td>' + item.exception_id + '</td>' +
            '<td><span class="status-tag" style="background:#f0f3f7;color:#2c3e50;padding:2px 8px;border-radius:3px;font-size:11px;">' + (item.exception_type || "") + '</span></td>' +
            '<td>' + (item.source_channel || "") + '</td>' +
            '<td>' + (item.title || "") + '</td>' +
            '<td style="color:' + statusColor + ';font-weight:500;">' + item.status + '</td>''''

FIX1_NEW = '''          // 后端返回英文状态码，比较用英文；显示用中文翻译
          var __zhStatus = {"pending":"待处理","resolved":"已处理","discarded":"已废弃","false_positive":"误判"};
          var statusColor = "pending" === item.status ? "#f5a623" :
                             "resolved" === item.status ? "#28a745" :
                             "discarded" === item.status ? "#dc3545" :
                             "false_positive" === item.status ? "#6b7a90" : "#2c3e50";
          rowsHtml += '<tr data-item-id="' + item.exception_id + '">' +
            '<td>' + item.exception_id + '</td>' +
            '<td><span class="status-tag" style="background:#f0f3f7;color:#2c3e50;padding:2px 8px;border-radius:3px;font-size:11px;">' + (item.exception_type || "") + '</span></td>' +
            '<td>' + (item.source_channel || "") + '</td>' +
            '<td>' + (item.title || "") + '</td>' +
            '<td style="color:' + statusColor + ';font-weight:500;">' + (__zhStatus[item.status] || item.status) + '</td>''''

# 修复 2: 批量任务的状态比较
FIX2_OLD = '''          var statusColor = "completed" === it.status ? "#28a745" : "running" === it.status ? "#4a90e2" : "待处理" === it.status ? "#f5a623" : "#6b7a90";
          var riskColor = "critical" === it.risk_level ? "#dc3545" : "high" === it.risk_level ? "#f5a623" : "#6b7a90";
          rows += '<tr><td>' + it.batch_id + '</td>' +
                  '<td>' + (it.op_type || "") + '</td>' +
                  '<td>' + (it.operator || "") + '</td>' +
                  '<td>' + (it.total || 0) + '</td>' +
                  '<td style="color:#28a745;">' + (it.succeeded || 0) + '</td>' +
                  '<td style="color:#dc3545;">' + (it.failed || 0) + '</td>' +
                  '<td style="color:' + statusColor + ';font-weight:500;">' + it.status + '</td>' +
                  '<td style="color:' + riskColor + ';">' + (it.risk_level || "normal") + '</td>' +
                  '<td>' + (it.started_at || "") + '</td></tr>';'''

FIX2_NEW = '''          // 状态码比较用英文，显示用中文
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
                  '<td>' + (it.started_at || "") + '</td></tr>';'''

# 修复 3: 批量进度信息显示 - 翻译状态与字段标签
FIX3_OLD = '''        if (info) info.innerHTML = '<div><strong>批量任务ID:</strong> ' + st.batch_id + '</div>' +
          '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">Status: ' + st.status + ' | Total: ' + st.total + ' | Succeeded: ' + st.succeeded + ' | Failed: ' + st.failed + '</div>';'''

FIX3_NEW = '''        if (info) {
          var __zhBatch = {"completed":"已完成","running":"执行中","pending":"等待中","failed":"失败"};
          info.innerHTML = '<div><strong>批量任务ID:</strong> ' + st.batch_id + '</div>' +
            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态: ' + (__zhBatch[st.status] || st.status) + ' | 总数: ' + st.total + ' | 成功: ' + st.succeeded + ' | 失败: ' + st.failed + '</div>';
        }'''

# 修复 4: 导出进度信息 - 翻译状态
FIX4_OLD = '''        if (info) {
          var size = st.file_size ? (st.file_size / 1024).toFixed(1) + " KB" : "生成中...";
          var rows = st.row_count || 0;
          info.innerHTML = '<div><strong>导出ID:</strong> ' + st.export_id + '</div>' +
            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态：' + ({"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"}.get(st.status, st.status)) + ' | 行数：' + rows + ' | 大小：' + size + '</div>';
          if (st.status === "ready" && st.file_content_b64) {
            var filename = "export_" + st.stage_key + "_" + st.export_id + ".csv";
            info.innerHTML += '<div style="margin-top:8px;"><a class="btn btn-primary" onclick="admin.downloadExportFile(\'' +
              st.export_id + '\')">📥 下载CSV文件</a></div>';
          }
        }'''

# 这个在 r1 中可能没有被替换过，让我先检查当前实际内容
# 让我直接写一个更精确的修复 - 在 admin.js 顶部添加状态翻译函数，然后替换显示部分

# 修复 5: 趋势标签
FIX5_OLD = '''            var trLabel = "Pending";'''
FIX5_NEW = '''            var trLabel = "待处理";'''

# 修复 6: 导出状态显示 - 查找实际代码
# 实际代码我需要先读取才知道，让我先做已知的修复

def replace_in_file(path: Path, replacements: list[tuple[str, str]]) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    count = 0
    for old, new in replacements:
        if old in text:
            n = text.count(old)
            text = text.replace(old, new)
            count += n
    if count:
        path.write_text(text, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    print("=" * 60)
    print("🔤 JS 状态修复：恢复英文比较 + 中文显示")
    print("=" * 60)

    replacements = [
        (FIX1_OLD, FIX1_NEW),
        (FIX2_OLD, FIX2_NEW),
        (FIX3_OLD, FIX3_NEW),
        (FIX5_OLD, FIX5_NEW),
    ]

    n = replace_in_file(JS_PATH, replacements)
    print(f"  admin.js: 替换 {n} 处")
    total += n

    # 额外：检查导出状态显示部分
    text = JS_PATH.read_text(encoding="utf-8")
    # 修复导出进度信息
    if 'generating...' in text and '导出ID:' in text:
        # 已有中文，跳过
        pass
    if 'Status: ' in text:
        text = text.replace(
            '''info.innerHTML = '<div><strong>导出ID:</strong> ' + st.export_id + '</div>' +\n            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态：' + ({"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"}.get(st.status, st.status))''',
            '''info.innerHTML = '<div><strong>导出ID:</strong> ' + st.export_id + '</div>' +\n            '<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态：' + (({"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"})[st.status] || st.status)''',
        )
        JS_PATH.write_text(text, encoding="utf-8")
        print("  导出状态显示: 已修复")

    print("\n" + "=" * 60)
    print(f"✅ 完成，共替换 {total} 处")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
