"""测试用完整 URL 解析 PDF"""
import requests

base = "http://localhost:8000"

# 用完整 URL 测试
pdf_url = "https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20266/284102405dc747758e69300022e990e8.pdf"

print(f"测试 PDF: {pdf_url}")

r = requests.post(f"{base}/api/admin/crawl/steps/step-test",
    json={"step_type": "attachment_parse",
          "config": {"url": pdf_url, "parse_pdf": True},
          "page_html": ""},
    timeout=180)
data = r.json()
print(f"code: {data.get('code')}")

if data.get("data"):
    out = data["data"].get("output", {})
    results = out.get("results", [])
    print(f"解析结果: {len(results)} 个")
    for r in results:
        print(f"  filename: {r.get('filename')}")
        print(f"  status: {r.get('parse_status')}")
        print(f"  error: {r.get('error')}")
        print(f"  text 长度: {len(r.get('text') or '')}")
        if r.get('text'):
            print(f"  text 前 500 字符: {r['text'][:500]}")
        print(f"  tables: {len(r.get('tables') or [])} 个")
