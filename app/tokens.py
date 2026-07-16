from app.redis_client import redis_client

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
