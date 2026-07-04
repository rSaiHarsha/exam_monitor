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

app = FastAPI(title="ExamWatch Proctoring Server")

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

PORT = 5002

# =========================================================
# SESSION STORE
# =========================================================
sessions = {}

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
def create_session(request: Request):
    session_id = str(uuid.uuid4())[:8].upper()
    sessions[session_id] = {
        "created_at": time.time()
    }
    
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
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    if device not in ("laptop", "mobile"):
        raise HTTPException(status_code=400, detail="Invalid device.")
        
    return templates.TemplateResponse(
        request,
        "join.html",
        {
            "session_id": session_id,
            "device": device
        }
    )

@app.get("/dashboard/{session_id}", response_class=HTMLResponse)
def dashboard(request: Request, session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "session_id": session_id
        }
    )

@app.post("/cleanup")
def cleanup():
    now = time.time()
    removed = []
    
    for session_id in list(sessions.keys()):
        created_at = sessions[session_id]["created_at"]
        if now - created_at > 3600:
            removed.append(session_id)
            del sessions[session_id]
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
    ssl_keyfile = "key.pem" if os.path.exists("key.pem") else None
    ssl_certfile = "cert.pem" if os.path.exists("cert.pem") else None
    
    print("\n========================================")
    print("✅ EXAM MONITOR FASTAPI SERVER STARTED")
    print("========================================")
    
    protocol = "https" if ssl_certfile else "http"
    print(f"\n📍 Local URL:")
    print(f"   {protocol}://localhost:{PORT}")
    print(f"\n📍 Network URL:")
    print(f"   {protocol}://{LOCAL_IP}:{PORT}")
    print("\n========================================\n")
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=PORT,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        reload=False,
        timeout_graceful_shutdown=1
    )