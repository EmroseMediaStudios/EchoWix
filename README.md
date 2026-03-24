# 🔮 EchoWix — AI Voice Clone Chat & Call

A Flask-based web app that lets people text chat and voice call an AI clone of you, using your cloned voice via ElevenLabs TTS.

## Features

- **Text Chat**: Streaming GPT-4o responses via SSE
- **Voice Calls**: Full-duplex "phone call" style — continuous mic, VAD silence detection, real-time TTS response
- **Three-Layer Memory System**:
  - `context.md` — Core identity (always loaded): family, life events, favorites, opinions, stories
  - `people/<username>.md` — Per-person knowledge (loaded when that person chats)
  - `.memories/<username>.json` — Auto-extracted facts from conversations (keyword-searched per message)
- **Persistent Conversations**: Saved to disk per user, survives restarts
- **TTS Audio Cache**: Identical phrases served from disk cache (zero API credits on repeat)
- **Login System**: Per-user accounts with session-based auth and configurable timeout
- **Personality Prompt**: Loaded from `personality.md` — human-first, emotionally present
- **Dark Theme UI**: Navy/blue/orange glassmorphism, responsive (desktop + mobile)
- **Customizable Icons**: All buttons load from `static/img/` with emoji fallbacks

## Tech Stack

- **Backend**: Python Flask + Flask-SocketIO (gevent)
- **Frontend**: Vanilla JavaScript (no frameworks)
- **AI**: OpenAI GPT-4o (text chat), GPT-4o-mini (voice calls + memory extraction), Whisper (STT)
- **TTS**: ElevenLabs — `eleven_multilingual_v2` (text), `eleven_turbo_v2_5` (calls)
- **Real-time**: WebSocket (Socket.IO) for voice, SSE for text streaming
- **Port**: 7751

## File Structure

```
EchoWix/
├── app.py                    # Flask backend, all routes + WebSocket handlers
├── config.json               # App configuration (models, voice, TTS settings)
├── personality.md            # System prompt — who Steve is
├── context.md                # Core identity — family, stories, favorites, opinions
├── people/                   # Per-person knowledge files
│   ├── drew.md
│   ├── kim.md
│   └── emma.md
├── users.json                # User accounts (auto-generated on first run)
├── .env                      # API keys (not in git)
├── .env.example              # API key template
├── requirements.txt          # Python dependencies
├── run.sh                    # Launch script (creates venv, installs deps, starts app)
├── static/img/               # UI icons and avatars
│   ├── avatar.png            # Steve's avatar (header + messages)
│   ├── logo.png              # Logo (left panel on desktop)
│   ├── user-avatar.png       # User's avatar in messages
│   ├── icon-call.png         # Call button
│   ├── icon-hangup.png       # Hangup button
│   ├── icon-menu.png         # Menu button
│   ├── icon-send.png         # Send button
│   └── icon-clear.png        # Clear conversation
├── templates/
│   ├── index.html            # Main app (SPA — HTML + CSS + JS)
│   └── login.html            # Login page
├── .tts_cache/               # Cached TTS audio (gitignored)
├── .conversations/           # Persistent conversation history (gitignored)
└── .memories/                # Auto-extracted user memories (gitignored)
```

## Setup

### 1. Clone
```bash
git clone https://github.com/EmroseMediaStudios/EchoWix.git ~/Desktop/EchoWix
cd ~/Desktop/EchoWix
```

### 2. Configure API Keys
```bash
cp .env.example .env
nano .env
```
```
OPENAI_API_KEY=sk-your-key
ELEVENLABS_API_KEY=your-key
SECRET_KEY=echowix-prod-7751-xk9m2v
SESSION_TIMEOUT_MINUTES=120
```

### 3. Add Images
Copy your icon/avatar files to `static/img/`. All icons have emoji fallbacks if missing.

### 4. Launch
```bash
chmod +x run.sh
./run.sh
```
Opens at `http://localhost:7751`

## User Accounts

Stored in `users.json` (auto-created on first run). Default accounts:

| Username | Password | Notes |
|----------|----------|-------|
| admin | 3ThreeIs1! | Steve (owner) |
| drew | InfinitePumpkins | |
| kim | MoonAndBack | |
| emma | LoveYou3000 | |

- Usernames are auto-lowercased on login
- Passwords are case-sensitive
- Passwords stored as SHA-256 hashes

## Configuration (config.json)

```json
{
  "name": "EchoWix",
  "avatar_name": "Steve",
  "voice_id": "Yq69pIOf18GqcL1d3PUq",
  "system_prompt_file": "personality.md",
  "context_file": "context.md",
  "model": "gpt-4o",
  "call_model": "gpt-4o-mini",
  "call_tts_model": "eleven_turbo_v2_5",
  "max_history": 40,
  "tts_model": "eleven_multilingual_v2",
  "tts_settings": {
    "stability": 0.35,
    "similarity_boost": 0.9,
    "style": 0.55,
    "use_speaker_boost": true
  }
}
```

### Key Settings
- **model**: Used for text chat responses (GPT-4o)
- **call_model**: Used for voice call responses (GPT-4o-mini — faster, cheaper)
- **call_tts_model**: TTS model for calls (`eleven_turbo_v2_5` — low latency)
- **tts_model**: TTS model for click-to-play audio (`eleven_multilingual_v2` — higher quality)
- **max_history**: Messages kept in conversation context (40)
- **tts_settings**: ElevenLabs voice tuning parameters

## Memory System

### Layer 1: Core Identity (`context.md`)
Always loaded. Contains who Steve is — family details, important dates, life events, favorites, opinions, stories, inside jokes. Edit this file to add/change Steve's permanent knowledge.

### Layer 2: Per-Person Knowledge (`people/<username>.md`)
Loaded only when that user is chatting. Pre-filled templates for each user. **Grows automatically** — memory extraction appends timestamped entries from conversations.

### Layer 3: Dynamic Recall (`.memories/<username>.json`)
Auto-extracted facts from every conversation using GPT-4o-mini (runs async in background). Keyword-searched each message — relevant memories injected into the prompt. Max 200 memories per user, max 8 injected per response.

### How It Flows
1. User sends message
2. System builds prompt: personality + context.md + people/user.md + relevant memories + conversation history
3. GPT responds
4. Background: GPT-4o-mini extracts memorable facts → saves to `.memories/` + appends to `people/user.md`

## TTS Cache

Cached in `.tts_cache/` as MP3 files. Cache key = SHA-256 of (text + model + voice_id + settings). Text normalized (lowercase + trimmed). 30-day expiration. Saves ~30-50% on ElevenLabs credits with normal use.

## API Credit Usage

### Text Chat
- **OpenAI only** — no ElevenLabs credits unless user clicks the audio bars
- Memory extraction adds ~50 tokens per exchange (GPT-4o-mini, negligible cost)

### Voice Calls
- **OpenAI**: GPT-4o-mini per exchange (~cheap)
- **ElevenLabs**: TTS per response (~80 chars per exchange)
- Estimated: 4 users casual use ≈ 48% of ElevenLabs Pro plan (500K chars/mo)

## Mobile / Remote Access

### Local Network (text chat only)
```
http://<mac-ip>:7751
```
Voice calls won't work — browsers block mic access on HTTP.

### Remote Access (full features)
```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:7751
```
Share the generated HTTPS URL. Kill with Ctrl+C when done.

## Session Timeout
Default: 2 hours. Override via `SESSION_TIMEOUT_MINUTES` in `.env`.

## VAD Configuration (Voice Calls)
- Silence threshold: 0.015 (trigger recording stop)
- Silence duration: 1000ms
- Interrupt threshold: 0.025 (higher to avoid speaker bleed)
- 3+ consecutive frames above interrupt threshold → stops playback, captures new utterance

## API Routes

### HTTP
- `GET /` — Main app (requires login)
- `GET /login` — Login page
- `POST /login` — Authenticate
- `GET /logout` — End session
- `GET /config` — Public config (name, model)
- `POST /api/chat` — Text chat (streaming SSE)
- `POST /api/tts` — Text-to-speech (returns audio/mpeg)
- `POST /api/clear` — Clear conversation history

### WebSocket (Socket.IO)
- `call_start` → Server begins listening
- `call_utterance` (base64 audio) → STT → GPT → TTS → `call_audio`
- `call_interrupt` → Stop current playback
- `call_end` → End call
- `call_audio` ← Audio response chunks
- `call_audio_end` ← Playback complete, resume listening
- `call_resume` ← Ready for next utterance

## Troubleshooting

### Mic blocked on mobile
Use HTTPS (Cloudflare tunnel). Browsers block `getUserMedia` on HTTP.

### Choppy audio
Uses HTML5 Audio elements (not Web Audio API `decodeAudioData`). If still choppy, check network latency.

### API key errors
Verify `.env` has correct keys. Watch for copy-paste corruption (extra/missing characters).

### gevent/eventlet issues on macOS
App uses gevent (not eventlet). If `kqueue` errors appear, ensure `gevent` is installed: `pip install gevent gevent-websocket`
