"""E2E test: upload PDF → full pipeline → verify every phase."""
import json, pathlib, time, sys
import requests as req

API = "http://127.0.0.1:8013"

# ── Step 1: Verify libraries ──
print("=== Step 1: Check libraries ===")
resp = req.get(f"{API}/literature/libraries")
libs = resp.json()
print(f"  Libraries: {json.dumps(libs, ensure_ascii=False)[:300]}")
assert libs.get("libraries"), "FAIL: no libraries returned"
lib_id = libs.get("default_library_id") or libs["libraries"][0]["library_id"]
print(f"  Using library: {lib_id}")

# ── Step 2: Submit PDF ──
print("\n=== Step 2: Submit PDF ===")
pdf_path = pathlib.Path(
    r"D:\Code\kn_gragh\outputs\full data\full data"
    r"\organized_by_title\pdf"
    r"\A framework for supply chain sustainability"
    r" in service industry with Confirmatory Factor Analysis.pdf"
)
assert pdf_path.exists(), f"PDF not found: {pdf_path}"
print(f"  PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

with open(pdf_path, "rb") as f:
    resp = req.post(
        f"{API}/v1/pipeline/parse-extract",
        files={"file": (pdf_path.name, f, "application/pdf")},
        data={"library_id": lib_id},
        timeout=10,
    )
print(f"  POST status: {resp.status_code}")
job = resp.json()
assert resp.status_code in (200, 202), f"FAIL: {resp.status_code} {job.get('error','')} {job.get('detail','')}"
job_id = job.get("job_id")
assert job_id, f"FAIL: no job_id in response"
print(f"  job_id: {job_id}")

# ── Step 3: Poll job ──
print("\n=== Step 3: Poll job ===")
final = None
for i in range(36):  # 6 minutes max
    time.sleep(10)
    j = req.get(f"{API}/v1/jobs/{job_id}").json()
    status = j.get("status", "?")
    stage = j.get("stage", "?")
    progress = j.get("progress", 0)
    print(f"  [{i+1}] {status}/{stage} ({progress}%)")
    if status in ("completed", "failed", "cancelled"):
        final = j
        break
assert final, "FAIL: job did not finish"

# ── Step 4: Verify outputs ──
print("\n=== Step 4: Verify ===")
verdict = final.get("final_verdict", "?")
imported = final.get("imported_paper_count", 0)
graph_ok = final.get("graph_updated", False)
graph_path = final.get("graph_output_path", "")

print(f"  verdict: {verdict}")
print(f"  imported_paper_count: {imported}")
print(f"  graph_updated: {graph_ok}")
print(f"  graph_output_path: {graph_path}")

assert verdict == "success", f"FAIL: verdict={verdict} at stage {final.get('failure_stage')}: {final.get('failure_code')}"
assert imported > 0, "FAIL: no papers imported"
assert graph_ok, "FAIL: graph_views not built"

# Step 4b: verify graph_views.json
gv = json.loads(pathlib.Path(graph_path).read_text(encoding="utf-8"))
pm = gv.get("paper_map", {})
nodes = gv.get("nodes", {})
edges = gv.get("edges", [])
print(f"  paper_map: {len(pm)} entries")
print(f"  nodes: {len(nodes)}")
print(f"  edges: {len(edges)}")
assert len(pm) > 0, "FAIL: paper_map is empty"
assert len(nodes) > 0, f"FAIL: no nodes ({len(nodes)})"
assert len(edges) > 0, f"FAIL: no edges ({len(edges)})"

# Step 4c: verify SQLite
import sqlite3
ws = final.get("workspace_path", "")
db_path = pathlib.Path(ws) / "kn_gragh.db" if ws else None
if db_path and db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM papers")
    paper_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM direct_effects")
    effect_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM canonical_variables")
    var_count = cur.fetchone()[0]
    conn.close()
    print(f"  SQLite: papers={paper_count}, effects={effect_count}, variables={var_count}")
    assert paper_count > 0, "FAIL: no papers in SQLite"
else:
    print(f"  SQLite: db not found at {db_path}")

print("\n✅ FULL PIPELINE E2E PASSED")
print("   PDF → Mineru → Extract → Import → SQLite → Graph Views")
