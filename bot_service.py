import requests
import time
from firebase_config import get_db
from firebase_admin import firestore


def get_recent_posts(user_id, access_token, max_posts=5):
    """Fetch recent Instagram posts."""
    url = f"https://graph.facebook.com/v21.0/{user_id}/media"
    params = {
        "fields": "id,caption,media_type,timestamp,permalink",
        "limit": max_posts,
        "access_token": access_token
    }
    response = requests.get(url, params=params)
    data = response.json()
    if "error" in data:
        print(f"Error fetching posts: {data['error']['message']}")
        return []
    return data.get("data", [])

def get_comments(media_id, access_token):
    """Fetch all comments on a specific post."""
    url = f"https://graph.facebook.com/v21.0/{media_id}/comments"
    params = {
        "fields": "id,text,username,timestamp,replies{id,text,username}",
        "access_token": access_token
    }
    response = requests.get(url, params=params)
    data = response.json()
    if "error" in data:
        print(f"Error fetching comments: {data['error']['message']}")
        return []
    return data.get("data", [])

def reply_to_comment(comment_id, reply_text, access_token):
    """Post a reply to a comment."""
    url = f"https://graph.facebook.com/v21.0/{comment_id}/replies"
    data = {
        "message": reply_text,
        "access_token": access_token
    }
    response = requests.post(url, data=data)
    result = response.json()
    return "error" not in result

def send_dm(comment_id, message_text, access_token):
    """Send a private DM reply to a comment."""
    url = f"https://graph.facebook.com/v21.0/me/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message_text},
        "access_token": access_token
    }
    response = requests.post(url, json=payload)
    result = response.json()
    return "error" not in result

def hide_comment(comment_id, access_token):
    """Hide a spam comment."""
    url = f"https://graph.facebook.com/v21.0/{comment_id}"
    data = {
        "hide": "true",
        "access_token": access_token
    }
    response = requests.post(url, data=data)
    result = response.json()
    return "error" not in result

def is_spam(comment_text, spam_keywords):
    """Check if a comment is spam."""
    text_lower = comment_text.lower()
    for word in spam_keywords:
        if word.lower() in text_lower:
            return True
    return False

def get_auto_reply(comment_text, auto_reply_rules):
    """Find matching auto-reply for a comment."""
    text_lower = comment_text.lower()
    for rule in auto_reply_rules:
        if rule['keyword'].lower() in text_lower:
            return rule
    return None

from flow_engine import evaluate_flow

def process_user_comments(uid):
    """Process comments for a single user."""
    db = get_db()
    if not db:
        print("Firebase not configured.")
        return

    # 1. Get user config
    config_ref = db.collection('instagram_configs').document(uid).get()
    if not config_ref.exists:
        return
    config = config_ref.to_dict()
    access_token = config.get('access_token')
    insta_user_id = config.get('instagram_user_id')
    if not access_token or not insta_user_id:
        return

    # 2. Get Flows and Spam Keywords
    flow_doc = db.collection('flows').document(uid).get()
    flow_data = flow_doc.to_dict() if flow_doc.exists else None

    spam_docs = db.collection('spam_keywords').where('uid', '==', uid).stream()
    spam_keywords = [doc.to_dict().get('word') for doc in spam_docs]

    # 3. Get User Stats and Conversation States
    stats_ref = db.collection('users').document(uid)
    stats_doc = stats_ref.get()
    replied_ids = stats_doc.to_dict().get('replied_comments', []) if stats_doc.exists else []
    
    conv_states_ref = db.collection('conversation_states').document(uid)
    conv_states_doc = conv_states_ref.get()
    user_states = conv_states_doc.to_dict() if conv_states_doc.exists else {}
    states_updated = False
    
    total_processed = 0
    spam_hidden = 0
    replies_sent = 0

    posts = get_recent_posts(insta_user_id, access_token)
    for post in posts:
        media_id = post["id"]
        comments = get_comments(media_id, access_token)
        for comment in comments:
            comment_id = comment["id"]
            if comment_id in replied_ids:
                continue

            comment_text = comment.get("text", "")
            username = comment.get("username", "unknown")
            print(f"[{uid}] Processing comment: {comment_text}")

            if is_spam(comment_text, spam_keywords):
                if hide_comment(comment_id, access_token):
                    spam_hidden += 1
                replied_ids.append(comment_id)
                continue
            
            # Use Flow Engine
            current_state_node_id = user_states.get(username)
            reply_text, next_state_node_id = evaluate_flow(flow_data, comment_text, current_state_node_id)
            
            if reply_text:
                if reply_to_comment(comment_id, reply_text, access_token):
                    replies_sent += 1
                
                dm_text = f"Hi @{username}, {reply_text}"
                send_dm(comment_id, dm_text, access_token)
                
                if next_state_node_id:
                    user_states[username] = next_state_node_id
                    states_updated = True
                elif current_state_node_id:
                    # Flow finished, remove state
                    del user_states[username]
                    states_updated = True

            replied_ids.append(comment_id)
            total_processed += 1

    # Update stats
    if total_processed > 0 or spam_hidden > 0 or replies_sent > 0:
        stats_ref.set({
            'replied_comments': replied_ids,
            'total_processed': firestore.Increment(total_processed),
            'spam_hidden': firestore.Increment(spam_hidden),
            'replies_sent': firestore.Increment(replies_sent)
        }, merge=True)
        
    if states_updated:
        conv_states_ref.set(user_states)
