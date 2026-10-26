import os, datetime as dt
from sqlalchemy import create_engine, String, Boolean, ForeignKey, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./internloop.db"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)
now = lambda: dt.datetime.now(dt.timezone.utc)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(20))  # admin | mentor | intern
    pw_hash: Mapped[str] = mapped_column(String(200))

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="In Progress")
    policy_version: Mapped[int] = mapped_column(default=1)
    epoch: Mapped[int] = mapped_column(default=0)  # completion count; scopes notification keys
    final_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    tasks = relationship("Task", back_populates="project")
    tests = relationship("TestRun")
    docs = relationship("Doc")

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="Assigned")
    project = relationship("Project", back_populates="tasks")
    findings = relationship("Finding", back_populates="task")

class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20), default="Medium")
    status: Mapped[str] = mapped_column(String(20), default="Open")  # Open|Resolved|Reopened|Accepted Risk|Superseded
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    task = relationship("Task", back_populates="findings")

class TestRun(Base):
    __tablename__ = "test_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)

class Doc(Base):
    __tablename__ = "docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)

class Outbox(Base):  # notifications queue here; nothing counts as sent without a provider
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(50))
    recipient_role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="preview-not-sent")

class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    msg: Mapped[str] = mapped_column(Text)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
