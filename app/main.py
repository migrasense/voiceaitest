from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # ✅ Add this import
from contextlib import asynccontextmanager
import os

# Absolute imports so it works in both pytest + uvicorn
from app.routers import websocket_routes, mock_routes, twilio_routes


# Lifespan handler replaces deprecated @app.on_event
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting up FastAPI server")
    
    # ✅ Create static directory if it doesn't exist
    static_dir = "app/static"
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
        print(f"📁 Created static directory: {static_dir}")
    
    yield
    print("🛑 Shutting down FastAPI server")


# Create app with lifespan
app = FastAPI(lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    # allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite dev server
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Add static file serving - THIS IS THE KEY LINE!
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(websocket_routes.router)
app.include_router(mock_routes.router)
app.include_router(twilio_routes.router)

# app.include_router(owner_routes.router)