import sqlite3
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
con = sqlite3.connect(p)
cur = con.cursor()
cur.execute("PRAGMA table_info(pipeline_task_events)")
print(cur.fetchall())
cur.execute("SELECT * FROM pipeline_task_events LIMIT 5")
rows = cur.fetchall()
print('sample_rows=', rows)
con.close()
