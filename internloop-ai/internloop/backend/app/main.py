import os, hmac, hashlib, time, re, csv, io
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
for p in [Path(__file__).resolve().parents[1] / ".env", Path(__file__).resolve().parents[2] / ".env"]:
    if p.exists():
        load_dotenv(p)
        break

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .models import *
from .completion import evaluate, apply_completion
from .gemini import test_connection as gemini_test_conn, tutor_chat as gemini_tutor, review_code as gemini_review

SECRET = os.getenv("SECRET_KEY", "dev-only-change-me").encode()
DEMO = os.getenv("DEMO_MODE", "false").lower() == "true"
Base.metadata.create_all(engine)
app = FastAPI(title="InternLoop AI", version="0.1.0")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def hpw(pw): return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"internloop", 120_000).hex()
def sign(uid):
    body = f"{uid}.{int(time.time()) + 8 * 3600}"
    return body + "." + hmac.new(SECRET, body.encode(), "sha256").hexdigest()

def user(authorization: str = Header(None), db=Depends(get_db)):
    try:
        uid, exp, sig = (authorization or "").removeprefix("Bearer ").split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET, f"{uid}.{exp}".encode(), "sha256").hexdigest()) or int(exp) < time.time(): raise ValueError
        return db.get(User, int(uid))
    except Exception:
        raise HTTPException(401, "Sign in required")

def need(u, *roles):
    if u.role not in roles: raise HTTPException(403, "Your role cannot do this")
def got(x, msg="Not found"):
    if x is None: raise HTTPException(404, msg)
    return x

class Login(BaseModel): email: str; password: str
class Move(BaseModel): to: str
class Text(BaseModel): text: str
class TestIn(BaseModel): name: str; passed: bool
class TutorIn(BaseModel): message: str; history: list = []; context: dict | None = None
class ReviewIn(BaseModel): code: str; commit_msg: str = "Update implementation"; task_id: int | None = None

@app.get("/api/health")
def health(): return {"ok": True}

@app.post("/api/login")
def login(b: Login, db=Depends(get_db)):
    u = db.query(User).filter_by(email=b.email.lower()).first()
    if not u or not hmac.compare_digest(u.pw_hash, hpw(b.password)): raise HTTPException(401, "Wrong email or password")
    return {"token": sign(u.id), "role": u.role}

@app.post("/api/dev/seed")
def seed(db=Depends(get_db)):
    if not DEMO: raise HTTPException(404, "Not found")
    if db.query(User).count(): return {"seeded": False}
    us = {r: User(email=f"{r}@demo.test", role=r, pw_hash=hpw("demo-pass")) for r in ("admin", "mentor", "intern")}
    db.add_all(us.values()); db.flush()
    p = Project(title="Campus Portal Backend"); db.add(p); db.flush()
    T = lambda t, st, m=True: Task(project_id=p.id, assignee_id=us["intern"].id, title=t, status=st, mandatory=m)
    t1, t2, t3, t4 = T("Enrollment REST API", "Submitted"), T("Unit tests", "Submitted"), T("README", "Approved"), T("Optional CSV export", "Assigned", False)
    db.add_all([t1, t2, t3, t4]); db.flush()
    db.add_all([Finding(task_id=t1.id, title="Missing input validation", severity="High"),
                TestRun(project_id=p.id, name="test_enrollment_limits"), Doc(project_id=p.id, name="README.md")])
    db.commit(); return {"seeded": True}

@app.get("/api/projects/{pid}")
def get_project(pid: int, u=Depends(user), db=Depends(get_db)):
    p = got(db.get(Project, pid), "Project not found")
    mine = [t for t in p.tasks if u.role != "intern" or t.assignee_id == u.id]
    if u.role == "intern" and not mine: raise HTTPException(403, "Not your project")
    return {"id": p.id, "title": p.title, "completed_at": p.completed_at, "evaluation": evaluate(p),
            "tasks": [{"id": t.id, "title": t.title, "mandatory": t.mandatory, "status": t.status,
                       "findings": [{"id": f.id, "title": f.title, "severity": f.severity, "status": f.status} for f in t.findings]} for t in mine]}

FLOW = {"Assigned": ["In Progress", "Submitted"], "In Progress": ["Submitted"], "Submitted": ["Approved", "Changes Requested"],
        "Changes Requested": ["Submitted"], "Approved": ["Changes Requested"]}

@app.post("/api/tasks/{tid}/transition")
def move(tid: int, b: Move, u=Depends(user), db=Depends(get_db)):
    t = got(db.get(Task, tid), "Task not found")
    if b.to not in FLOW.get(t.status, []): raise HTTPException(409, f"Cannot move {t.status} to {b.to}")
    if b.to == "Submitted":
        if u.role != "intern" or t.assignee_id != u.id: raise HTTPException(403, "Only the assigned intern can submit")
    else: need(u, "mentor")
    if b.to == "Approved" and any(f.mandatory and f.status in ("Open", "Reopened") for f in t.findings):
        raise HTTPException(409, "Open mandatory findings block approval")
    t.status = b.to; db.add(Audit(msg=f"Task {t.id} -> {b.to} by {u.role}"))
    return apply_completion(db, t.project)

def decide(db, u, fid, text, status):
    need(u, "mentor"); f = got(db.get(Finding, fid), "Finding not found")
    if status != "Reopened" and len(text.strip()) < 10: raise HTTPException(422, "A written reason or evidence (10+ characters) is required")
    f.status = status; f.evidence = text or f.evidence; db.add(Audit(msg=f"Finding {f.id} -> {status} by mentor"))
    return apply_completion(db, f.task.project)

@app.post("/api/findings/{fid}/resolve")
def resolve(fid: int, b: Text, u=Depends(user), db=Depends(get_db)): return decide(db, u, fid, b.text, "Resolved")
@app.post("/api/findings/{fid}/accept-risk")
def accept(fid: int, b: Text, u=Depends(user), db=Depends(get_db)): return decide(db, u, fid, b.text, "Accepted Risk")
@app.post("/api/findings/{fid}/reopen")
def reopen(fid: int, u=Depends(user), db=Depends(get_db)): return decide(db, u, fid, "", "Reopened")

@app.post("/api/projects/{pid}/tests")
def record_test(pid: int, b: TestIn, u=Depends(user), db=Depends(get_db)):
    need(u, "mentor", "admin")  # production: written only by the sandboxed test runner
    r = got(db.query(TestRun).filter_by(project_id=pid, name=b.name).first(), "Unknown test")
    r.passed = b.passed; return apply_completion(db, db.get(Project, pid))

@app.post("/api/docs/{did}/accept")
def accept_doc(did: int, u=Depends(user), db=Depends(get_db)):
    need(u, "mentor"); d = got(db.get(Doc, did), "Document not found"); d.accepted = True
    return apply_completion(db, db.get(Project, d.project_id))

@app.post("/api/projects/{pid}/final-approval")
def final(pid: int, u=Depends(user), db=Depends(get_db)):
    need(u, "mentor"); p = got(db.get(Project, pid), "Project not found")
    if not evaluate(p)["base_ok"]: raise HTTPException(409, "Other requirements are not met yet")
    p.final_approval = True; db.add(Audit(msg=f"Final approval recorded for project {pid}"))
    return apply_completion(db, p)

@app.post("/api/import/validate")
def validate(b: Text, u=Depends(user), db=Depends(get_db)):
    need(u, "admin"); rows, ids, ems = [], set(), set()
    for i, r in enumerate(csv.DictReader(io.StringIO(b.text)), start=2):
        sid, em = (r.get("id") or "").strip(), (r.get("email") or "").strip().lower()
        err = ("Missing required field" if not sid or not (r.get("name") or "").strip() or not em else
               "Invalid email" if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", em) else
               "Duplicate student ID" if sid in ids else "Duplicate email" if em in ems else
               "Account already exists" if db.query(User).filter_by(email=em).first() else "")
        if not err: ids.add(sid); ems.add(em)
        rows.append({"row": i, "id": sid, "error": err})
    bad = sum(bool(r["error"]) for r in rows)
    return {"valid": len(rows) - bad, "rejected": bad, "rows": rows}

@app.get("/api/outbox")
def outbox(u=Depends(user), db=Depends(get_db)):
    need(u, "admin"); return [{"key": o.key, "kind": o.kind, "to": o.recipient_role, "status": o.status} for o in db.query(Outbox)]

@app.get("/api/ai/status")
def ai_status():
    return gemini_test_conn()

@app.post("/api/ai/tutor")
def ai_tutor(b: TutorIn):
    try:
        reply = gemini_tutor(b.message, b.history, b.context)
        return {"reply": reply, "model": "gemini-3.5-flash-lite"}
    except Exception as e:
        raise HTTPException(500, f"AI Tutor error: {str(e)}")

@app.post("/api/ai/review")
def ai_review(b: ReviewIn, db=Depends(get_db)):
    try:
        result = gemini_review(b.code, b.commit_msg)
        db.add(Audit(msg=f"Gemini AI Review: {result.get('summary', 'Code reviewed')} (passed={result.get('passed', False)})"))
        db.commit()
        return result
    except Exception as e:
        raise HTTPException(500, f"AI Review error: {str(e)}")

FE = Path(__file__).resolve().parents[2] / "frontend"
if FE.exists(): app.mount("/", StaticFiles(directory=FE, html=True), name="fe")
