from app.redis_client import redis_client

TOKEN_KEY = "live_token"
RELOAD_TIME = 5

def set_current_token(token):
    redis_client.set(TOKEN_KEY, token)

def get_current_token():
    return redis_client.get(TOKEN_KEY)