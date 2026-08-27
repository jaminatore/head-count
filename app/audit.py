import logging

from app.db import async_session
from app.models import AuditLog

logger = logging.getLogger(__name__)

async def write_audit(event_type, *, session_id=None, user_id=None, reason=None, instance_id=None):
    async with async_session() as audit_db:
        audit_db.add(AuditLog(
            event_type=event_type,
            session_id=session_id,
            user_id=user_id,
            reason=reason,
            instance_id=instance_id
        ))
        await audit_db.commit()

async def safe_audit(event_type, **kwargs):
    try:
        await write_audit(event_type, **kwargs)
    except Exception:
        logger.warning("Failed to write audit log", exc_info=True)