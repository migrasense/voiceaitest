from datetime import datetime
from typing import Optional, Set, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import uuid
from app.core.config import logger

# app/core/conversation_manager.py

class ConversationManager:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.active_session_id: Optional[str] = None

    def start_session(self, caller_id: str = "unknown") -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "caller_id": caller_id,
            "messages": [],
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "overall_sentiment": None  # ✅ new
        }
        self.active_session_id = session_id
        return session_id

    def add_message(self, session_id: str, message: dict):
        if session_id not in self.sessions:
            session_id = self.start_session()

        # ✅ Add message
        self.sessions[session_id]["messages"].append(message)

        # ✅ Update overall sentiment trend
        sentiments = [m.get("sentiment") for m in self.sessions[session_id]["messages"] if m.get("sentiment")]
        if sentiments:
            # Simple scoring: positive=1, neutral=0, negative=-1
            score_map = {"positive": 1, "neutral": 0, "negative": -1}
            avg_score = sum(score_map[s] for s in sentiments if s in score_map) / len(sentiments)
            if avg_score > 0.2:
                self.sessions[session_id]["overall_sentiment"] = "positive"
            elif avg_score < -0.2:
                self.sessions[session_id]["overall_sentiment"] = "negative"
            else:
                self.sessions[session_id]["overall_sentiment"] = "neutral"
