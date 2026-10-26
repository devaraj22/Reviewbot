"""Single authoritative completion evaluator. Deterministic; safe to run repeatedly."""
from sqlalchemy.exc import IntegrityError
from .models import Outbox, Audit, now

def evaluate(p):
    mt = [t for t in p.tasks if t.mandatory]
    ap = [t for t in mt if t.status == "Approved"]
    allf = [f for t in p.tasks for f in t.findings if f.mandatory]
    openf = [f for f in allf if f.status in ("Open", "Reopened")]
    rt = [x for x in p.tests if x.required]; rtp = [x for x in rt if x.passed]
    rd = [d for d in p.docs if d.required]; rdp = [d for d in rd if d.accepted]
    base = [
        {"key": "mandatory_tasks_approved", "ok": len(ap) == len(mt), "detail": f"{len(ap)}/{len(mt)}"},
        {"key": "mandatory_findings_closed", "ok": not openf, "detail": f"{len(openf)} open"},
        {"key": "required_tests_pass", "ok": len(rtp) == len(rt), "detail": f"{len(rtp)}/{len(rt)}"},
        {"key": "required_docs_accepted", "ok": len(rdp) == len(rd), "detail": f"{len(rdp)}/{len(rd)}"},
    ]
    final = {"key": "mentor_final_approval", "ok": bool(p.final_approval), "detail": "recorded" if p.final_approval else "missing"}
    conds = base + [final]
    units = len(mt) + len(allf) + len(rt) + len(rd) + 1
    got = len(ap) + (len(allf) - len(openf)) + len(rtp) + len(rdp) + (1 if p.final_approval else 0)
    done = all(c["ok"] for c in conds); pre = all(c["ok"] for c in base)
    return {"done": done, "base_ok": pre, "percent": round(100 * got / units),
            "status": "Completed" if done else "Awaiting Final Approval" if pre else "In Progress", "conditions": conds}

def _queue(db, key, kind):
    for role in ("intern", "mentor", "admin"):
        k = f"{key}:{role}"
        if db.query(Outbox).filter_by(key=k).first(): continue
        try:
            with db.begin_nested(): db.add(Outbox(key=k, kind=kind, recipient_role=role))
        except IntegrityError: pass

def apply_completion(db, p):
    e = evaluate(p)
    if e["done"] and p.status != "Completed":
        p.epoch += 1; p.status = "Completed"; p.completed_at = now()
        db.add(Audit(msg=f"Project {p.id} COMPLETED (policy v{p.policy_version})"))
        _queue(db, f"completed:{p.id}:{p.epoch}", "project_completed")
    elif not e["done"] and p.status == "Completed":
        p.status = e["status"]; p.completed_at = None; p.final_approval = False
        db.add(Audit(msg=f"Project {p.id} completion revoked: a mandatory condition became invalid"))
        _queue(db, f"reopened:{p.id}:{p.epoch}", "project_reopened")
    elif not e["done"]:
        p.status = e["status"]
    db.commit()
    return evaluate(p)
