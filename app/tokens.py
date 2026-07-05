import redis

#  Redis client + key 
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
TOKEN_KEY = "live_token"
RELOAD_TIME = 5

def set_current_token(token):
    redis_client.set(TOKEN_KEY, token)

def get_current_token():
    return redis_client.get(TOKEN_KEY)

def validate_scan(token, student, session):
    live_token = get_current_token()
    if live_token is None or token != live_token:
        return False, "Invalid token"
    record = f"scan:{session}:{token}:{student}"
    claimed = redis_client.set(record, "1", nx=True, ex=RELOAD_TIME)
    if not claimed:
        return False, "Already scanned"
    # TODO: persist attendance to Postgres / DB
    return True, "Scan successful"