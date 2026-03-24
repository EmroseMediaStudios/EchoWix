#!/usr/bin/env python3
"""
EchoWix — Voice Chat/Call Web App
Flask + flask-socketio backend for real-time chat and voice calling
Uses OpenAI GPT-4o, Whisper, and ElevenLabs TTS
"""

import json
import os
import io
import tempfile
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, jsonify, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
import openai
import httpx

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# API keys
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')

# Configure OpenAI
openai.api_key = OPENAI_API_KEY

# Load config
def load_config():
    """Load personality and voice settings from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "name": "EchoWix",
            "voice_id": "PLACEHOLDER_VOICE_ID",
            "system_prompt": "You are a conversational AI clone. Speak naturally and casually, like a real person in a phone conversation. Keep responses concise — 2-3 sentences max unless asked to elaborate. Be warm, authentic, and engaging. Don't be overly formal or robotic.",
            "model": "gpt-4o",
            "max_history": 20,
            "tts_model": "eleven_multilingual_v2",
            "tts_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": 0.3
            }
        }

CONFIG = load_config()

# Load system prompt from personality file if configured, otherwise use inline prompt
def _load_system_prompt():
    prompt_file = CONFIG.get("system_prompt_file")
    if prompt_file:
        prompt_path = os.path.join(os.path.dirname(__file__), prompt_file)
        try:
            with open(prompt_path, 'r') as f:
                content = f.read().strip()
                # Strip markdown comments (lines starting with #) at the very top if desired
                # Actually keep them — GPT handles markdown fine and the headers help structure
                return content
        except FileNotFoundError:
            pass
    return CONFIG.get("system_prompt", "You are a conversational AI. Be natural and concise.")

SYSTEM_PROMPT = _load_system_prompt()

# In-memory conversation storage (keyed by session ID)
conversations = {}

def get_session_id():
    """Get or create a session ID"""
    if 'sid' not in session:
        session['sid'] = os.urandom(16).hex()
    return session['sid']

def get_conversation(session_id):
    """Get conversation history for a session"""
    if session_id not in conversations:
        conversations[session_id] = []
    return conversations[session_id]

def add_message(session_id, role, content):
    """Add a message to conversation history"""
    conv = get_conversation(session_id)
    conv.append({"role": role, "content": content})
    # Keep only last N messages
    max_history = CONFIG.get('max_history', 20)
    if len(conv) > max_history:
        conversations[session_id] = conv[-max_history:]

def get_recent_history(session_id, include_current=False):
    """Get recent conversation history for context"""
    conv = get_conversation(session_id)
    # Return all but the last message (unless include_current)
    if include_current:
        return conv
    return conv[:-1] if conv else []

# Routes

@app.route('/')
def index():
    """Serve the main app"""
    get_session_id()  # Initialize session
    return render_template('index.html', app_name=CONFIG.get('name', 'EchoWix'))

@app.route('/config')
def get_config():
    """Get public config (non-sensitive)"""
    return jsonify({
        "name": CONFIG.get('name'),
        "model": CONFIG.get('model'),
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Text chat endpoint with streaming response"""
    data = request.get_json()
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({"error": "Empty message"}), 400
    
    session_id = get_session_id()
    
    # Add user message to history
    add_message(session_id, "user", user_message)
    
    # Build messages for API call
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(get_recent_history(session_id, include_current=True))
    
    def stream_response():
        """Stream response using SSE"""
        full_response = ""
        try:
            stream = openai.ChatCompletion.create(
                model=CONFIG.get('model', 'gpt-4o'),
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=300
            )
            
            for chunk in stream:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    if 'content' in delta:
                        content = delta['content']
                        full_response += content
                        # Send SSE event
                        yield f"data: {json.dumps({'text': content})}\n\n"
            
            # Add full response to history
            add_message(session_id, "assistant", full_response)
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            print(f"Chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(stream_response(), mimetype='text/event-stream')

@app.route('/api/tts', methods=['POST'])
def tts():
    """Text-to-speech endpoint"""
    data = request.get_json()
    text = data.get('text', '').strip()
    
    if not text:
        return jsonify({"error": "Empty text"}), 400
    
    try:
        voice_id = CONFIG.get('voice_id', 'PLACEHOLDER_VOICE_ID')
        
        # Call ElevenLabs TTS API
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": CONFIG.get('tts_model', 'eleven_multilingual_v2'),
            "voice_settings": CONFIG.get('tts_settings', {}),
            "output_format": "mp3_44100_128"
        }
        
        with httpx.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                return jsonify({"error": "TTS API error"}), 500
            
            # Stream audio back
            def audio_stream():
                for chunk in response.iter_bytes(chunk_size=1024):
                    yield chunk
            
            return Response(audio_stream(), mimetype='audio/mpeg')
    
    except Exception as e:
        print(f"TTS error: {e}")
        return jsonify({"error": str(e)}), 500

# WebSocket events for voice

@socketio.on('connect')
def handle_connect():
    """Client connected"""
    session_id = get_session_id()
    print(f"Client connected: {session_id}")
    emit('connected', {'session_id': session_id})

@socketio.on('voice_start')
def handle_voice_start():
    """Client starts recording"""
    print("Voice recording started")
    emit('voice_ready', broadcast=False)

@socketio.on('voice_data')
def handle_voice_data(data):
    """
    Receive audio blob from client
    data should contain 'audio' (base64 encoded audio blob)
    """
    try:
        session_id = get_session_id()
        audio_data = data.get('audio')
        
        if not audio_data:
            emit('voice_error', {'error': 'No audio data'})
            return
        
        # Save audio to temp file
        import base64
        audio_bytes = base64.b64decode(audio_data)
        
        # Transcribe using Whisper
        transcription = transcribe_audio(audio_bytes)
        user_text = transcription.get('text', '')
        
        if not user_text:
            emit('voice_error', {'error': 'Could not transcribe audio'})
            return
        
        # Add to conversation
        add_message(session_id, "user", user_text)
        emit('transcription', {'text': user_text})
        
        # Get AI response
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(get_recent_history(session_id, include_current=True))
        
        response = openai.ChatCompletion.create(
            model=CONFIG.get('model', 'gpt-4o'),
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        
        ai_text = response.choices[0].message.content
        add_message(session_id, "assistant", ai_text)
        emit('ai_response_text', {'text': ai_text})
        
        # Get TTS audio stream
        voice_id = CONFIG.get('voice_id', 'PLACEHOLDER_VOICE_ID')
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": ai_text,
            "model_id": CONFIG.get('tts_model', 'eleven_multilingual_v2'),
            "voice_settings": CONFIG.get('tts_settings', {}),
            "output_format": "mp3_44100_128"
        }
        
        with httpx.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code == 200:
                # Stream audio chunks to client
                for chunk in response.iter_bytes(chunk_size=4096):
                    import base64
                    audio_b64 = base64.b64encode(chunk).decode('utf-8')
                    emit('audio_chunk', {'data': audio_b64})
                
                emit('audio_end', {})
            else:
                emit('voice_error', {'error': 'TTS API error'})
    
    except Exception as e:
        print(f"Voice data error: {e}")
        emit('voice_error', {'error': str(e)})

def transcribe_audio(audio_bytes):
    """Transcribe audio using OpenAI Whisper"""
    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path, 'rb') as f:
                transcript = openai.Audio.transcribe(
                    model="whisper-1",
                    file=f
                )
            return transcript
        finally:
            os.unlink(tmp_path)
    
    except Exception as e:
        print(f"Transcription error: {e}")
        return {'text': '', 'error': str(e)}

@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected"""
    print("Client disconnected")

if __name__ == '__main__':
    print(f"Starting EchoWix on port 7751...")
    print(f"Personality: {CONFIG.get('name')}")
    socketio.run(app, host='0.0.0.0', port=7751, debug=True)
