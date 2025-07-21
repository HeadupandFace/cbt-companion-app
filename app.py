import os
from functools import wraps

# --- Third-party Imports ---
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, auth, firestore
import google.generativeai as genai

# --- App Initialization ---

app = Flask(__name__)

# RECOMMENDATION: Use environment variables for configuration to keep secrets out of code.
# The secret key is crucial for security in some Flask extensions, though not used directly here.
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-for-prod')

# RECOMMENDATION: Restrict CORS origins in production for better security.
# For development, "*" is okay, but for production, you should list your frontend's domain.
# e.g., origins=["https://your-cbt-champion-app.com"]
CORS(app, supports_credentials=True, origins=os.environ.get("CORS_ORIGINS", "*").split(','))

# --- Firebase & AI Initialization ---

db = None
model = None

try:
    # RECOMMENDATION: Prioritize Google's standard environment variable for credentials.
    # This is the standard for Cloud Run, GKE, and other Google Cloud services.
    # The local 'credentials.json' file is now a fallback for local development.
    cred_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
    if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
        print("Initializing Firebase with GOOGLE_APPLICATION_CREDENTIALS.")
        firebase_admin.initialize_app()
    elif os.path.exists(cred_path):
        print(f"Initializing Firebase with local credentials file: {cred_path}")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        raise FileNotFoundError("Could not find 'credentials.json' or GOOGLE_APPLICATION_CREDENTIALS.")

    db = firestore.client()
    print("Firebase Admin SDK initialized successfully.")

except Exception as e:
    print(f"FATAL: Could not initialize Firebase Admin SDK: {e}")

try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if GOOGLE_API_KEY:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-pro")
        print("Google Generative AI configured successfully.")
    else:
        print("WARNING: GOOGLE_API_KEY environment variable not found. The /api/chat endpoint will be disabled.")
except Exception as e:
    print(f"ERROR: Could not configure Google Generative AI: {e}")


# --- Authentication Decorator ---

def token_required(f):
    """
    A decorator to protect routes by verifying the Firebase ID token.
    The token should be passed in the 'Authorization' header as 'Bearer <token>'.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Authorization header is missing or invalid."}), 401
        
        token = auth_header.split('Bearer ')[1]

        try:
            decoded_token = auth.verify_id_token(token)
            # Use Flask's 'g' object to store the verified user info for this request.
            g.user = decoded_token
        except auth.ExpiredIdTokenError:
            return jsonify({"error": "Authentication token has expired. Please log in again."}), 401
        except auth.InvalidIdTokenError as e:
            # RECOMMENDATION: Log the specific error for easier debugging.
            print(f"Invalid token for user: {g.get('user', {}).get('uid', 'unknown')}. Error: {e}")
            return jsonify({"error": "Invalid authentication token."}), 401
        except Exception as e:
            print(f"Unexpected error verifying token: {e}")
            return jsonify({"error": "Could not verify authentication token."}), 500

        return f(*args, **kwargs)
    return decorated_function


# --- API Endpoints ---

@app.route("/api/register", methods=["POST"])
@token_required
def register_user():
    """Creates a user profile in Firestore after client-side signup."""
    if not db: return jsonify({"error": "Database not available."}), 503
        
    uid = g.user['uid']
    try:
        data = request.get_json()
        if not data or 'username' not in data:
            return jsonify({"error": "Username is required in request body."}), 400

        user_doc_ref = db.collection("users").document(uid)
        
        # Check if user profile already exists
        if user_doc_ref.get().exists:
            return jsonify({"message": "User profile already exists."}), 200

        user_doc_ref.set({
            "username": data.get("username"),
            "email": g.user.get('email'),
            # RECOMMENDATION: Added this field from your original app.py.
            # The frontend would need to be updated to send this.
            "preferred_assistant": data.get("preferred_assistant", "General"),
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "User profile created successfully."}), 201
    except Exception as e:
        print(f"Error in /api/register for UID {uid}: {e}")
        return jsonify({"error": "An error occurred during registration."}), 500

@app.route("/api/diary", methods=["POST"])
@token_required
def save_diary_entry():
    """Saves a new diary entry for the authenticated user."""
    if not db: return jsonify({"error": "Database not available."}), 503
    
    uid = g.user['uid']
    data = request.get_json()
    entry_text = data.get("entry")
    if not entry_text:
        return jsonify({"error": "Diary entry text cannot be empty."}), 400

    try:
        entry_ref = db.collection("users").document(uid).collection("diaryEntries").document()
        entry_ref.set({
            "text": entry_text,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "Diary entry saved.", "id": entry_ref.id}), 201
    except Exception as e:
        print(f"Error in POST /api/diary for UID {uid}: {e}")
        return jsonify({"error": "Failed to save diary entry."}), 500

@app.route("/api/diary", methods=["GET"])
@token_required
def get_diary_entries():
    """Retrieves all diary entries for the authenticated user."""
    if not db: return jsonify({"error": "Database not available."}), 503
    
    uid = g.user['uid']
    try:
        # RECOMMENDATION: Limit the query to prevent fetching excessive data.
        query = db.collection("users").document(uid).collection("diaryEntries").order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        ).limit(50)
        
        entries = []
        for entry in query.stream():
            entry_data = entry.to_dict()
            entry_data['id'] = entry.id
            # Convert timestamp to a standardized string (ISO 8601)
            if 'createdAt' in entry_data and hasattr(entry_data['createdAt'], 'isoformat'):
                entry_data['createdAt'] = entry_data['createdAt'].isoformat()
            entries.append(entry_data)
            
        return jsonify(entries), 200
    except Exception as e:
        print(f"Error in GET /api/diary for UID {uid}: {e}")
        return jsonify({"error": "Failed to retrieve diary entries."}), 500

@app.route("/api/chat", methods=["POST"])
@token_required
def chat():
    """
    Handles chat requests to the Generative AI model, now with user context.
    """
    if not model: return jsonify({"error": "AI Model not configured."}), 503
    if not db: return jsonify({"error": "Database not available."}), 503

    uid = g.user['uid']
    data = request.get_json()
    user_prompt = data.get("prompt")
    if not user_prompt:
        return jsonify({"error": "Prompt is required."}), 400

    try:
        # --- RECOMMENDATION: Add context to the AI prompt ---
        # 1. Fetch recent diary entries to understand the user's state.
        diary_query = db.collection("users").document(uid).collection("diaryEntries").order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        ).limit(3)
        
        recent_entries = [f"- {doc.to_dict().get('text')}" for doc in diary_query.stream()]
        diary_context = "\n".join(recent_entries) if recent_entries else "No recent diary entries."

        # 2. Construct a system prompt that guides the AI.
        system_prompt = f"""
        You are 'CBT Champion', a supportive and empathetic AI assistant based on Cognitive Behavioral Therapy principles.
        Your goal is to help the user identify and challenge their negative thought patterns.
        Do not give medical advice. Be kind, encouraging, and guide them with questions.

        Here is some recent context from the user's thought diary:
        {diary_context}

        Now, respond to the user's latest message.
        """
        
        full_prompt = f"{system_prompt}\n\nUser: {user_prompt}\nAI:"
        
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        print(f"Error in /api/chat for UID {uid}: {e}")
        return jsonify({"error": "An error occurred with the AI service."}), 500

@app.route("/health")
def health_check():
    """A simple health check endpoint to verify the service is running."""
    return jsonify({"status": "ok", "database_status": "ok" if db else "unavailable"}), 200

if __name__ == "__main__":
    # RECOMMENDATION: Use an environment variable for the port, common for deployment platforms.
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get("FLASK_DEBUG", "False").lower() == "true")
