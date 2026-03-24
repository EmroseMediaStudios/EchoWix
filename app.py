#!/usr/bin/env python3
"""
EchoWix — AI Voice Clone Chat & Call
Flask + flask-socketio backend for text chat and live phone-call-style voice
Uses OpenAI GPT-4o, Whisper, and ElevenLabs TTS
"""

import gevent.monkey
gevent.monkey.patch_all()
import gevent

import json
import os
import re
import base64
import hashlib
import tempfile
import time
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, jsonify, Response, redirect, url_for
from flask_socketio import SocketIO, emit
import openai
import httpx

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = int(os.getenv('SESSION_TIMEOUT_MINUTES', 120)) * 60  # default 2 hours
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*")

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
openai.api_key = OPENAI_API_KEY


# ---- CONFIG ----

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "name": "EchoWix",
            "avatar_name": "Steve",
            "voice_id": "PLACEHOLDER_VOICE_ID",
            "model": "gpt-4o",
            "max_history": 20,
            "tts_model": "eleven_multilingual_v2",
            "tts_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3}
        }

CONFIG = load_config()


def _load_system_prompt():
    prompt_file = CONFIG.get("system_prompt_file")
    if prompt_file:
        prompt_path = os.path.join(os.path.dirname(__file__), prompt_file)
        try:
            with open(prompt_path, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            pass
    return CONFIG.get("system_prompt", "You are a conversational AI. Be natural and concise.")

SYSTEM_PROMPT = _load_system_prompt()


# ---- CONTEXT / MEMORIES ----
# Load optional context file with stories, events, reference material.
# This gets injected alongside the system prompt to give Steve depth.

def _load_context():
    context_file = CONFIG.get("context_file", "context.md")
    context_path = os.path.join(os.path.dirname(__file__), context_file)
    if os.path.exists(context_path):
        try:
            with open(context_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except IOError:
            pass
    return None

def _load_person_context(username):
    """Load per-person knowledge file if it exists."""
    person_path = os.path.join(os.path.dirname(__file__), 'people', f'{username}.md')
    if os.path.exists(person_path):
        try:
            with open(person_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except IOError:
            pass
    return None

CONTEXT = _load_context()


# ---- MEMORY SYSTEM (per-user long-term recall) ----
# After each exchange, GPT extracts key memories from the conversation.
# Before each response, relevant memories are searched and injected.
# This gives Steve persistent recall across sessions.

MEMORY_DIR = os.path.join(os.path.dirname(__file__), '.memories')
os.makedirs(MEMORY_DIR, exist_ok=True)

def _memory_path(username):
    return os.path.join(MEMORY_DIR, f"{username}.json")

def load_memories(username):
    path = _memory_path(username)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_memories(username, memories):
    path = _memory_path(username)
    with open(path, 'w') as f:
        json.dump(memories, f, indent=2)

def search_memories(username, query, max_results=8):
    """Simple keyword search through memories. Returns most relevant entries."""
    memories = load_memories(username)
    if not memories:
        return []
    
    query_words = set(query.lower().split())
    scored = []
    for mem in memories:
        mem_text = mem.get('content', '').lower()
        # Score by keyword overlap + recency bonus
        matches = sum(1 for w in query_words if w in mem_text and len(w) > 2)
        if matches > 0:
            scored.append((matches, mem))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_results]]

def extract_memories_async(username, user_text, ai_text):
    """Background: ask GPT to extract memorable facts from this exchange."""
    try:
        resp = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": """Extract key facts, preferences, emotions, or events worth remembering from this conversation exchange. Return a JSON array of short memory strings. Only include things worth recalling in future conversations — skip generic pleasantries.

Examples of good memories:
- "Mentioned they had a rough day at work on March 24"
- "Said they're thinking about getting a dog"  
- "Was feeling lonely and missing family"
- "Excited about a new project they're starting"
- "Prefers being called 'babe' sometimes"

If nothing worth remembering, return an empty array: []
Return ONLY the JSON array, no other text."""},
                {"role": "user", "content": f"User said: {user_text}\n\nSteve replied: {ai_text}"}
            ],
            temperature=0.3,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        # Parse JSON array from response
        if raw.startswith('['):
            new_memories = json.loads(raw)
        else:
            # Try to find array in response
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                new_memories = json.loads(match.group())
            else:
                return
        
        if not new_memories:
            return
        
        existing = load_memories(username)
        timestamp = time.strftime('%Y-%m-%d %H:%M')
        for mem_text in new_memories:
            if isinstance(mem_text, str) and mem_text.strip():
                existing.append({
                    'content': mem_text.strip(),
                    'timestamp': timestamp,
                })
        
        # Keep last 200 memories max
        if len(existing) > 200:
            existing = existing[-200:]
        
        save_memories(username, existing)
        
        # Also append to person file if it exists
        person_path = os.path.join(os.path.dirname(__file__), 'people', f'{username}.md')
        if os.path.exists(person_path):
            try:
                with open(person_path, 'a') as f:
                    for mem_text in new_memories:
                        if isinstance(mem_text, str) and mem_text.strip():
                            f.write(f"\n- [{timestamp}] {mem_text.strip()}")
            except IOError:
                pass
    except Exception as e:
        print(f"Memory extraction error: {e}")


def build_messages(sid):
    """Build the full message list with system prompt + context + person + memories + history."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Layer 1: Core identity (always loaded)
    if CONTEXT:
        msgs.append({"role": "system", "content": f"This is who you are — your life, your family, your experiences. This IS your memory. Draw from it naturally:\n\n{CONTEXT}"})
    
    # Layer 2: Per-person knowledge
    username = session.get('username', 'anonymous')
    person_ctx = _load_person_context(username)
    if person_ctx:
        msgs.append({"role": "system", "content": f"What you know about the person you're talking to right now. Use this naturally — reference things you know about them, but don't be creepy about it:\n\n{person_ctx}"})
    
    # Layer 3: Dynamic memories from past conversations
    history = get_history(sid)
    last_user_msg = ""
    for m in reversed(history):
        if m['role'] == 'user':
            last_user_msg = m['content']
            break
    
    if last_user_msg:
        relevant = search_memories(username, last_user_msg)
        if relevant:
            mem_text = "\n".join(f"- {m['content']} ({m.get('timestamp', '')})" for m in relevant)
            msgs.append({"role": "system", "content": f"Things you remember from past conversations with this person (use naturally, don't list them off):\n{mem_text}"})
    
    msgs.extend(history)
    return msgs


# ---- USER AUTH ----

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')

def _hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def _load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def _save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def _init_users():
    """Create default users file if it doesn't exist."""
    if not os.path.exists(USERS_FILE):
        users = {
            "admin": {"password": _hash_pw("3ThreeIs1!"), "role": "admin", "display_name": "Steve"},
            "drew": {"password": _hash_pw("InfinitePumpkins"), "role": "user", "display_name": "Drew"},
            "kim": {"password": _hash_pw("MoonAndBack"), "role": "user", "display_name": "Kim"},
            "emma": {"password": _hash_pw("LoveYou3000"), "role": "user", "display_name": "Emma"},
        }
        _save_users(users)
        print("Created users.json")

_init_users()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            if request.is_json or request.path.startswith('/api/') or request.path.startswith('/socket.io'):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ---- CONVERSATION MEMORY (per-user, persisted to disk) ----

CONV_DIR = os.path.join(os.path.dirname(__file__), '.conversations')
os.makedirs(CONV_DIR, exist_ok=True)

def get_user_sid():
    """Session ID is the logged-in username — each user gets their own conversation."""
    return session.get('username', 'anonymous')

def _conv_path(sid):
    return os.path.join(CONV_DIR, f"{sid}.json")

def get_conversation(sid):
    path = _conv_path(sid)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def _save_conversation(sid, conv):
    path = _conv_path(sid)
    with open(path, 'w') as f:
        json.dump(conv, f)

def add_message(sid, role, content):
    conv = get_conversation(sid)
    conv.append({"role": role, "content": content})
    mx = CONFIG.get('max_history', 40)
    if len(conv) > mx:
        conv = conv[-mx:]
    _save_conversation(sid, conv)

def clear_user_conversation(sid):
    path = _conv_path(sid)
    if os.path.exists(path):
        os.unlink(path)

def get_history(sid):
    return get_conversation(sid)


# ---- HELPERS ----

def transcribe_audio(audio_bytes):
    """Transcribe audio bytes using OpenAI Whisper."""
    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, 'rb') as f:
            result = openai.audio.transcriptions.create(model="whisper-1", file=f)
        return result.text.strip()
    except Exception as e:
        print(f"Whisper error: {e}")
        return ""
    finally:
        os.unlink(tmp_path)


def get_ai_response(sid, user_text):
    """Get GPT response and add to conversation (for text chat)."""
    add_message(sid, "user", user_text)
    messages = build_messages(sid)
    resp = openai.chat.completions.create(
        model=CONFIG.get('model', 'gpt-4o'),
        messages=messages,
        temperature=0.85,
        max_tokens=500,
    )
    ai_text = resp.choices[0].message.content
    add_message(sid, "assistant", ai_text)
    # Extract memories in background
    username = session.get('username', 'anonymous')
    gevent.spawn(extract_memories_async, username, user_text, ai_text)
    return ai_text


def stream_ai_sentences(sid, user_text):
    """Stream GPT response and yield complete sentences as they form."""
    add_message(sid, "user", user_text)
    messages = build_messages(sid)
    
    call_model = CONFIG.get('call_model', 'gpt-4o-mini')
    stream = openai.chat.completions.create(
        model=call_model,
        messages=messages,
        stream=True,
        temperature=0.85,
        max_tokens=200,
    )
    
    buffer = ""
    full = ""
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            buffer += delta.content
            full += delta.content
            # Check if we have a complete sentence
            while True:
                match = re.search(r'[.!?]+\s*', buffer)
                if match and match.end() < len(buffer):
                    sentence = buffer[:match.end()].strip()
                    buffer = buffer[match.end():]
                    if sentence:
                        yield sentence
                else:
                    break
    
    # Yield remaining text
    if buffer.strip():
        yield buffer.strip()
    
    add_message(sid, "assistant", full)
    # Extract memories in background
    username = session.get('username', 'anonymous')
    gevent.spawn(extract_memories_async, username, user_text, full)


# ---- TTS CACHE ----
# Cache generated audio to avoid re-generating identical phrases.
# Key = hash of (text + model + voice_id + settings). Stored on disk.

TTS_CACHE_DIR = os.path.join(os.path.dirname(__file__), '.tts_cache')
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
TTS_CACHE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

def _cache_key(text, model_id):
    """Generate a cache key from text + model + voice settings."""
    voice_id = CONFIG.get('voice_id', '')
    settings = json.dumps(CONFIG.get('tts_settings', {}), sort_keys=True)
    raw = f"{text}|{model_id}|{voice_id}|{settings}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _cache_get(key):
    """Get cached audio bytes, or None if not cached / expired."""
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < TTS_CACHE_MAX_AGE:
            with open(path, 'rb') as f:
                return f.read()
        else:
            os.unlink(path)  # expired
    return None

def _cache_put(key, audio_bytes):
    """Store audio bytes in cache."""
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    with open(path, 'wb') as f:
        f.write(audio_bytes)


def tts_call(text):
    """Fast TTS for live calls — uses turbo model. Cached."""
    model_id = CONFIG.get('call_tts_model', 'eleven_turbo_v2_5')
    key = _cache_key(text.strip().lower(), model_id)
    cached = _cache_get(key)
    if cached:
        return cached

    voice_id = CONFIG.get('voice_id')
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    tts_settings = CONFIG.get('tts_settings', {})
    payload = {
        "text": text,
        "model_id": CONFIG.get('call_tts_model', 'eleven_turbo_v2_5'),
        "voice_settings": {
            "stability": tts_settings.get('stability', 0.35),
            "similarity_boost": tts_settings.get('similarity_boost', 0.9),
            "style": tts_settings.get('style', 0.55),
            "use_speaker_boost": True,
        },
        "output_format": "mp3_22050_32",
        "optimize_streaming_latency": 4,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code == 200:
        _cache_put(key, resp.content)
        return resp.content
    else:
        print(f"Call TTS error: HTTP {resp.status_code} — {resp.content[:200]}")
        return None


def tts_full(text):
    """Get complete TTS audio as bytes from ElevenLabs. Cached."""
    model_id = CONFIG.get('tts_model', 'eleven_multilingual_v2')
    key = _cache_key(text.strip().lower(), model_id)
    cached = _cache_get(key)
    if cached:
        return cached

    voice_id = CONFIG.get('voice_id')
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    tts_settings = CONFIG.get('tts_settings', {})
    payload = {
        "text": text,
        "model_id": CONFIG.get('tts_model', 'eleven_multilingual_v2'),
        "voice_settings": {
            "stability": tts_settings.get('stability', 0.45),
            "similarity_boost": tts_settings.get('similarity_boost', 0.8),
            "style": tts_settings.get('style', 0.45),
            "use_speaker_boost": True,
        },
        "output_format": "mp3_44100_192",
        "optimize_streaming_latency": 3,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code == 200:
        _cache_put(key, resp.content)
        return resp.content
    else:
        print(f"TTS error: HTTP {resp.status_code} — {resp.content[:200]}")
        return None


# ---- ROUTES ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = data.get('username', '').strip().lower()
        password = data.get('password', '')
        
        users = _load_users()
        user = users.get(username)
        
        if user and user['password'] == _hash_pw(password):
            session.permanent = True
            session['username'] = username
            session['display_name'] = user.get('display_name', username)
            session['role'] = user.get('role', 'user')
            if request.is_json:
                return jsonify({"ok": True})
            return redirect(url_for('index'))
        
        if request.is_json:
            return jsonify({"error": "Invalid credentials"}), 401
        return render_template('login.html',
                               app_name=CONFIG.get('name', 'EchoWix'),
                               error="Invalid username or password")
    
    return render_template('login.html', app_name=CONFIG.get('name', 'EchoWix'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           app_name=CONFIG.get('name', 'EchoWix'),
                           avatar_name=CONFIG.get('avatar_name', 'Steve'),
                           username=session.get('display_name', 'User'))


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    """Text chat with streaming SSE response."""
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    sid = get_user_sid()
    add_message(sid, "user", user_message)
    messages = build_messages(sid)

    def generate():
        full = ""
        try:
            stream = openai.chat.completions.create(
                model=CONFIG.get('model', 'gpt-4o'),
                messages=messages,
                stream=True,
                temperature=0.85,
                max_tokens=500,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full += (delta.content or "")
                    yield f"data: {json.dumps({'text': delta.content})}\n\n"
            add_message(sid, "assistant", full)
            # Extract memories in background
            _uname = session.get('username', 'anonymous')
            gevent.spawn(extract_memories_async, _uname, user_message, full)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            print(f"Chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/tts', methods=['POST'])
@login_required
def tts():
    """One-shot TTS for playing an individual message."""
    data = request.get_json()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400
    try:
        audio = tts_full(text)
        if audio:
            return Response(audio, mimetype='audio/mpeg')
        return jsonify({"error": "TTS failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/clear', methods=['POST'])
@login_required
def clear_conversation():
    sid = get_user_sid()
    clear_user_conversation(sid)
    return jsonify({"ok": True})


# ---- WEBSOCKET: LIVE CALL ----

@socketio.on('connect')
def handle_connect():
    if 'username' not in session:
        return False  # reject unauthenticated WebSocket connections
    sid = get_user_sid()
    print(f"Client connected: {session['username']}")
    emit('connected', {'session_id': sid})


@socketio.on('call_start')
def handle_call_start():
    print(f"Live call started by {session.get('username')}")
    emit('call_ready')


@socketio.on('call_utterance')
def handle_call_utterance(data):
    try:
        sid = get_user_sid()
        audio_data = data.get('audio')
        if not audio_data:
            emit('call_error', {'error': 'No audio data'})
            return

        audio_bytes = base64.b64decode(audio_data)

        # 1. Transcribe
        user_text = transcribe_audio(audio_bytes)
        if not user_text:
            emit('call_resume')
            return

        emit('call_transcription', {'role': 'user', 'text': user_text})

        # 2. Stream GPT response → TTS each sentence as it completes
        full_text = ""
        for sentence in stream_ai_sentences(sid, user_text):
            full_text += (" " if full_text else "") + sentence
            audio = tts_call(sentence)
            if audio:
                b64 = base64.b64encode(audio).decode('utf-8')
                emit('call_audio', {'data': b64})

        if full_text:
            emit('call_transcription', {'role': 'ai', 'text': full_text})

        emit('call_audio_end')

    except Exception as e:
        print(f"Call error: {e}")
        emit('call_error', {'error': str(e)})


@socketio.on('call_interrupt')
def handle_call_interrupt():
    print(f"Call interrupted by {session.get('username')}")


@socketio.on('call_end')
def handle_call_end():
    print(f"Live call ended by {session.get('username')}")


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {session.get('username')}")


if __name__ == '__main__':
    print(f"Starting EchoWix on port 7751...")
    print(f"Avatar: {CONFIG.get('avatar_name', 'Steve')}")
    socketio.run(app, host='0.0.0.0', port=7751, debug=False)
