from app.redis_client import redis_client

RELOAD_TIME = 5 # This is a global time
TICK_INTERVAL = 0.5
ACTIVE_SESSIONS_KEY = "active_sessions"  


# --- Session-scoped token/present keys -------------------------------------

def token_key(session_id):
    return f"session:{session_id}:live_token"

def present_key(session_id):
    return f"session:{session_id}:present"

def set_current_token(session_id, token, reload_time_s=None):
    if reload_time_s is None:
        reload_time_s = get_reload_time(session_id)
    redis_client.set(token_key(session_id), token, ex=reload_time_s + 2)

def get_current_token(session_id):
    return redis_client.get(token_key(session_id))


# --- Active session membership + due-time scheduling ------------------------

def mark_session_active(session_id, next_due):
    redis_client.zadd(ACTIVE_SESSIONS_KEY, {session_id: next_due})

def mark_session_inactive(session_id):
    redis_client.zrem(ACTIVE_SESSIONS_KEY, session_id)
    redis_client.delete(token_key(session_id), present_key(session_id), reload_time_key(session_id))

def get_active_sessions():
    return redis_client.zrange(ACTIVE_SESSIONS_KEY, 0, -1)

def is_session_active(session_id):
    return redis_client.zscore(ACTIVE_SESSIONS_KEY, session_id) is not None

def get_due_sessions(now):
    return redis_client.zrangebyscore(ACTIVE_SESSIONS_KEY, 0, now)

def set_next_due(session_id, when):
    redis_client.zadd(ACTIVE_SESSIONS_KEY, {session_id: when})


# --- Per-session reload time (cached from Postgres) -------------------------

def reload_time_key(session_id):
    return f"session:{session_id}:reload_time"

def set_reload_time(session_id, reload_time_s):
    redis_client.set(reload_time_key(session_id), reload_time_s)

def get_reload_time(session_id):
    val = redis_client.get(reload_time_key(session_id))
    return int(val) if val is not None else RELOAD_TIME


# --- Per-session rotation lock ----------------------------------------------

ACQUIRE_LUA = """
local cur = redis.call('GET', KEYS[1])
if cur == false or cur == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return 1
end
return 0
"""
_acquire_script = redis_client.register_script(ACQUIRE_LUA)

def lock_key(session_id):
    return f"lock:{session_id}"

def try_acquire_session_lock(session_id, instance_id, reload_time_s):
    ttl_ms = int((reload_time_s + 2) * 1000)
    return _acquire_script(keys=[lock_key(session_id)], args=[instance_id, ttl_ms])