from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, CSRFError
import firebase_admin
from firebase_admin import credentials, auth, firestore
import google.generativeai as genai
import os

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-secret-key')
CORS(app)
csrf = CSRFProtect(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Initialize Firebase Admin
cred = credentials.Certificate("./credentials.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Configure Google Generative AI
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-pro")

# User class
class User(UserMixin):
    def __init__(self, uid, username, preferred_assistant):
        self.id = uid
        self.username = username
        self.preferred_assistant = preferred_assistant

@login_manager.user_loader
def load_user(user_id):
    user_ref = db.collection("users").document(user_id).get()
    if user_ref.exists:
        user_data = user_ref.to_dict()
        return User(user_id, user_data.get("username"), user_data.get("preferred_assistant"))
    return None

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["POST"])
@csrf.exempt
def register():
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Empty JSON.")
        id_token = data.get("idToken")
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token["uid"]
        username = data.get("username")
        preferred_assistant = data.get("preferred_assistant")

        db.collection("users").document(uid).set({
            "username": username,
            "preferred_assistant": preferred_assistant
        })
        return jsonify({"message": "User registered successfully."})
    except Exception as e:
        print(f"Error in /register: {e}, Raw: {request.data}")
        return jsonify({"error": "Registration failed."}), 400

@app.route("/login", methods=["POST"])
@csrf.exempt
def login():
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Empty JSON.")
        id_token = data.get("idToken")
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token["uid"]
        user_ref = db.collection("users").document(uid).get()

        if user_ref.exists:
            user_data = user_ref.to_dict()
            user = User(uid, user_data.get("username"), user_data.get("preferred_assistant"))
            login_user(user)
            return jsonify({"message": "Login successful."})
        else:
            return jsonify({"error": "User not found."}), 404
    except Exception as e:
        print(f"Error in /login: {e}, Raw: {request.data}")
        return jsonify({"error": "Login failed."}), 400

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/api/save_consent", methods=["POST"])
@csrf.exempt
def save_consent():
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Empty JSON.")
        uid = data.get("uid")
        consent = data.get("consent")
        db.collection("consents").document(uid).set({"consent": consent})
        return jsonify({"message": "Consent saved."})
    except Exception as e:
        print(f"Error in /api/save_consent: {e}, Raw: {request.data}")
        return jsonify({"error": "Failed to save consent."}), 400

@app.route("/api/chat", methods=["POST"])
@csrf.exempt
def chat():
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Empty JSON.")
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "Prompt is required."}), 400

        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        print(f"Error in /api/chat: {e}, Raw: {request.data}")
        return jsonify({"error": "AI response failed."}), 400

@app.route("/api/diary", methods=["POST"])
@csrf.exempt
def save_diary():
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Empty JSON.")
        uid = data.get("uid")
        entry = data.get("entry")
        db.collection("diary").add({"uid": uid, "entry": entry})
        return jsonify({"message": "Diary entry saved."})
    except Exception as e:
        print(f"Error in /api/diary: {e}, Raw: {request.data}")
        return jsonify({"error": "Failed to save diary entry."}), 400

if __name__ == "__main__":
    app.run(debug=True)
