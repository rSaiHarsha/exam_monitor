# ExamWatch — Two-Device Exam Monitor


# new features to add 
1. add a new session managemet button that will shedule a session with timing until that time the session will be active.
2. add a new tab active sessions to views the active sessions. 
3. then add llm ot generate quesitions based on jd and resume .
4. then add llm to check the code written by the candidate . 


A fixed, production-quality POC for simultaneous laptop + mobile camera proctoring.

## Quick Start

```bash
pip install flask flask-cors
python app.py
```

Open the printed URL (e.g. `http://192.168.1.5:5000`) — use this IP-based URL on your phone too.

---

## What Was Fixed

### 🔴 Original Problems → ✅ Fixed

| Problem | Fix |
|---|---|
| Mobile camera never worked | Proper `facingMode` constraints + fallback to relaxed constraints |
| `getUserMedia` silently failed | Full error handling with user-facing messages per error type |
| No CORS headers | `flask-cors` added, allows mobile browser on same network |
| Flask only on localhost | `host="0.0.0.0"` so phones on the same WiFi can connect |
| No connection status | Dashboard shows live/offline per device with timestamps |
| Screen sleep killed mobile stream | `WakeLock API` requested to prevent screen-off |
| No feedback on upload failure | Upload dot turns red on error, recovers automatically |
| Memory leak (frames never cleared) | Frames only kept if device is "connected" (seen < 30s ago) |
| No FPS / resolution info | Status bar shows live FPS and resolution |
| Front camera mirrored weirdly | CSS `scaleX(-1)` only applied to front-facing camera |

---

## Mobile Access — Important

Your phone **must be on the same WiFi** as your computer.

The app prints the correct URL on startup:
```
✅  Exam Monitor running
   Local:   http://localhost:5000
   Network: http://192.168.1.X:5000  ← open this on your phone
```

Use the **Network** URL on your phone. `localhost` will NOT work on mobile.

---

## Architecture

```
Browser (Laptop)          Flask Server             Browser (Mobile)
     |                        |                         |
     |  POST /upload_frame    |   POST /upload_frame    |
     |----------------------->|<------------------------|
     |                        |                         |
     |          GET /get_frames/{id}                    |
Dashboard <------------------|
```

Frames are JPEG-compressed in the browser and POSTed as base64 JSON.
The server stores only the latest frame per device.

---

## How to Use

1. Run `python app.py`
2. Open `http://YOUR_PC_IP:5000` in your laptop browser
3. Click **Create Session** — you get 3 links
4. Open the **Laptop Link** in your laptop browser → allow camera
5. Open the **Mobile Link** on your phone → allow camera  
   *(use Chrome on Android, Safari on iOS)*
6. Open the **Dashboard** to monitor both feeds live

---

## Potential Enhancements

- **HTTPS via ngrok**: `ngrok http 5000` gives you HTTPS + public URL (useful for testing away from same WiFi)
- **WebRTC**: Replace polling with `aiortc` or `simple-peer` for true real-time streaming
- **AI proctoring**: Plug in MediaPipe face detection or YOLO on the server side
- **Recording**: Save frames to disk or S3 periodically
- **Auth**: Add session PIN codes so only the right student can join
