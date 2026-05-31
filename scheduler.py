from apscheduler.schedulers.background import BackgroundScheduler
from bot_service import process_user_comments
from firebase_config import get_db

def job_runner():
    """Fetches all users and runs the bot for each."""
    db = get_db()
    if not db:
        return
    
    print("Running scheduled job to check comments for all users...")
    users = db.collection('instagram_configs').stream()
    for user_doc in users:
        uid = user_doc.id
        try:
            process_user_comments(uid)
        except Exception as e:
            print(f"Error processing user {uid}: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run every 60 seconds (adjust as needed for production limits)
    scheduler.add_job(func=job_runner, trigger="interval", seconds=60)
    scheduler.start()
    print("Scheduler started. Running every 60 seconds.")
