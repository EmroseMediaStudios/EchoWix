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
import base64
import tempfile
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, jsonify, Response
from flask_socketio import SocketIO, emit
import openai
import httpx

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
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


# ---- CONVERSATION MEMORY ----

conversations = {}

def get_session_id():
    if 'sid' not in session:
        session['sid'] = os.urandom(16).hex()
    return session['sid']

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
    """Get GPT response and add to conversation."""
    add_message(sid, "user", user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(sid)
    resp = openai.chat.completions.create(
        model=CONFIG.get('model', 'gpt-4o'),
        messages=messages,
        temperature=0.7,
        max_tokens=300,
    )
    ai_text = resp.choices[0].message.content
    add_message(sid, "assistant", ai_text)
    return ai_text


def stream_tts(text):
    """Generator that yields TTS audio chunks from ElevenLabs."""
    voice_id = CONFIG.get('voice_id')
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": CONFIG.get('tts_model', 'eleven_multilingual_v2'),
        "voice_settings": CONFIG.get('tts_settings', {}),
        "output_format": "mp3_44100_128",
    }
    with httpx.stream("POST", url, headers=headers, json=payload, timeout=60) as r:
        if r.status_code == 200:
            for chunk in r.iter_bytes(chunk_size=4096):
                yield chunk
        else:
            print(f"TTS error: HTTP {r.status_code}")


# ---- ROUTES ----

@app.route('/')
def index():
    get_session_id()
    return render_template('index.html',
                           app_name=CONFIG.get('name', 'EchoWix'),
                           avatar_name=CONFIG.get('avatar_name', 'Steve'))


@app.route('/api/chat', methods=['POST'])
def chat():
    """Text chat with streaming SSE response."""
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    sid = get_session_id()
    add_message(sid, "user", user_message)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(sid)

    def generate():
        full = ""
        try:
            stream = openai.chat.completions.create(
                model=CONFIG.get('model', 'gpt-4o'),
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=300,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full_part = delta.content
                    full_part and None  # no-op
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
def tts():
    """One-shot TTS for playing an individual message."""
    data = request.get_json()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400
    try:
        return Response(stream_tts(text), mimetype='audio/mpeg')
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/clear', methods=['POST'])
def clear_conversation():
    sid = get_session_id()
    if sid in conversations:
        conversations[sid] = []
    return jsonify({"ok": True})


# ---- WEBSOCKET: LIVE CALL ----
# The client opens a continuous mic stream. When the user stops talking
# (detected client-side via VAD / silence detection), the client sends
# the accumulated audio blob. The server transcribes, gets GPT response,
# and streams TTS audio back — then the client resumes listening for
# the next utterance. This creates a continuous call feel.

@socketio.on('connect')
def handle_connect():
    sid = get_session_id()
    print(f"Client connected: {sid}")
    emit('connected', {'session_id': sid})


@socketio.on('call_start')
def handle_call_start():
    """Client initiated a live call."""
    print("Live call started")
    emit('call_ready')


@socketio.on('call_utterance')
def handle_call_utterance(data):
    """
    Client sends a completed utterance (detected via silence/VAD).
    audio: base64-encoded audio blob of the utterance.
    """
    try:
        sid = get_session_id()
        audio_data = data.get('audio')
        if not audio_data:
            emit('call_error', {'error': 'No audio data'})
            return

        audio_bytes = base64.b64decode(audio_data)

        # 1. Transcribe
        user_text = transcribe_audio(audio_bytes)
        if not user_text:
            # Silence or unintelligible — resume listening, don't respond
            emit('call_resume')
            return

        emit('call_transcription', {'role': 'user', 'text': user_text})

        # 2. GPT response
        ai_text = get_ai_response(sid, user_text)
        emit('call_transcription', {'role': 'ai', 'text': ai_text})

        # 3. Stream TTS audio back
        for chunk in stream_tts(ai_text):
            b64 = base64.b64encode(chunk).decode('utf-8')
            emit('call_audio', {'data': b64})

        emit('call_audio_end')

    except Exception as e:
        print(f"Call error: {e}")
        emit('call_error', {'error': str(e)})


@socketio.on('call_interrupt')
def handle_call_interrupt():
    """Client interrupted AI speech — stop any pending TTS streaming."""
    print("Call interrupted by user")


@socketio.on('call_end')
def handle_call_end():
    """Client ended the call."""
    print("Live call ended")


@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")


if __name__ == '__main__':
    print(f"Starting EchoWix on port 7751...")
    print(f"Avatar: {CONFIG.get('avatar_name', 'Steve')}")
    socketio.run(app, host='0.0.0.0', port=7751, debug=False)
