from uagents import Context, Model
from uagents_core.types import DeliveryStatus, MsgStatus


async def send_with_debug(
    ctx: Context,
    sender_name: str,
    recipient: str,
    message: Model,
) -> MsgStatus:
    """Send a message and make uAgents' non-raising delivery status visible."""
    message_type = type(message).__name__
    incident_id = getattr(message, "incident_id", None)

    ctx.logger.info(
        "Send started sender=%s recipient=%s message_type=%s incident_id=%s",
        sender_name,
        recipient,
        message_type,
        incident_id,
    )
    status = await ctx.send(recipient, message)

    log = (
        ctx.logger.info
        if status.status == DeliveryStatus.DELIVERED
        else ctx.logger.error
    )
    log(
        "Send finished sender=%s recipient=%s message_type=%s incident_id=%s "
        "status=%s detail=%s endpoint=%s",
        sender_name,
        recipient,
        message_type,
        incident_id,
        status.status,
        status.detail,
        status.endpoint,
    )
    return status
