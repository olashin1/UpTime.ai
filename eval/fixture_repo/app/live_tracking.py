from fastapi import APIRouter, WebSocket

from app.events import subscribe

router = APIRouter()


@router.websocket("/ws/orders/{order_id}")
async def order_updates(ws: WebSocket, order_id: int):
    await ws.accept()
    async for update in subscribe(order_id):
        # Raises ConnectionClosed when the customer closes the tab; nothing to clean up.
        await ws.send_json(update)
