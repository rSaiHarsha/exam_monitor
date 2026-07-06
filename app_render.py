import uuid
import time
import socket
import os
from typing import Dict
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles 
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import db

# Windows ProactorEventLoop connection lost error suppression patch
import sys
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost
        def _patched_call_connection_lost(self, exc=None):
            try:
                _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                pass
        _ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost
    except ImportError:
        pass

app = FastAPI(title="ExamWatch Proctoring Server (Render)")
db.init_db()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup recordings folder
RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Mount static files and setup templates
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR), name="recordings")
app.mount("/sample", StaticFiles(directory="sample"), name="sample")
templates = Jinja2Templates(directory="templates")

PORT = int(os.environ.get("PORT", 5002))

# =========================================================
# SESSION STORE
# =========================================================
# Managed via SQLite in db.py

# Store active websocket connections for WebRTC signaling
# session_id -> {device_name -> websocket}
active_connections: Dict[str, Dict[str, WebSocket]] = {}

# =========================================================
# GET LOCAL IP
# =========================================================
def get_local_ip():
    """
    Get local network IP address.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

LOCAL_IP = get_local_ip()

def get_base_url(request: Request):
    """
    Returns base URL of the server, preferring local network IP over localhost
    so that mobile devices on the same WiFi can connect.
    """
    host = request.url.hostname
    if host in ("localhost", "127.0.0.1", None):
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{scheme}://{LOCAL_IP}:{PORT}"
    else:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{scheme}://{request.url.netloc}"

# =========================================================
# ROUTES
# =========================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.get("/create_session")
def create_session(request: Request, duration_minutes: int = 60):
    session_id = str(uuid.uuid4())[:8].upper()
    duration_seconds = duration_minutes * 60
    db.create_session_db(session_id, duration_seconds)
    
    base = get_base_url(request)
    
    return JSONResponse({
        "status": "success",
        "session_id": session_id,
        "base_url": base,
        "laptop_link": f"{base}/join/{session_id}/laptop",
        "mobile_link": f"{base}/join/{session_id}/mobile",
        "dashboard_link": f"{base}/dashboard/{session_id}"
    })

@app.get("/join/{session_id}/{device}", response_class=HTMLResponse)
def join(request: Request, session_id: str, device: str):
    if not db.is_session_active(session_id):
        raise HTTPException(status_code=404, detail="Session not found or inactive.")
    if device not in ("laptop", "mobile"):
        raise HTTPException(status_code=400, detail="Invalid device.")
        
    with db.get_db_connection() as conn:
        row = conn.execute("SELECT expires_at FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        expires_at = row["expires_at"] if row else time.time() + 3600
        
    return templates.TemplateResponse(
        request,
        "join.html",
        {
            "session_id": session_id,
            "device": device,
            "expires_at": expires_at
        }
    )

@app.get("/dashboard/{session_id}", response_class=HTMLResponse)
def dashboard(request: Request, session_id: str):
    if not db.is_session_active(session_id):
        raise HTTPException(status_code=404, detail="Session not found or inactive.")
        
    with db.get_db_connection() as conn:
        row = conn.execute("SELECT expires_at FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        expires_at = row["expires_at"] if row else time.time() + 3600
        
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "session_id": session_id,
            "expires_at": expires_at
        }
    )

@app.get("/list_active_sessions")
def list_active_sessions():
    return JSONResponse(db.get_active_sessions_list())

@app.post("/end_session/{session_id}")
async def end_session(session_id: str):
    db.deactivate_session_db(session_id)
    removed_connections = False
    if session_id in active_connections:
        for device, ws in list(active_connections[session_id].items()):
            try:
                await ws.close(code=1000)
            except Exception:
                pass
        active_connections.pop(session_id, None)
        removed_connections = True
    return JSONResponse({
        "status": "success",
        "session_id": session_id,
        "connections_closed": removed_connections
    })

@app.get("/get_questions/{session_id}")
def get_questions(session_id: str):
    import json
    questions_json = db.get_session_questions(session_id)
    if questions_json:
        try:
            return JSONResponse(json.loads(questions_json))
        except Exception:
            pass
            
    static_path = os.path.join("static", "questions.json")
    if os.path.exists(static_path):
        with open(static_path, "r", encoding="utf-8") as f:
            try:
                return JSONResponse(json.load(f))
            except Exception:
                pass
                
    return JSONResponse([])

@app.post("/generate_questions/{session_id}")
def generate_questions(session_id: str):
    import json
    from llm import LLMManager
    
    duration_seconds = db.get_session_duration(session_id)
    duration_minutes = max(1, duration_seconds // 60)
    num_questions = max(5, min(15, duration_minutes // 5))
    
    jd_data = {}
    jd_path = os.path.join("sample", "job_description.json")
    if os.path.exists(jd_path):
        with open(jd_path, "r", encoding="utf-8") as f:
            try:
                jd_data = json.load(f)
            except Exception:
                pass
                
    jd_text = f"Role: {jd_data.get('role', 'Java Developer')}\n"
    jd_text += f"Experience: {jd_data.get('experience', '3-5 years')}\n"
    jd_text += f"Location: {jd_data.get('location', 'Remote')}\n"
    jd_text += f"Description: {jd_data.get('description', '')}\n"
    jd_text += "Requirements:\n" + "\n".join([f"- {r}" for r in jd_data.get("requirements", [])]) + "\n"
    jd_text += "Responsibilities:\n" + "\n".join([f"- {r}" for r in jd_data.get("responsibilities", [])])
    
    resume_path = os.path.join("sample", "resume.pdf")
    resume_text = ""
    try:
        import pypdf
        reader = pypdf.PdfReader(resume_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                resume_text += page_text + "\n"
    except Exception:
        pass
        
    resume_text = resume_text.strip()
    if not resume_text or "Mock Resume" in resume_text or "replace this file" in resume_text:
        resume_text = """
Name: Jane Doe
Experience: 4 Years as Software Engineer
Skills: Java 11/17, Spring Boot, Spring Data JPA, Microservices, PostgreSQL, Docker, Kafka, RESTful APIs, JUnit, Mockito.
Experience Highlights:
- Senior Developer at Tech Solutions (2022 - Present): Led migration of a legacy monolithic Java system to Spring Boot microservices. Improved system scalability and reduced startup time.
- Java Developer at Innovate LLC (2020 - 2022): Developed features for transactional e-commerce APIs, optimized complex PostgreSQL queries, and wrote comprehensive unit tests.
Education: B.Tech in Computer Science
"""

    prompt = f"""
You are an expert technical interviewer. Your task is to generate a list of technical interview questions for a candidate, based on the Job Description and their Resume.

Job Description:
{jd_text}

Candidate Resume:
{resume_text}

Instructions:
1. Generate exactly {num_questions} questions (based on the session interview time of {duration_minutes} minutes).
2. Focus heavily on the Job Description requirements and match them with relevant aspects from the candidate's resume.
3. The questions should test both conceptual understanding and practical experience.
4. For each question, provide a brief topic, the question text, and a concise expected sample answer.
5. You MUST return ONLY a raw JSON array matching this format (do NOT wrap it in markdown code blocks, do NOT write any introduction or conclusion, just the raw JSON text):
[
  {{
    "id": 1,
    "topic": "Topic Name",
    "question": "Question text?",
    "answer": "Expected brief answer."
  }},
  ...
]
"""
    
    try:
        llm = LLMManager()
        messages = [{"role": "user", "content": prompt}]
        response = llm.get_response(messages, stream=False)
        raw_content = response.choices[0].message.content
        
        raw_content = raw_content.strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:]
        elif raw_content.startswith("```"):
            raw_content = raw_content[3:]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]
        raw_content = raw_content.strip()
        
        parsed_questions = json.loads(raw_content)
        for i, q in enumerate(parsed_questions):
            q["id"] = i + 1
            
        questions_str = json.dumps(parsed_questions)
        db.save_session_questions(session_id, questions_str)
        
        return JSONResponse(parsed_questions)
    except Exception as e:
        print(f"Error in LLM question generation: {e}")
        raise HTTPException(status_code=500, detail=f"LLM question generation failed: {str(e)}")

@app.post("/cleanup")
async def cleanup():
    now = time.time()
    removed = []
    
    # Get all active sessions (this automatically deactivates expired ones in DB)
    active_sessions = db.get_active_sessions_list()
    active_ids = {s["session_id"] for s in active_sessions}
    
    # Close websocket connections for any session in active_connections that is no longer active
    for session_id in list(active_connections.keys()):
        if session_id not in active_ids:
            removed.append(session_id)
            for device, ws in list(active_connections[session_id].items()):
                try:
                    await ws.close(code=1000)
                except Exception:
                    pass
            active_connections.pop(session_id, None)
            
    return JSONResponse({
        "status": "success",
        "removed_count": len(removed),
        "removed_sessions": removed
    })

@app.post("/upload_recording/{session_id}")
async def upload_recording(session_id: str, file: UploadFile = File(...)):
    filename = f"{session_id}_{int(time.time())}.webm"
    filepath = os.path.join(RECORDINGS_DIR, filename)
    with open(filepath, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return JSONResponse({
        "status": "success",
        "filename": filename
    })

@app.get("/list_recordings")
def list_recordings():
    files = []
    if os.path.exists(RECORDINGS_DIR):
        for name in os.listdir(RECORDINGS_DIR):
            if name.endswith(".webm"):
                path = os.path.join(RECORDINGS_DIR, name)
                stat = os.stat(path)
                parts = name.split("_")
                sess_id = parts[0] if len(parts) > 0 else "UNKNOWN"
                files.append({
                    "filename": name,
                    "session_id": sess_id,
                    "size_bytes": stat.st_size,
                    "created_at": stat.st_mtime
                })
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return JSONResponse(files)

@app.post("/execute_code/{session_id}")
async def execute_code(session_id: str, payload: dict):
    import urllib.request
    import json
    import ssl
    
    code = payload.get("code", "")
    language_id = payload.get("language_id", 71) # Python 3 default
    
    data = json.dumps({
        "source_code": code,
        "language_id": language_id
    }).encode("utf-8")
    
    url = "https://ce.judge0.com/submissions?wait=true"
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    
    try:
        response = urllib.request.urlopen(req, context=ctx, timeout=15)
        res_data = json.loads(response.read().decode("utf-8"))
        
        stdout = res_data.get("stdout") or ""
        stderr = res_data.get("stderr") or ""
        compile_output = res_data.get("compile_output") or ""
        message = res_data.get("message") or ""
        
        status_desc = "Accepted"
        status_id = 3
        if "status" in res_data:
            status_desc = res_data["status"].get("description", "Accepted")
            status_id = res_data["status"].get("id", 3)
            
        exec_message = {
            "type": "code_execution",
            "code": code,
            "stdout": stdout,
            "stderr": stderr,
            "compile_output": compile_output,
            "message": message,
            "status_desc": status_desc,
            "status_id": status_id
        }
        await broadcast_to_session(session_id, exec_message)
        
        return JSONResponse(res_data)
        
    except Exception as e:
        print(f"Code execution request failed: {e}")
        error_res = {
            "stdout": "",
            "stderr": f"Execution error: Failed to connect to code execution server ({str(e)})",
            "compile_output": "",
            "message": "Internal Server Error",
            "status": {
                "id": 13,
                "description": "Internal Error"
            }
        }
        return JSONResponse(error_res, status_code=500)

# =========================================================
# WEBSOCKET SIGNALING ENDPOINT
# =========================================================

async def broadcast_to_session(session_id: str, message: dict, exclude: str = None):
    if session_id in active_connections:
        for device, ws in list(active_connections[session_id].items()):
            if device != exclude:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

@app.websocket("/ws/{session_id}/{device}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, device: str):
    if not db.is_session_active(session_id):
        await websocket.accept()
        try:
            await websocket.send_json({"type": "error", "message": "Session is inactive or expired."})
            await websocket.close(code=1008)
        except Exception:
            pass
        return
        
    await websocket.accept()
    
    if session_id not in active_connections:
        active_connections[session_id] = {}
        
    active_connections[session_id][device] = websocket
    
    # Notify others in the session that this peer connected
    await broadcast_to_session(
        session_id,
        {
            "type": "peer_status",
            "device": device,
            "connected": True
        },
        exclude=device
    )
    
    # Send list of online peers to the newly connected device
    online_peers = [d for d in active_connections[session_id].keys() if d != device]
    try:
        await websocket.send_json({
            "type": "online_peers",
            "peers": online_peers
        })
    except Exception:
        pass
        
    try:
        while True:
            data = await websocket.receive_json()
            target = data.get("target")
            data["sender"] = device  # Stamp sender identification
            
            if target:
                target_ws = active_connections[session_id].get(target)
                if target_ws:
                    try:
                        await target_ws.send_json(data)
                    except Exception:
                        pass
            else:
                await broadcast_to_session(session_id, data, exclude=device)
                
    except WebSocketDisconnect:
        if session_id in active_connections:
            active_connections[session_id].pop(device, None)
            if not active_connections[session_id]:
                active_connections.pop(session_id, None)
                
        await broadcast_to_session(
            session_id,
            {
                "type": "peer_status",
                "device": device,
                "connected": False
            },
            exclude=device
        )

# =========================================================
# SERVER START
# =========================================================
if __name__ == "__main__":
    print("\n========================================")
    print("   RENDER FASTAPI SERVER STARTING")
    print("========================================")
    print(f"📍 Listening on port: {PORT}")
    print("========================================\n")
    
    uvicorn.run(
        "app_render:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        timeout_graceful_shutdown=1
    )
