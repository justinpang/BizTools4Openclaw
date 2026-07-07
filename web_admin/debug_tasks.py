import json
from infra.redis_client import get_redis

r = get_redis()

tasks = r.hgetall('web_admin:spider:tasks')
print('=== Redis 中任务数量:', len(tasks))

for k, v in list(tasks.items()):
    key = k.decode() if isinstance(k, bytes) else str(k)
    val = v.decode() if isinstance(v, bytes) else str(v)
    meta = json.loads(val)
    print('Task:', key)
    print('  status:', meta.get('status'))
    print('  success:', meta.get('success'), 'failed:', meta.get('failed'))
    print('  channel:', meta.get('channel'))
    print('  spider_name:', meta.get('spider_name'))
    ut = meta.get('url_template') or ''
    print('  url_template:', ut[:80])
    kws = meta.get('keywords') or []
    print('  keywords type:', type(kws).__name__)
    print('  keywords:', kws[:3] if isinstance(kws, list) else kws[:80])
    print()
