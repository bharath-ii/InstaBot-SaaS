import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

# Initialize Firebase Admin SDK
cred_path = os.path.join(os.path.dirname(__file__), "firebase-adminsdk.json")

# Check if credentials exist (to prevent crashing before setup)
if os.path.exists(cred_path):
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase initialized successfully.")
else:
    db = None
    print("⚠️ Firebase credentials not found! Please add 'firebase-adminsdk.json' to the backend folder.")

def get_db():
    return db
