import sqlite3, json
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
job = 'job_6e09ca5c04864306b6b6f164906358ec'
con = sqlite3.connect(p)
cur = con.cursor()
cur.execute('SELECT options_json, result_json FROM pipeline_jobs WHERE job_id=?', (job,))
row = cur.fetchone()
con.close()
opts = json.loads(row[0] or '{}') if row and row[0] else {}
res = json.loads(row[1] or '{}') if row and row[1] else {}
print('options=', opts)
print('parse_keys=', list((res.get('parse') or {}).keys()))
print('parse=', res.get('parse'))
