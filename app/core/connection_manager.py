import asyncio
import json
from typing import Set, Dict, Any
from fastapi import WebSocket
from concurrent.futures import ThreadPoolExecutor
from app.core.config import logger

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.loop = asyncio.get_event_loop()
        self.executor = ThreadPoolExecutor(max_workers=4)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("✅ New WebSocket connection")

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:    
            self.active_connections.remove(websocket)
            logger.info("🔌 WebSocket disconnected")

    async def broadcast(self, message: Dict[str, Any]):
        if not self.active_connections:
            return
        data = json.dumps(message)
        await asyncio.gather(
            *(conn.send_text(data) for conn in self.active_connections.copy()),
            return_exceptions=True
        )

manager = ConnectionManager()
