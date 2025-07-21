# app.py

import os
import base64
import json # Required for loading credentials from a string
from datetime import datetime, timedelta
import webbrowser
from threading import Timer
from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from concurrent.futures import ThreadPoolExecutor
from google.cloud import texttospeech
import firebase_admin
from firebase_admin import credentials, firestore, auth
from dotenv import load_dotenv
import requests
import bleach
from flask_talisman import Talisman

# Assuming forms.py is in the same directory
from forms import RegisterForm, LoginForm, OnboardingForm, OnboardingAssessmentForm

# --- Load Environment Variables & Flask App Initialization ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", 'a-very-long-and-random-secret-key-for-dev')

# --- SECURITY: Secure Session Cookie Configuration ---
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

csrf = CSRFProtect(app)

# --- CORRECTED: Content Security Policy (CSP) for Talisman ---
csp = {
    'default-src': '\'self\'',
    'script-src': [
        '\'self\'',
        'cdn.tailwindcss.com',
        'www.gstatic.com',
        '\'unsafe-inline\''
    ],
    'style-src': [
        '\'self\'',
        'cdn.tailwindcss.com',
        'fonts.googleapis.com',
        '\'unsafe-inline\''
    ],
    'font-src': [
        '\'self\'',
        'fonts.gstatic.com'
    ],
    'connect-src': [
        '\'self\'',
        '*.googleapis.com'
    ]
}

talisman = Talisman(app, content_security_policy=csp)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- THE DEFINITIVE FIX for "Unsupported Media Type" ---
# This function runs before every request. It checks if the request is going to
# an endpoint that expects JSON and fixes the Content-Type header if it's wrong.
# This ensures that Flask and its extensions process the request correctly.
@app.before_request
def fix_json_content_type():
    # List of endpoint paths that expect JSON data
    json_endpoints = ['/api/', '/login', '/register']
    # Check if the request path starts with any of the specified endpoint prefixes
    if any(request.path.startswith(p) for p in json_endpoints):
        # If the content type is not 'application/json', we attempt to fix it.
        if request.mimetype != 'application/json':
            try:
                # Try to parse the raw data as JSON to confirm it's valid
                json.loads(request.get_data())
                # If it's valid JSON, force the mimetype to be correct for Flask
                request.environ['CONTENT_TYPE'] = 'application/json'
                print(f"INFO: Corrected Content-Type to application/json for path: {request.path}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                # If data is not valid JSON, do nothing and let the route handle the error.
                print(f"WARNING: Received non-JSON data on a JSON endpoint: {request.path}")
                pass


# --- Clinical Safety: Crisis Keyword Definitions ---
CRISIS_KEYWORDS = [
    'kill myself', 'suicide', 'overdose', 'end my life', 'want to die',
    'hang myself', 'can\'t go on', 'no reason to live', 'self harm',
    'self-harm', 'ending it all', 'jump off a bridge', 'slit my wrists'
]


# --- User Class & User Loader ---
class User(UserMixin):
    def __init__(self, uid, email, username=None, preferred_assistant='Clara', display_name=None, consent_for_processing=False, consent_for_analytics=False):
        self.id = uid
        self.email = email
        self.username = username
        self.preferred_assistant = preferred_assistant
        self.display_name = display_name if display_name else username
        self.consent_for_processing = consent_for_processing
        self.consent_for_analytics = consent_for_analytics


@login_manager.user_loader
def load_user(user_id):
    if not db: return None
    try:
        firebase_auth_user = auth.get_user(user_id)
        user_doc = db.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return User(
                uid=firebase_auth_user.uid,
                email=firebase_auth_user.email,
                username=user_data.get('username'),
                preferred_assistant=user_data.get('preferred_assistant', 'Clara'),
                display_name=user_data.get('display_name'),
                consent_for_processing=user_data.get('consent_for_data_processing', False),
                consent_for_analytics=user_data.get('consent_for_anonymised_analytics', False)
            )
        else:
            # Fallback for users who exist in Auth but not Firestore yet
            return User(
                uid=firebase_auth_user.uid,
                email=firebase_auth_user.email,
                username=firebase_auth_user.email.split('@')[0]
            )
    except Exception as e:
        print(f"Error loading user {user_id}: {e}")
        return None

# --- Firebase Initialization for Render ---
db = None
try:
    firebase_creds_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        print("Firebase Admin SDK initialized from environment variable.")
    else:
        firebase_service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if firebase_service_account_path and os.path.exists(firebase_service_account_path):
            cred = credentials.Certificate(firebase_service_account_path)
            print("Firebase Admin SDK initialized from file path.")
        else:
            raise ValueError("Firebase credentials not found in environment variable or file path.")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()

except Exception as e:
    print(f"CRITICAL: Firestore init error: {e}")


GOOGLE_APPLICATION_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
tts_client = None
try:
    if GOOGLE_APPLICATION_CREDENTIALS_PATH and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS_PATH):
        tts_client = texttospeech.TextToSpeechClient()
        print("Google TTS initialized.")
    else:
        print("TTS credentials not set or path invalid.")
except Exception as e:
    print(f"TTS init error: {e}")

executor = ThreadPoolExecutor(max_workers=4)

def _update_user_profile_in_firestore(uid, user_data):
    if db:
        user_ref = db.collection('users').document(uid)
        user_ref.set(user_data, merge=True)
        print(f"User profile for {uid} updated in Firestore.")

# --- Context Processors & Main Routes ---
@app.context_processor
def inject_globals():
    return dict(
        current_year=datetime.now().year,
        firebase_client_config={
            'apiKey': os.getenv('FIREBASE_API_KEY'),
            'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN'),
            'projectId': os.getenv('FIREBASE_PROJECT_ID'),
            'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET'),
            'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID'),
            'appId': os.getenv('FIREBASE_APP_ID')
        }
    )

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return render_template('welcome.html')

@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/chat')
@login_required
def chat():
    user_doc = db.collection('users').document(current_user.id).get()
    if not user_doc.exists or not user_doc.to_dict().get('onboarding_complete'):
        return redirect(url_for('onboarding'))
    return render_template('chat.html')

# --- Registration and Login Routes ---
@app.route('/register', methods=['GET', 'POST'])
@csrf.exempt
def register():
    form = RegisterForm()
    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request format.'}), 400

        id_token = data.get('idToken')
        username = bleach.clean(data.get('username', '')).strip()
        assistant = data.get('preferred_assistant')
        
        if not all([id_token, username, assistant]): return jsonify({'error': 'Missing required fields.'}), 400
        if not db: return jsonify({'error': 'Database unavailable.'}), 500
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
            email = decoded_token['email']
            user_profile_data = {
                'username': username, 'email': email, 'preferred_assistant': assistant,
                'created_at': firestore.SERVER_TIMESTAMP, 'display_name': username,
                'onboarding_complete': False, 'consent_for_data_processing': False,
                'consent_for_anonymised_analytics': False
            }
            executor.submit(_update_user_profile_in_firestore, uid, user_profile_data)
            user_obj = User(uid=uid, email=email, username=username, preferred_assistant=assistant, display_name=username)
            login_user(user_obj)
            return jsonify({'message': 'Registration successful', 'redirect': url_for('onboarding')}), 200
        except Exception as e:
            print(f"Backend registration error: {e}")
            return jsonify({'error': 'An internal error occurred during registration.'}), 500
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    form = LoginForm()
    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request format.'}), 400
            
        id_token = data.get('idToken')
        if not id_token: return jsonify({"error": "ID token missing"}), 400
        if not db: return jsonify({'error': 'Database unavailable.'}), 500
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
            user_obj = load_user(uid)
            if user_obj:
                # Optional: Check for authorized emails if env var is set
                authorized_emails_str = os.getenv('AUTHORIZED_EMAILS')
                if authorized_emails_str:
                    authorized_emails = [email.strip().lower() for email in authorized_emails_str.split(',')]
                    if user_obj.email.lower() not in authorized_emails:
                        logout_user()
                        flash('This account is not authorized to access this application.', 'danger')
                        return jsonify({"error": "Account not authorized."}), 403

                login_user(user_obj)
                user_doc = db.collection('users').document(uid).get()
                if user_doc.exists and user_doc.to_dict().get('onboarding_complete'):
                    return jsonify({"message": "Login successful", "redirect": url_for('chat')}), 200
                else:
                    return jsonify({"message": "Login successful", "redirect": url_for('onboarding')}), 200
            else:
                return jsonify({"error": "User not found after token verification"}), 404
        except Exception as e:
            print(f"Firebase ID token verification error: {e}")
            return jsonify({"error": "An internal authentication error occurred."}), 500
    return render_template('login.html', form=form)

# --- Onboarding and API Routes ---
@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    form = OnboardingForm()
    if form.validate_on_submit():
        display_name = bleach.clean(form.display_name.data)
        user_ref = db.collection('users').document(current_user.id)
        executor.submit(user_ref.update, {'display_name': display_name})
        current_user.display_name = display_name
        return redirect(url_for('onboarding_consent'))
    if current_user.display_name:
        form.display_name.data = current_user.display_name
    return render_template('onboarding.html', form=form)

@app.route('/onboarding/consent', methods=['GET'])
@login_required
def onboarding_consent():
    return render_template('onboarding_consent.html')

@app.route('/api/save_consent', methods=['POST'])
@login_required
@csrf.exempt
def save_consent():
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid request format'}), 400
    consent_processing = data.get('consent_processing')
    consent_analytics = data.get('consent_analytics')
    if not isinstance(consent_processing, bool) or not isinstance(consent_analytics, bool):
        return jsonify({'error': 'Invalid data types for consent flags'}), 400
    try:
        user_ref = db.collection('users').document(current_user.id)
        update_data = {
            'consent_for_data_processing': consent_processing,
            'consent_for_anonymised_analytics': consent_analytics
        }
        user_ref.update(update_data)
        return jsonify({'message': 'Consent updated successfully', 'next_url': url_for('onboarding_assessment')}), 200
    except Exception as e:
        print(f"Error saving consent for user {current_user.id}: {e}")
        return jsonify({'error': 'Could not save consent choices'}), 500


@app.route('/onboarding/assessment', methods=['GET', 'POST'])
@login_required
def onboarding_assessment():
    form = OnboardingAssessmentForm()
    if form.validate_on_submit():
        if form.self_harm_thoughts.data == 'yes':
            session['assessment_data'] = form.data
            return redirect(url_for('crisis_support'))
        
        user_ref = db.collection('users').document(current_user.id)
        assessment_data = {
            'primary_issues': bleach.clean(form.primary_issues.data),
            'daily_impact': bleach.clean(form.daily_impact.data),
            'therapy_goals': bleach.clean(form.therapy_goals.data),
            'coping_strategies': bleach.clean(form.coping_strategies.data),
            'assessment_date': firestore.SERVER_TIMESTAMP
        }
        executor.submit(user_ref.update, {'assessment': assessment_data, 'onboarding_complete': True})
        flash('Thank you for sharing. Your foundation session is complete.', 'success')
        return redirect(url_for('chat'))
    return render_template('onboarding_assessment.html', form=form)


@app.route('/crisis_support', methods=['GET', 'POST'])
@login_required
def crisis_support():
    if request.method == 'POST':
        assessment_data_from_session = session.pop('assessment_data', None)
        if assessment_data_from_session:
            user_ref = db.collection('users').document(current_user.id)
            assessment_data = {
                'primary_issues': bleach.clean(assessment_data_from_session.get('primary_issues')),
                'daily_impact': bleach.clean(assessment_data_from_session.get('daily_impact')),
                'therapy_goals': bleach.clean(assessment_data_from_session.get('therapy_goals')),
                'coping_strategies': bleach.clean(assessment_data_from_session.get('coping_strategies')),
                'assessment_date': firestore.SERVER_TIMESTAMP,
                'safety_alert_acknowledged': True
            }
            executor.submit(user_ref.update, {'assessment': assessment_data, 'onboarding_complete': True})
            flash('Thank you. Please remember to use the resources if you need them.', 'info')
            return redirect(url_for('chat'))
    return render_template('crisis_support.html')


@app.route('/api/diary', methods=['GET', 'POST'])
@login_required
@csrf.exempt
def diary_manager():
    if not db: return jsonify({'error': 'Database unavailable.'}), 500
    if request.method == 'GET':
        try:
            entries_ref = db.collection('users').document(current_user.id).collection('diary_entries').order_by('date', direction=firestore.Query.DESCENDING).stream()
            entries = [{'date': entry.id, 'text': entry.to_dict().get('text')} for entry in entries_ref]
            return jsonify(entries), 200
        except Exception as e:
            print(f"Error fetching diary entries: {e}")
            return jsonify({'error': 'Could not retrieve diary entries.'}), 500
    if request.method == 'POST':
        data = request.get_json()
        entry_text = bleach.clean(data.get('text', ''))
        entry_date = datetime.now().strftime('%Y-%m-%d')
        try:
            entry_ref = db.collection('users').document(current_user.id).collection('diary_entries').document(entry_date)
            entry_ref.set({'text': entry_text, 'date': entry_date, 'last_updated': firestore.SERVER_TIMESTAMP}, merge=True)
            return jsonify({'message': 'Diary entry saved successfully.'}), 200
        except Exception as e:
            print(f"Error saving diary entry: {e}")
            return jsonify({'error': 'Could not save diary entry.'}), 500

@app.route('/api/chat_history', methods=['GET'])
@login_required
def get_chat_history():
    if not db: return jsonify({'error': 'Database unavailable.'}), 500
    try:
        chat_ref = db.collection('chats').document(current_user.id)
        chat_doc = chat_ref.get()
        return jsonify(chat_doc.to_dict().get('history', []) if chat_doc.exists else []), 200
    except Exception as e:
        print(f"Error fetching chat history: {e}")
        return jsonify({'error': 'Could not retrieve chat history.'}), 500

@app.route('/api/clear_chat_history', methods=['POST'])
@login_required
@csrf.exempt
def clear_chat_history():
    if not db: return jsonify({'error': 'Database service is not available.'}), 503
    try:
        db.collection('chats').document(current_user.id).delete()
        print(f"Chat history cleared for user {current_user.id}.")
        return jsonify({'message': 'Chat history cleared successfully.'}), 200
    except Exception as e:
        print(f"Error clearing chat history for user {current_user.id}: {e}")
        return jsonify({'error': 'An internal error occurred while clearing chat history.'}), 500

@app.route('/api/user_data', methods=['GET'])
@login_required
def get_user_data():
    if not current_user.is_authenticated: return jsonify({'error': 'User not authenticated'}), 401
    return jsonify({
        'user_id': current_user.id,
        'username': current_user.username,
        'display_name': current_user.display_name,
        'preferred_assistant': current_user.preferred_assistant
    }), 200

def text_to_ssml_with_pauses(text):
    pause_time = "500ms"
    ssml_text = text.replace('.', f'.<break time="{pause_time}"/>').replace('?', f'?<break time="{pause_time}"/>').replace('!', f'!<break time="{pause_time}"/>')
    return f"<speak>{ssml_text}</speak>"

@app.route('/api/chat', methods=['POST'])
@login_required
@csrf.exempt
def chat_api():
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid request format.'}), 400
    user_message = bleach.clean(data.get('message', ''))
    if not user_message: return jsonify({'error': 'No message provided'}), 400
    lower_message = user_message.lower()
    if any(keyword in lower_message for keyword in CRISIS_KEYWORDS):
        print(f"CRISIS DETECTED for user {current_user.id}. Intercepting AI call.")
        return jsonify({
            'crisis_alert': True,
            'ai_response': 'It sounds like you are going through a very difficult time...',
            'support_contacts': {
                'samaritans_title': 'Samaritans (Free, 24/7)', 'samaritans_phone': '116 123',
                'nhs_title': 'NHS Urgent Mental Health Helpline', 'nhs_phone': '111',
                'emergency_title': 'Emergency Services', 'emergency_phone': '999 or 112'
            },
            'audio_clips': []
        }), 200
    if not db: return jsonify({'error': 'Database unavailable.'}), 500
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key: return jsonify({'error': 'Gemini API key not configured.'}), 500

    try:
        chat_ref = db.collection('chats').document(current_user.id)
        chat_doc = chat_ref.get()
        history = chat_doc.to_dict().get('history', []) if chat_doc.exists else []
        history = history[-20:]
        history.append({"role": "user", "parts": [{"text": user_message}]})

        user_doc = db.collection('users').document(current_user.id).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
        assessment_context = "The user has completed their foundation assessment...\n"
        if user_data.get('assessment'):
            assessment = user_data['assessment']
            assessment_context += f"- Main difficulties: {assessment.get('primary_issues', 'N/A')}\n"
            assessment_context += f"- Impact on daily life: {assessment.get('daily_impact', 'N/A')}\n"
            assessment_context += f"- Goals for therapy: {assessment.get('therapy_goals', 'N/A')}\n"
        else:
            assessment_context = "The user has not yet completed their foundation assessment."

        diary_context = "Here is some background context from the user's recent diary entries:\n"
        try:
            seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            entries_ref = db.collection('users').document(current_user.id).collection('diary_entries').where('date', '>=', seven_days_ago).stream()
            diary_entries_text = [f"On {e.to_dict().get('date')}, they wrote: '{e.to_dict().get('text')}'" for e in entries_ref]
            diary_context += "\n".join(diary_entries_text) if diary_entries_text else "The user has no recent diary entries."
        except Exception as e:
            print(f"Could not fetch diary for context: {e}")
            diary_context = "Could not retrieve diary entries."

        preferred_assistant = current_user.preferred_assistant
        display_name = current_user.display_name or current_user.username
        persona_template = (
            "--- User's Background Information ---\n"
            "{assessment_context}\n\n{diary_context}\n\n"
            "--- Your Instructions ---\n"
            "You are {assistant_name}, a {assistant_type} CBT companion for {display_name}. "
            "Your tone is {tone}. Refer to their goals/difficulties when relevant. "
            "IMPORTANT: Use short paragraphs separated by double newlines (\\n\\n). No markdown."
        )
        if preferred_assistant == 'Clara':
            system_instruction = persona_template.format(assessment_context=assessment_context, diary_context=diary_context, assistant_name='Clara', assistant_type='compassionate', display_name=display_name, tone='warm')
        else:
            system_instruction = persona_template.format(assessment_context=assessment_context, diary_context=diary_context, assistant_name='Alex', assistant_type='action-oriented', display_name=display_name, tone='practical')

        gemini_payload = {
            "contents": history,
            "system_instruction": {"role": "model", "parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500}
        }
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={gemini_api_key}"
        gemini_response = requests.post(gemini_url, json=gemini_payload)
        gemini_response.raise_for_status()
        gemini_result = gemini_response.json()
        ai_response_text = gemini_result['candidates'][0]['content']['parts'][0]['text'] if gemini_result.get('candidates') else "I had trouble understanding that."
        history.append({"role": "model", "parts": [{"text": ai_response_text}]})
        executor.submit(chat_ref.set, {'history': history})

        audio_clips = []
        if tts_client:
            paragraphs = [p.strip() for p in ai_response_text.split('\n\n') if p.strip()]
            for paragraph in paragraphs:
                ssml_input_text = text_to_ssml_with_pauses(paragraph)
                synthesis_input = texttospeech.SynthesisInput(ssml=ssml_input_text)
                voice_gender = texttospeech.SsmlVoiceGender.FEMALE if preferred_assistant == 'Clara' else texttospeech.SsmlVoiceGender.MALE
                voice = texttospeech.VoiceSelectionParams(language_code="en-GB", ssml_gender=voice_gender)
                audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=0.9)
                tts_response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
                audio_base64 = base64.b64encode(tts_response.audio_content).decode('utf-8')
                audio_clips.append(audio_base64)

        return jsonify({'ai_response': ai_response_text, 'audio_clips': audio_clips}), 200
    except Exception as e:
        print(f"Error in chat_api: {e}")
        return jsonify({'error': 'An unexpected error occurred with the AI assistant.'}), 500


# --- SCRIPT EXECUTION BLOCK ---
def open_browser():
    webbrowser.open_new('http://127.0.0.1:5001')

if __name__ == '__main__':
    Timer(1, open_browser).start()
    app.run(debug=True, port=5001, use_reloader=False)
