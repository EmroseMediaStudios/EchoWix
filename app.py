#!/usr/bin/env python3
"""
EchoWix — AI Voice Clone Chat & Call
Flask + flask-socketio backend for text chat and live phone-call-style voice
Uses OpenAI GPT-4o, Whisper, and ElevenLabs TTS
"""

import gevent.monkey
gevent.monkey.patch_all()

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


# ---- CONVERSATION MEMORY (per-user) ----

conversations = {}

def get_user_sid():
    """Session ID is the logged-in username — each user gets their own conversation."""
    return session.get('username', 'anonymous')

def get_conversation(sid):
    if sid not in conversations:
        conversations[sid] = []
    return conversations[sid]

def add_message(sid, role, content):
    conv = get_conversation(sid)
    conv.append({"role": role, "content": content})
    mx = CONFIG.get('max_history', 20)
    if len(conv) > mx:
        conversations[sid] = conv[-mx:]

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
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(sid)
    resp = openai.chat.completions.create(
        model=CONFIG.get('model', 'gpt-4o'),
        messages=messages,
        temperature=0.85,
        max_tokens=150,
    )
    ai_text = resp.choices[0].message.content
    add_message(sid, "assistant", ai_text)
    return ai_text


def stream_ai_sentences(sid, user_text):
    """Stream GPT response and yield complete sentences as they form."""
    add_message(sid, "user", user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(sid)
    
    call_model = CONFIG.get('call_model', 'gpt-4o-mini')
    stream = openai.chat.completions.create(
        model=call_model,
        messages=messages,
        stream=True,
        temperature=0.85,
        max_tokens=150,
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
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(sid)

    def generate():
        full = ""
        try:
            stream = openai.chat.completions.create(
                model=CONFIG.get('model', 'gpt-4o'),
                messages=messages,
                stream=True,
                temperature=0.85,
                max_tokens=150,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full += (delta.content or "")
                    yield f"data: {json.dumps({'text': delta.content})}\n\n"
            add_message(sid, "assistant", full)
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
    if sid in conversations:
        conversations[sid] = []
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
