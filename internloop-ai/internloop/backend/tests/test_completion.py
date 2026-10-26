import os, pathlib
pathlib.Path("test.db").unlink(missing_ok=True)
os.environ.update(DATABASE_URL="sqlite:///./test.db", DEMO_MODE="true", SECRET_KEY="t")
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app); c.post("/api/dev/seed")
def H(r): return {"Authorization": "Bearer " + c.post("/api/login", json={"email": f"{r}@demo.test", "password": "demo-pass"}).json()["token"]}
def status(): return c.get("/api/projects/1", headers=H("mentor")).json()["evaluation"]["status"]
def post(path, who, **j): return c.post(path, headers=H(who), json=j or None)

def test_auth_and_roles():
    assert c.get("/api/projects/1").status_code == 401
    assert post("/api/tasks/1/transition", "intern", to="Approved").status_code == 403
    assert c.get("/api/outbox", headers=H("mentor")).status_code == 403

def test_blocks():
    assert post("/api/tasks/1/transition", "mentor", to="Approved").status_code == 409   # open finding
    assert post("/api/tasks/4/transition", "mentor", to="Approved").status_code == 409   # invalid transition
    assert post("/api/findings/1/resolve", "mentor", text="ok").status_code == 422        # needs evidence
    assert post("/api/projects/1/final-approval", "mentor").status_code == 409

def test_full_flow():
    post("/api/findings/1/resolve", "mentor", text="validation added in commit abc123")
    post("/api/tasks/1/transition", "mentor", to="Approved"); post("/api/tasks/2/transition", "mentor", to="Approved")
    post("/api/docs/1/accept", "mentor")
    assert status() == "In Progress"                                                      # required test not passed
    post("/api/projects/1/tests", "mentor", name="test_enrollment_limits", passed=False)
    assert post("/api/projects/1/final-approval", "mentor").status_code == 409            # failing test blocks
    post("/api/projects/1/tests", "mentor", name="test_enrollment_limits", passed=True)
    assert status() == "Awaiting Final Approval"
    r = post("/api/projects/1/final-approval", "mentor").json()
    assert r["done"] and r["status"] == "Completed"                                       # optional T4 ignored
    for _ in range(3): post("/api/projects/1/tests", "mentor", name="test_enrollment_limits", passed=True)
    box = c.get("/api/outbox", headers=H("admin")).json()
    assert len([o for o in box if o["kind"] == "project_completed"]) == 3                 # no duplicates
    assert all(o["status"] == "preview-not-sent" for o in box)
    post("/api/tasks/2/transition", "mentor", to="Changes Requested")                     # reopen
    assert status() != "Completed"

def test_import_validation():
    t = "id,name,email\nS1,A,a@x.edu\nS2,B,bad\nS1,C,c@x.edu\nS4,D,a@x.edu\n,E,e@x.edu"
    r = post("/api/import/validate", "admin", text=t).json()
    assert [x["error"] for x in r["rows"]] == ["", "Invalid email", "Duplicate student ID", "Duplicate email", "Missing required field"]
