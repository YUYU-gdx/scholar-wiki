import sqlite3
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
job = 'job_6e09ca5c04864306b6b6f164906358ec'
con = sqlite3.connect(p)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_task_events'")
print('has_pipeline_task_events=', bool(cur.fetchone()))
cur.execute("SELECT seq, ts, event_type, payload_json FROM pipeline_task_events WHERE job_id=? ORDER BY seq", (job,))
rows = cur.fetchall()
print('task_event_count=', len(rows))
for r in rows[:15]:
    print('---', r['seq'], r['event_type'])
    print(str(r['payload_json'] or '')[:700])

for r in rows:
    txt = str(r['payload_json'] or '')
    if 'query' in txt or 'scholarly-paper-extraction' in txt or 'extract_result.json' in txt:
        print('== hit ==', r['seq'], r['event_type'])
        print(txt[:4000])
        print()
con.close()
