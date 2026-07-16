import redis
import os

host = os.environ.get("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=host, port=6379, decode_responses=True)

RELOAD_TIME = 5
ACTIVE_SESSIONS_KEY = "active_sessions"

def token_key(session_id):
    return f"session:{session_id}:live_token"

def present_key(session_id):
    return f"session:{session_id}:present"

def set_current_token(session_id, token):
    redis_client.set(token_key(session_id), token, ex=RELOAD_TIME + 2)

def get_current_token(session_id):
    return redis_client.get(token_key(session_id))

def mark_session_active(session_id):
    redis_client.sadd(ACTIVE_SESSIONS_KEY, session_id)

def mark_session_inactive(session_id):
    redis_client.srem(ACTIVE_SESSIONS_KEY, session_id)
    redis_client.delete(token_key(session_id), present_key(session_id))

def get_active_sessions():
    return redis_client.smembers(ACTIVE_SESSIONS_KEY)

def validate_scan(session_id, token, student):
    live_token = get_current_token(session_id)
    if live_token is None or token != live_token:
        return False, "Invalid token"
    # return 0 by SADD if the student already exists
    added = redis_client.sadd(present_key(session_id), student)
    if not added:
        return False, "Already scanned"
    # TODO: persist attendance to Postgres
    return True, "Scan successful"