import os
import redis

host = os.environ.get("REDIS_HOST", "localhost")
port = int(os.environ.get("REDIS_PORT", 6379))
redis_client = redis.Redis(host=host, port=port, decode_responses=True)