from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import firebase_admin
from firebase_admin import auth
from firebase_config import get_db
from scheduler import start_scheduler
import requests as http_requests
import os

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173"])

# Start the background job
start_scheduler()

# ─── Instagram OAuth Config ──────────────────────────────────────────────────
# Fill these in from your Meta App Dashboard
APP_ID     = os.environ.get("INSTAGRAM_APP_ID",     "2188104798634426")
APP_SECRET = os.environ.get("INSTAGRAM_APP_SECRET", "8e62daf99dc4daf96bedb7ddb31a5119")
REDIRECT_URI = os.environ.get("REDIRECT_URI",       "http://localhost:5000/auth/instagram/callback")
FRONTEND_URL = os.environ.get("FRONTEND_URL",       "http://localhost:5173")
# ─────────────────────────────────────────────────────────────────────────────

def verify_token(req):
    auth_header = req.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split('Bearer ')[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token['uid']
    except Exception as e:
        print(f"Token verification failed: {e}")
        return None


# ─── Base Routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({
        "status": "active",
        "service": "InstaBot SaaS Backend API",
        "meta_app_id": APP_ID
    })

# ─── OAuth Routes ─────────────────────────────────────────────────────────────

@app.route('/auth/instagram')
def instagram_oauth_start():
    """
    Step 1: Frontend sends the user's Firebase UID as ?uid=...
    We build the Facebook OAuth URL and redirect the user there.
    """
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "Missing uid"}), 400

    # We encode the uid into the `state` param so we can retrieve it in the callback
    oauth_url = (
        f"https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=instagram_basic,instagram_manage_comments,instagram_manage_messages,pages_show_list"
        f"&state={uid}"
        f"&response_type=code"
    )
    return redirect(oauth_url)


@app.route('/auth/instagram/callback')
def instagram_oauth_callback():
    """
    Step 2: Facebook redirects here with ?code=...&state=uid
    We exchange the code for a short-lived token, upgrade to long-lived,
    fetch the user's Instagram User ID, and save everything to Firestore.
    """
    code = request.args.get('code')
    uid  = request.args.get('state')   # The Firebase UID we passed as state

    if not code or not uid:
        return redirect(f"{FRONTEND_URL}/app/settings?error=oauth_failed")

    # 1. Exchange code → short-lived access token
    token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
    token_resp = http_requests.get(token_url, params={
        "client_id":     APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "code":          code,
    })
    token_data = token_resp.json()
    short_token = token_data.get("access_token")

    if not short_token:
        return redirect(f"{FRONTEND_URL}/app/settings?error=token_exchange_failed")

    # 2. Upgrade to long-lived token (valid for 60 days)
    long_token_resp = http_requests.get("https://graph.facebook.com/v21.0/oauth/access_token", params={
        "grant_type":        "fb_exchange_token",
        "client_id":         APP_ID,
        "client_secret":     APP_SECRET,
        "fb_exchange_token": short_token,
    })
    long_token_data = long_token_resp.json()
    long_token = long_token_data.get("access_token")

    if not long_token:
        long_token = short_token   # fallback

    # 3. Get the Facebook Pages linked to this account
    pages_resp = http_requests.get("https://graph.facebook.com/v21.0/me/accounts", params={
        "access_token": long_token
    })
    pages = pages_resp.json().get("data", [])

    # 4. For each page, find the connected Instagram Business Account
    instagram_user_id = None
    page_access_token = long_token

    for page in pages:
        page_id    = page.get("id")
        page_token = page.get("access_token")
        ig_resp = http_requests.get(
            f"https://graph.facebook.com/v21.0/{page_id}",
            params={"fields": "instagram_business_account", "access_token": page_token}
        )
        ig_data = ig_resp.json()
        iba = ig_data.get("instagram_business_account")
        if iba:
            instagram_user_id = iba.get("id")
            page_access_token = page_token
            break

    if not instagram_user_id:
        return redirect(f"{FRONTEND_URL}/app/settings?error=no_instagram_account")

    # 5. Save to Firestore under the user's uid
    db = get_db()
    if db:
        db.collection('instagram_configs').document(uid).set({
            "access_token":      page_access_token,
            "instagram_user_id": instagram_user_id,
            "connected":         True,
        }, merge=True)

    return redirect(f"{FRONTEND_URL}/app/settings?success=connected")


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
def get_stats():
    uid = verify_token(request)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    doc = db.collection('users').document(uid).get()
    if doc.exists:
        data = doc.to_dict()
        return jsonify({
            "total_processed": data.get('total_processed', 0),
            "spam_hidden":     data.get('spam_hidden', 0),
            "replies_sent":    data.get('replies_sent', 0),
        })
    return jsonify({"total_processed": 0, "spam_hidden": 0, "replies_sent": 0})


@app.route('/api/config', methods=['GET'])
def get_config():
    uid = verify_token(request)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    doc = db.collection('instagram_configs').document(uid).get()
    if doc.exists:
        data = doc.to_dict()
        return jsonify({"connected": data.get("connected", False), "instagram_user_id": data.get("instagram_user_id", "")})
    return jsonify({"connected": False})


@app.route('/api/flows', methods=['GET', 'POST'])
def handle_flows():
    uid = verify_token(request)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    ref = db.collection('flows').document(uid)

    if request.method == 'GET':
        doc = ref.get()
        return jsonify(doc.to_dict() if doc.exists else {"nodes": [], "edges": []})

    elif request.method == 'POST':
        data = request.json
        ref.set(data)
        return jsonify({"success": True})


if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
