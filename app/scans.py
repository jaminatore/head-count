from app.tokens import RELOAD_TIME, get_current_token
from app.redis_client import redis_client

def validate_scan(token, student, session):
    live_token = get_current_token()
    if live_token is None or token != live_token:
        return False, "Invalid token"
    record = f"scan:{session}:{token}:{student}"
    # if the token rotates and expires, the student will be able to scan again and create duplicate attendance records
    claimed = redis_client.set(record, "1", nx=True, ex=RELOAD_TIME)
    if not claimed:
        return False, "Already scanned"
    # TODO: persist attendance to Postgres / DB
    return True, "Scan successful"