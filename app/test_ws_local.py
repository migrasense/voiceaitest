#!/usr/bin/env python3
"""Quick local WebSocket test"""
import asyncio
import json

try:
    import websockets
    
    async def test():
        uri = "ws://localhost:8000/audio/test"
        print(f"🔌 Testing WebSocket: {uri}")
        try:
            async with websockets.connect(uri) as ws:
                print("✅ Connected successfully!")
                await ws.send(json.dumps({"test": "hello"}))
                print("📤 Sent test message")
                response = await ws.recv()
                print(f"📥 Received: {response[:200]}")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
    
    asyncio.run(test())
except ImportError:
    print("⚠️ websockets not installed. Run: pip install websockets")

