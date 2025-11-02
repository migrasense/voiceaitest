#!/usr/bin/env python3
"""Test WebSocket through ngrok"""
import asyncio
import json

try:
    import websockets
    
    async def test():
        # Replace with your ngrok URL
        uri = "wss://mirkily-recordable-maranda.ngrok-free.dev/audio/test"
        print(f"🔌 Testing WebSocket through ngrok: {uri}")
        print("⏳ This will tell us if ngrok blocks WebSocket upgrades...")
        try:
            async with websockets.connect(uri) as ws:
                print("✅ SUCCESS! ngrok is forwarding WebSocket connections!")
                await ws.send(json.dumps({"test": "hello from ngrok"}))
                print("📤 Sent test message")
                response = await ws.recv()
                print(f"📥 Received: {response[:200]}")
        except Exception as e:
            print(f"❌ FAILED: {e}")
            print("\n💡 This confirms ngrok free tier is blocking WebSocket upgrades")
            print("💡 This is why Twilio can't connect")
    
    asyncio.run(test())
except ImportError:
    print("⚠️ websockets not installed. Run: pip install websockets")
except Exception as e:
    print(f"❌ Error: {e}")

