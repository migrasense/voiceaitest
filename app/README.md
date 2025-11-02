
# 📘 Servoice AI Voice Assistant – Developer & Demo Documentation

## 1. System Overview

Servoice is a **voice-enabled assistant for senior care companies**.
It captures audio from a microphone or WebSocket, transcribes it in real time using **Deepgram**, analyzes intent with **Groq**, and broadcasts transcripts + AI responses to clients (e.g., a Vite UI).

**Main Flow:**

1. 🎤 User speaks → audio sent to `/audio` WebSocket
2. 📝 Deepgram streams back live + final transcripts
3. 🤖 Groq analyzes transcripts for **intent, urgency, language**
4. 📡 Responses are broadcast to all connected clients via `/transcripts/stream`

---

## 2. Directory Layout

```
app/
├── core/
│   ├── config.py              # Global config & logging
│   ├── connection_manager.py  # WebSocket manager (broadcasts to clients)
│
├── models/
│   ├── mock_response.py       # Pre-defined mock responses
│   ├── mock_stt.py            # Mock STT with conversation history
│
├── routers/
│   ├── websocket_routes.py    # /audio + /transcripts/stream endpoints
│   ├── mock_routes.py         # /mock/* endpoints (for Postman/testing)
│
├── services/
│   ├── groq_client.py         # Intent detection using Groq API
│   ├── transcript_service.py  # Wraps Deepgram transcript handling
│
├── main.py                    # FastAPI entrypoint
├── prompt_config.json         # Prompt/response config for Groq
│
clients/
├── mic_client.py              # Streams mic → /audio
├── mic_and_transcript_client.py # Streams mic + listens to transcripts
│
tests/
├── test_app.py                 # Basic FastAPI route tests
├── test_websockets.py          # WebSocket connect tests
├── test_deepgram_integration.py # Optional integration w/ Deepgram
```

---

## 3. Core Components

### A. FastAPI Server (`main.py`)

* Bootstraps app and includes all routers
* CORS enabled for UI connections
* Uses `lifespan` for startup/shutdown logs

### B. Deepgram Service

* **`websocket_routes.py`** → `/audio` WebSocket receives mic audio → streams to Deepgram
* **`transcript_service.py`** → Handles Deepgram transcript events (partial & final)

### C. Groq Service (`groq_client.py`)

* Integrates with Groq’s Llama 3-70B model
* Loads structured policies from **`prompt_config.json`**
* Returns **strict JSON output** with fields:

  ```json
  {
    "original_text": "...",
    "translated_text": "...",
    "detected_language": "en/es/mixed",
    "intent": "appointment",
    "urgent": false,
    "confidence": 0.87,
    "key_phrases": ["doctor", "visit"],
    "ai_response": "We’ve scheduled your appointment.",
    "ai_response_translated": "We’ve scheduled your appointment."
  }
  ```

### D. Mock Services (`mock_routes.py`)

* **`/mock/groq`** → keyword → mock JSON response
* **`/mock-conversation`** → text → Groq → broadcasted response
* **`/conversation-history`** → returns mock conversation history
* **`/reset-conversation`** → clears history

### E. WebSocket Manager (`connection_manager.py`)

* Tracks active connections
* Provides `broadcast()` to push updates to all subscribed clients

### F. Clients

* **`mic_client.py`** → streams mic → `/audio`
* **`mic_and_transcript_client.py`** → streams mic **and** listens on `/transcripts/stream` (demo-friendly)

---

## 4. How to Run

### Start server

```bash
uvicorn app.main:app --reload
```

### Run mic client (audio only → Deepgram → transcript)

```bash
python app/mic_client.py
```

### Run mic + transcript client (full loop: audio + AI response)

```bash
python app/mic_and_transcript_client.py
```

---

## 5. Testing Strategy

### A. Unit Tests

Run:

```bash
pytest -v
```

* `test_app.py` – FastAPI HTTP routes
* `test_websockets.py` – WebSocket `/audio` + `/transcripts/stream`

### B. Integration Tests

```bash
pytest tests/test_deepgram_integration.py -s
```

⚠️ Uses Deepgram credits (manual only)

### C. Postman Collection

* `POST /mock/groq` → `{ "message": "I need to reschedule my caregiver" }`
* `POST /mock-conversation` → free-text Groq simulation
* `GET /conversation-history`
* `POST /reset-conversation`

### D. Manual Demo

1. Start server
2. Run `mic_and_transcript_client.py`
3. Speak test phrases:

   * “I need to reschedule my caregiver” → intent: `caregiver_reschedule`
   * “My mom has an emergency” → intent: `urgent` → response: *“An admin will be with you shortly.”*

---

## 6. Demo Strategy (Credits vs Mock)

### ✅ Credit-Free (Safe for loops/rehearsal)

* Use `/mock/groq` + `/mock-conversation` for scripted responses
* Use `/conversation-history` + `/reset-conversation` for demoing persistence

### ⚡ Real-Time (For WOW moment)

* Run `mic_and_transcript_client.py`
* Speak live → Deepgram transcribes → Groq analyzes → AI admin responds in real time

---

## 7. Admin Training (Future)

* `prompt_config.json` → holds rules for intent classification + response policies
* In future, Admin UI can update config in DB → loaded dynamically → injected into Groq prompt

---

Perfect 🙌 Let’s put together a **Postman Demo Script** you can walk through during your presentation. This will simulate both **mock flow (credit-safe)** and **real flow (live WebSocket + Deepgram + Groq)**.

---

# 🚀 Servoice Demo Script (Postman)

### Prerequisites

* Start your backend:

  ```bash
  uvicorn app.main:app --reload
  ```
* Import the **Servoice Voice Assistant API Postman Collection** (the JSON I gave you earlier).
* Make sure your `.env` contains:

  * `DEEPGRAM_API_KEY`
  * `GROQ_API_KEY`

---

## 1. **Mock Flow (Credit-Free)**

Safe to run multiple times — uses your mock endpoints only.

### Step 1: Mock Groq Intent

**POST → `/mock/groq`**
Body:

```json
{
  "message": "I need to reschedule my caregiver"
}
```

✅ **Expected Output**:

```json
{
  "intent": "caregiver_reschedule",
  "translated_text": "I need to reschedule my caregiver",
  "ai_response": "Sure, let me connect you with our scheduling team.",
  "ai_response_translated": "Sure, let me connect you with our scheduling team.",
  "is_final": true,
  "timestamp": "2025-08-16T..."
}
```

---

### Step 2: Mock Conversation (Groq Live)

**POST → `/mock-conversation`**
Body:

```json
{
  "text": "My mother has an emergency"
}
```

✅ **Expected Output**:

```json
{
  "status": "success",
  "transcript": "My mother has an emergency",
  "intent": "urgent",
  "ai_response": "An admin will be with you shortly.",
  "language": "en",
  "urgent": true
}
```

---

### Step 3: Check Conversation History

**GET → `/conversation-history`**

✅ **Expected Output**:

```json
{
  "history": [
    {
      "transcript": "My mother has an emergency",
      "intent": "urgent",
      "ai_response": "An admin will be with you shortly."
    }
  ],
  "total_messages": 1
}
```

---

### Step 4: Reset Conversation

**POST → `/reset-conversation`**

✅ **Expected Output**:

```json
{ "status": "success", "message": "Conversation reset" }
```

---

## 2. **Real Flow (Optional - Uses Credits)**

⚠️ Only run this during the live demo when you want to impress — it will consume Deepgram + Groq credits.

### Step 1: Connect Audio Stream

* Go to Postman’s **WebSocket tab**
* URL → `ws://localhost:8000/audio`
* Start sending **mic audio** (or pre-recorded audio via `mic_client.py`)

✅ Postman log:

```
Connected → /audio
```

---

### Step 2: Subscribe to Transcript Stream

* In another Postman tab
* URL → `ws://localhost:8000/transcripts/stream`

✅ You will see **real-time transcripts** appear:

```
📝 Transcript: hello
📝 Transcript: how are you doing
```

And final JSON message:

```json
{
  "transcript": "how are you doing",
  "intent": "inquiry",
  "ai_response": "We received your message and will respond soon.",
  "is_final": true,
  "timestamp": "2025-08-16T..."
}
```

---

## 3. **Suggested Demo Flow**

1. **Start with Mock** (no cost): Show intent detection + AI admin response.
2. **Show Conversation History**: “See? It keeps track of messages.”
3. **Live WebSocket Demo**: Say into your mic → audience sees **real-time transcription + AI admin reply**.
4. **Reset Conversation**: Start fresh.

---

# 🚀 Servoice Postman

```json
{
  "info": {
    "name": "Servoice Voice Assistant API",
    "_postman_id": "servoce-api-demo",
    "description": "Postman collection for testing Servoice voice assistant backend (mock + real endpoints).",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Mock - Groq",
      "request": {
        "method": "POST",
        "header": [{ "key": "Content-Type", "value": "application/json" }],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"message\": \"I need to reschedule my caregiver\"\n}"
        },
        "url": { "raw": "http://localhost:8000/mock/groq", "protocol": "http", "host": ["localhost"], "port": "8000", "path": ["mock", "groq"] }
      }
    },
    {
      "name": "Mock - Conversation",
      "request": {
        "method": "POST",
        "header": [{ "key": "Content-Type", "value": "application/json" }],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"text\": \"My mother has an emergency\"\n}"
        },
        "url": { "raw": "http://localhost:8000/mock-conversation", "protocol": "http", "host": ["localhost"], "port": "8000", "path": ["mock-conversation"] }
      }
    },
    {
      "name": "Get Conversation History",
      "request": {
        "method": "GET",
        "url": { "raw": "http://localhost:8000/conversation-history", "protocol": "http", "host": ["localhost"], "port": "8000", "path": ["conversation-history"] }
      }
    },
    {
      "name": "Reset Conversation",
      "request": {
        "method": "POST",
        "url": { "raw": "http://localhost:8000/reset-conversation", "protocol": "http", "host": ["localhost"], "port": "8000", "path": ["reset-conversation"] }
      }
    },
    {
      "name": "Real - WebSocket /audio",
      "event": [
        {
          "listen": "test",
          "script": {
            "exec": [
              "// Use Postman WebSocket testing tab",
              "// ws://localhost:8000/audio"
            ],
            "type": "text/javascript"
          }
        }
      ]
    },
    {
      "name": "Real - WebSocket /transcripts/stream",
      "event": [
        {
          "listen": "test",
          "script": {
            "exec": [
              "// Use Postman WebSocket testing tab",
              "// ws://localhost:8000/transcripts/stream"
            ],
            "type": "text/javascript"
          }
        }
      ]
    }
  ]
}
```

---

### ✅ How to Use

1. Open Postman
2. **Import** → Paste raw text → Save
3. Make sure your server is running (`uvicorn app.main:app --reload`)
4. Test:

   * `Mock - Groq` (simulated intent detection)
   * `Mock - Conversation` (sends text → Groq → broadcast)
   * `Get Conversation History`
   * `Reset Conversation`
   * WebSockets: use Postman’s **WebSocket tab** → `ws://localhost:8000/transcripts/stream`

---
## 🧪 Testing Notes – Why We Use the Original Client

When writing unit tests for our FastAPI endpoints, we originally considered migrating to the modern `httpx.AsyncClient(app=app, base_url=...)` style.

However, the latest versions of `httpx` introduced **breaking changes** that removed the `app` parameter from the `AsyncClient` initializer. This caused errors like:

```
TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'
```

### ✅ Decision

For stability (and to avoid introducing dependency mismatches during demo prep), we decided to **stick with the original client setup** that already works and passes all tests. This ensures:

* Tests run reliably across environments (local + CI/CD)
* No version lock issues with `httpx` or `pytest-asyncio`
* Faster debugging and demo preparation

### 🔮 Future Migration (Optional)

After the demo, we can revisit migration to `AsyncClient` by updating to the latest `httpx` and rewriting tests like so:

```python
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_mock_groq_hello():
    async with AsyncClient(base_url="http://test") as ac:
        response = await ac.post("/mock/groq", json={"message": "hello"})
        assert response.status_code == 200
```

This would require switching to a test client fixture that runs the FastAPI app inside a **TestServer** context (instead of `app=app`).

---