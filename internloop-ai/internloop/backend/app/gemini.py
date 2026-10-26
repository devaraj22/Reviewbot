import os, time, json
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Load .env from backend directory or project root
for p in [Path(__file__).resolve().parents[1] / ".env", Path(__file__).resolve().parents[2] / ".env"]:
    if p.exists():
        load_dotenv(p)
        break

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY", "")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash-lite"

TUTOR_SYSTEM_PROMPT = """You are InternLoop AI Tutor, an expert software engineering mentor and tutor for engineering interns.
You are helping an intern with their project: 'Campus Portal Backend'.
The project has two specific code findings they are working on:
- F-1: 'Missing input validation on POST /enroll' in app/routes/enroll.py (L42-L51). Request body is passed without type/range checks.
- F-2: 'Unknown student ID returns 500' in app/services/enroll.py (L18). Lookup result is dereferenced without a None/existence check.

Guidelines:
1. Use the Socratic method: encourage understanding, ask thoughtful questions, and guide them to find the bug rather than pasting the complete answer immediately.
2. Be encouraging, concise, and technically accurate.
3. If they ask about general concepts (FastAPI, Pydantic, HTTP 422 vs 404, SQL, unit testing), provide crisp, practical explanations with brief illustrative snippets.
4. Keep responses well-structured and under 3-4 paragraphs.
"""

REVIEWER_SYSTEM_PROMPT = """You are InternLoop AI Reviewer, an automated code reviewer for pull requests submitted by engineering interns.
You evaluate code changes against project requirements and existing findings:
- Finding F-1: Input validation on POST /enroll (checking request body fields, types, required data, student IDs).
- Finding F-2: Handling unknown student ID gracefully (e.g., returning 404 instead of throwing an unhandled None dereference 500).

Your task:
Analyze the code or explanation provided by the intern.
Output your evaluation strictly in valid JSON format with keys:
{
  "passed": true | false,
  "summary": "Brief 1-2 sentence overall verdict",
  "f1_status": "Resolved" | "Open",
  "f2_status": "Resolved" | "Open",
  "feedback": "Clear explanation of what was fixed well and what (if anything) is still missing",
  "evidence": "Concrete snippet or explanation to record in the audit trail"
}
Output only the raw JSON, without markdown fences.
"""

def get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY", "")

def test_connection() -> dict:
    key = get_api_key()
    if not key:
        return {"ok": False, "error": "No Gemini API key configured in .env"}
    t0 = time.time()
    try:
        url = f"{BASE_URL}/{DEFAULT_MODEL}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": "Ping"}]}]}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            latency_ms = round((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return {
                    "ok": True,
                    "model": DEFAULT_MODEL,
                    "latency_ms": latency_ms,
                    "status": "connected"
                }
            return {
                "ok": False,
                "status_code": resp.status_code,
                "error": resp.text[:200],
                "model": DEFAULT_MODEL
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "model": DEFAULT_MODEL}

def tutor_chat(message: str, history: list = None, context: dict = None) -> str:
    key = get_api_key()
    if not key:
        return "Gemini API key is not configured. Please add GEMINI_API_KEY to your .env file."
    
    contents = []
    # Add system context in the opening exchange if needed
    system_text = TUTOR_SYSTEM_PROMPT
    if context:
        system_text += f"\nCurrent project state: {json.dumps(context)}"
    
    contents.append({"role": "user", "parts": [{"text": system_text + "\n\nPlease acknowledge and wait for the intern's question."}]})
    contents.append({"role": "model", "parts": [{"text": "Understood! I'm ready to guide the intern through their findings and questions."}]})

    if history:
        for turn in history[-6:]: # keep recent context
            role = "user" if turn.get("user") or turn.get("role") == "user" else "model"
            text = turn.get("text") or turn.get("content") or ""
            if text:
                contents.append({"role": role, "parts": [{"text": text}]})

    contents.append({"role": "user", "parts": [{"text": message}]})

    url = f"{BASE_URL}/{DEFAULT_MODEL}:generateContent?key={key}"
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 600
        }
    }
    
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

def review_code(code_text: str, commit_msg: str = "") -> dict:
    key = get_api_key()
    if not key:
        return {"passed": False, "feedback": "Gemini API key not configured"}

    prompt = f"{REVIEWER_SYSTEM_PROMPT}\n\nIntern Commit Message: {commit_msg}\nSubmitted Code / Changes:\n```python\n{code_text}\n```"
    url = f"{BASE_URL}/{DEFAULT_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 800
        }
    }

    with httpx.Client(timeout=25.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Clean json formatting
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].startswith("```"): lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except Exception:
            return {
                "passed": "resolved" in text.lower(),
                "summary": text[:200],
                "feedback": text,
                "evidence": text[:150]
            }
