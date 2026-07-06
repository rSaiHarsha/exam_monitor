# ExamWatch — Real-Time Multi-Device Proctoring & Coding Platform

ExamWatch is a production-quality, real-time proctoring and candidate coding sandbox platform designed for technical interviews. It enables simultaneous laptop and mobile camera monitoring, dynamically generates interview questions using artificial intelligence, and executes Python/Java code sandboxes with instant dashboard synchronization.

---

## Key Features

1. **Dual-Device WebRTC Proctoring**
   * Establishes real-time video streams from both the candidate's laptop camera and mobile phone camera.
   * Leverages WebRTC peer connections and WebSocket signaling for low-latency live monitoring.
   * Docked picture-in-picture (PiP) feed allowing the proctor to swap primary feeds with a single click.

2. **Persistent Session Scheduling (SQLite 3)**
   * Schedule sessions with custom durations (preset buttons or datetime-local inputs).
   * Active Sessions tab displays ticking countdown timers for running sessions.
   * Clean session ending deactivates feeds and database records instantly.

3. **AI-Powered Question Generation (NVIDIA LLaMA)**
   * Dynamically parses candidate PDF resumes (`pypdf` parser) and matching job descriptions (`sample/job_description.json`).
   * Leverages LLM integration to generate highly customized, JD-aligned interview questions complete with topics, question text, and target sample answers.
   * Auto-caches questions in the SQLite database to persist across page refreshes.

4. **Multi-Language Integrated Code Editor (Judge0 API)**
   * Built-in split-screen candidate code editor supporting **Python 3** and **Java (JDK 17)**.
   * Executes candidate code securely via the public Judge0 Community Edition endpoint.
   * Real-time console log updates synchronizing execution stdout (green) and compilation/runtime errors (red) live onto the Interviewer Dashboard.

5. **Client Warning & Lockout Modals**
   * Displays warning overlays exactly 15 seconds before the scheduled session ends.
   * Automatically disables camera/microphone tracks, terminates sockets, and locks down feeds when the timer reaches 0, preserving the candidate's final code state.

6. **Dangling Connection & Traceback Protection**
   * Implements a custom startup monkeypatch on Windows to silence noisy `ConnectionResetError` (WinError 10054) traces when clients close browser tabs, keeping your terminal logs clean.

---

## Technical Stack

* **Backend**: FastAPI, Uvicorn, SQLite 3, `pypdf`, `openai` (NVIDIA NIM client)
* **Frontend**: HTML5, Vanilla CSS, WebSocket APIs, WebRTC APIs
* **Code Sandbox**: Judge0 Community Edition API

---

## Installation & Setup

1. **Create and Activate a Virtual Environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   source .venv/bin/activate  # macOS/Linux
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set Up Evironment Secrets**:
   Copy `.env.example` to `.env` and fill in your NVIDIA NIM API Key:
   ```bash
   copy .env.example .env
   ```

4. **Run the Application locally**:
   ```bash
   # Run the standard local server (with SSL capability)
   python app.py
   ```

5. **Run in Render container environment**:
   ```bash
   # Run without local SSL certificate locks, using dynamic port variables
   python app_render.py
   ```

---

## How to Use

1. Start the server and navigate to `https://localhost:5002` (or the network IP address listed in your terminal).
2. **Schedule a Session**: Enter a custom duration and click **Schedule Session**.
3. **Open Links**:
   * Open the **Laptop Link** on the candidate's computer (grant camera and microphone permissions).
   * Open the **Mobile Link** on the candidate's phone (placed to capture workspace/side view).
   * Open the **Dashboard Link** on the proctor's screen.
4. **AI Generation**: Click **Generate** in the Questions sidebar header to produce custom interview questions matching the resume and job description.
5. **Code Execution**: In the candidate interface, toggle the code panel (`</>`), pick a language (Python 3 or Java), write code, and click **Run Code**. The output synchronizes instantly to the proctor console.
6. **End Session**: Click **End Session** in the top bar to purge the session from the active list.
