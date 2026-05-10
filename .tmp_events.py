import sqlite3, json
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
job = 'job_6e09ca5c04864306b6b6f164906358ec'
con = sqlite3.connect(p)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("SELECT seq, ts, backend, method, params_json FROM pipeline_agent_events WHERE job_id=? ORDER BY seq", (job,))
rows = cur.fetchall()
print('event_count=', len(rows))
for r in rows[:12]:
    print('---', r['seq'], r['method'])
    pj = r['params_json'] or ''
    print(pj[:500])

# Try to find prompt-like fields
for r in rows:
    m = str(r['method'] or '')
    pj = str(r['params_json'] or '')
    if 'query' in pj or 'prompt' in pj or 'run_turn' in m or 'turn' in m:
        print('== hit ==', r['seq'], m)
        print(pj[:4000])
        print()
con.close()
