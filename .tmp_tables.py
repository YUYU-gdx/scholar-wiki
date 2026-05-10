import sqlite3
p = r'D:\KNGraphApp\pipeline\jobs.sqlite'
con = sqlite3.connect(p)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print([r[0] for r in cur.fetchall()])
con.close()
