import sqlite3, json
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
job = 'job_6e09ca5c04864306b6b6f164906358ec'
con = sqlite3.connect(p)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("SELECT seq, method, params_json FROM pipeline_agent_events WHERE job_id=? ORDER BY seq", (job,))
rows = cur.fetchall()
con.close()
# list tool calls
for r in rows:
    if r['method']!='item/started':
        continue
    try:
        pjson = json.loads(r['params_json'] or '{}')
    except Exception:
        continue
    item = pjson.get('item',{}) if isinstance(pjson, dict) else {}
    tool = item.get('tool')
    args = item.get('arguments')
    print(r['seq'], tool)
    if tool in ('Write','Edit','MultiEdit'):
        print('  args=', args)
