# app/core/conversation_manager.py

import uuid
from datetime import datetime
from collections import Counter
from typing import Optional, Dict, Any, List
import re

from dotenv.main import logger

class ConversationManager:
    def __init__(self):
        # sessions: {session_id: {...}}
        # Each session keeps everything in memory until you explicitly flush.
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.active_session_id: Optional[str] = None  # last active session

    # -------- Session lifecycle --------

    def start_session(self, caller_id: str = "unknown") -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        self.sessions[session_id] = {
            "caller_id": caller_id,
            "messages": [],
            "start_time": now,
            "end_time": None,
            "status": "live",         # live | closed
            "analysis": None,         # cached analysis
            "last_activity": now,     # updated on add_message
            "conversation_context": {},  # slot-filling memory
            "slots": {               # lightweight slot-filling memory
                "care_needs": set(),
                "hours_per_week": None,
                "days": set(),
                "time_of_day": None
            }
        }
        self.active_session_id = session_id
        return session_id

    # def get_or_create_active_session(self, caller_id: str = "unknown") -> str:
    #     if not self.active_session_id or self.sessions.get(self.active_session_id, {}).get("end_time"):
    #         self.active_session_id = self.start_session(caller_id)
    #     return self.active_session_id

    def get_or_create_active_session(self, caller_id: str = "unknown", allow_new: bool = True) -> str:
        """
        Get active session, optionally allowing creation of new session.
        If allow_new=False and no active session exists, returns None.
        """
        if not self.active_session_id or self.sessions.get(self.active_session_id, {}).get("end_time"):
            if not allow_new:
                return None
            self.active_session_id = self.start_session(caller_id)
        return self.active_session_id

    def end_session(self, session_id: str):
        """Mark as ended (timestamp), but do NOT write to DB here."""
        if session_id in self.sessions:
            self.sessions[session_id]["end_time"] = datetime.now().isoformat()
            self.sessions[session_id]["status"] = "closed"
            # refresh analysis cache on close
            self.sessions[session_id]["analysis"] = self._analyze_session(self.sessions[session_id])
            if self.active_session_id == session_id:
                self.active_session_id = None

    def mark_closed(self, session_id: str, analysis: Optional[Dict[str, Any]] = None):
        """Explicitly close the session and set analysis if provided."""
        if session_id in self.sessions:
            self.sessions[session_id]["end_time"] = self.sessions[session_id]["end_time"] or datetime.now().isoformat()
            self.sessions[session_id]["status"] = "closed"
            if analysis:
                self.sessions[session_id]["analysis"] = analysis
            else:
                self.sessions[session_id]["analysis"] = self._analyze_session(self.sessions[session_id])
            if self.active_session_id == session_id:
                self.active_session_id = None

    # -------- Messages & analysis --------

    def add_message(self, session_id: str, message: dict):
        """Buffer a message in memory; no DB writes here."""
        if session_id not in self.sessions:
            session_id = self.start_session("unknown")  # create a new one if missing
        self.sessions[session_id]["messages"].append(message)
        self.sessions[session_id]["last_activity"] = datetime.now().isoformat()
        # optional: keep rolling analysis cached
        self.sessions[session_id]["analysis"] = self._analyze_session(self.sessions[session_id])

    def _analyze_session(self, session: dict) -> Dict[str, Any]:
        """Generate a comprehensive summary of one session."""
        messages = session.get("messages", [])
        if not messages:
            return {"summary": "No messages in this session."}

        # Collect intents and transcripts
        intents = [m.get("intent") for m in messages if m.get("intent")]
        transcripts = [m.get("transcript", "") for m in messages if m.get("transcript")]
        # ai_responses = [m.get("ai_response", "") for m in messages if m.get("ai_response")]
        
        # Determine main intent
        business_intents = {"inquiry", "medical", "caregiver_reschedule", "appointment", "emergency", "admin_handoff", "job_application_followup"}
        # generic_intents = {"confirmation", "gratitude", "polite_closure", "backchannel", "greeting", "other"}
        
        business_intent_list = [i for i in intents if i in business_intents]
        if business_intent_list:
            main_intent = Counter(business_intent_list).most_common(1)[0][0]
        else:
            main_intent = Counter(intents).most_common(1)[0][0] if intents else "unknown"

        # Build narrative summary
        narrative_parts = []
        
        # Opening
        if transcripts:
            narrative_parts.append(f"Caller initiated contact with: '{transcripts[0]}'")
        
        # Main content - what did they discuss?
        conversation_content = " ".join(transcripts).lower()
        
        if "mom" in conversation_content or "mother" in conversation_content:
            narrative_parts.append("Discussion about care for caller's mother.")
        elif "dad" in conversation_content or "father" in conversation_content:
            narrative_parts.append("Discussion about care for caller's father.")
        
        # What services/needs were mentioned?
        needs_mentioned = []
        if "companionship" in conversation_content or "company" in conversation_content:
            needs_mentioned.append("companionship")
        if "medication" in conversation_content:
            needs_mentioned.append("medication reminders")
        if "housekeeping" in conversation_content or "cleaning" in conversation_content:
            needs_mentioned.append("housekeeping")
        
        if needs_mentioned:
            narrative_parts.append(f"Specific needs discussed: {', '.join(needs_mentioned)}.")
        
        # Schedule details
        if any("hour" in t for t in transcripts) or any("schedule" in t for t in transcripts):
            narrative_parts.append("Caller provided schedule preferences.")
        
        # Contact info shared?
        full_text = " ".join(transcripts)
        if re.search(r'\d{3}[\s\-]?\d{3}[\s\-]?\d{4}', full_text):
            narrative_parts.append("Contact information was shared.")
        
        # How did it end?
        urgent_flag = any(bool(m.get("urgent")) for m in messages)
        ended_with_goodbye = any(i in {"goodbye", "polite_closure"} for i in intents)
        
        closed_by = "unknown"
        last_message = messages[-1] if messages else {}

        if urgent_flag:
            narrative_parts.append("URGENT matter flagged for immediate admin attention.")
        
        if ended_with_goodbye:
            # Check if it was a natural goodbye or admin handoff
            if last_message.get("intent") == "admin_handoff":
                closed_by = "admin_handoff"
            elif last_message.get("intent") == "polite_closure":
                closed_by = "ai_natural_closure"
            else:
                closed_by = "caller_initiated"
        elif urgent_flag:
            closed_by = "escalated_to_admin"
        else:
            closed_by = "incomplete"  # Conversation didn't have clear closure
        
        # Optional: Keep metrics in a separate nested object
        metrics = {
            "total_messages": len(messages),
            "intents_distribution": dict(Counter(intents)),
            "caller_message_count": len([m for m in messages if m.get("transcript")]),
            "ai_message_count": len([m for m in messages if m.get("ai_response")]),
        }
        
        narrative_summary = " ".join(narrative_parts)

        return {
            "summary": narrative_summary,
            "main_intent": main_intent,
            "urgent": urgent_flag,
            "priority": None,
            "ended_with_closure": ended_with_goodbye,
            "closed_by": closed_by,
            "metrics": metrics
        }

    # def _analyze_session(self, session: dict) -> Dict[str, Any]:
    #     """Generate a comprehensive summary of one session."""
    #     messages = session.get("messages", [])
    #     if not messages:
    #         return {"summary": "No messages in this session."}

    #     intents = [m.get("intent") for m in messages if m.get("intent")]
    #     urgencies = [bool(m.get("urgent")) for m in messages if "urgent" in m]
    #     transcripts = [m.get("transcript", "") for m in messages if m.get("transcript")]

    #     # Define intent categories
    #     generic_intents = {"confirmation", "gratitude", "polite_closure", "backchannel", "other"}
    #     business_intents = {"inquiry", "medical", "caregiver_reschedule", "appointment", "emergency"}
        
    #     # Separate business intents from generic ones
    #     business_intent_list = [i for i in intents if i in business_intents]
    #     generic_intent_list = [i for i in intents if i in generic_intents]
        
    #     # Determine main intent - prioritize business intents
    #     if business_intent_list:
    #         main_intent = Counter(business_intent_list).most_common(1)[0][0]
    #     elif generic_intent_list:
    #         # If only generic intents, pick the most meaningful one
    #         main_intent = Counter(generic_intent_list).most_common(1)[0][0]
    #     else:
    #         main_intent = "unknown"

    #     urgent_flag = any(urgencies)
    #     ended_with_goodbye = any(i in {"goodbye", "polite_closure"} for i in intents if i)
        
    #     # Create a more detailed summary
    #     caller_messages = [m for m in messages if m.get("transcript") and not m.get("ai_response")]
    #     ai_messages = [m for m in messages if m.get("ai_response")]
        
    #     # Analyze conversation content for better summary
    #     conversation_topics = []
    #     if any("office hours" in t.lower() or "hours" in t.lower() for t in transcripts):
    #         conversation_topics.append("office hours inquiry")
    #     if any("care" in t.lower() or "caregiver" in t.lower() for t in transcripts):
    #         conversation_topics.append("care services")
    #     if any("appointment" in t.lower() or "schedule" in t.lower() for t in transcripts):
    #         conversation_topics.append("scheduling")
    #     if any("emergency" in t.lower() or "urgent" in t.lower() for t in transcripts):
    #         conversation_topics.append("urgent matter")
        
    #     # Build comprehensive summary
    #     summary_parts = [f"Conversation with {len(messages)} total messages"]
        
    #     if conversation_topics:
    #         summary_parts.append(f"Topics discussed: {', '.join(conversation_topics)}")
        
    #     summary_parts.append(f"Primary intent: {main_intent}")
        
    #     if urgent_flag:
    #         summary_parts.append("Urgent matter identified")
        
    #     if ended_with_goodbye:
    #         summary_parts.append("Conversation properly concluded")
    #     else:
    #         summary_parts.append("Conversation may need follow-up")
            
    #     summary = ". ".join(summary_parts) + "."

    #     return {
    #         "summary": summary,
    #         "main_intent": main_intent,
    #         "urgent": urgent_flag,
    #         "total_messages": len(messages),
    #         "intents_distribution": dict(Counter(intents)),
    #         "ended_with_closure": ended_with_goodbye,
    #         "conversation_topics": conversation_topics,
    #         "caller_message_count": len(caller_messages),
    #         "ai_message_count": len(ai_messages),
    #     }

    # -------- Inspection APIs --------

    def get_history(self, session_id: Optional[str] = None, status: Optional[str] = None):
        """Return in-memory sessions (no DB reads)."""
        if session_id:
            session = self.sessions.get(session_id)
            if not session:
                return {"error": "Session not found"}
            return {
                "session_id": session_id,
                "conversation": session,
                "analysis": session.get("analysis") or self._analyze_session(session),
            }

        # Filter by status if provided
        if status == "active":
            filtered = {sid: s for sid, s in self.sessions.items() if s.get("status") == "live"}
        elif status == "closed":
            filtered = {sid: s for sid, s in self.sessions.items() if s.get("status") == "closed"}
        else:
            filtered = self.sessions

        return {
            sid: {
                **session,
                "analysis": session.get("analysis") or self._analyze_session(session),
                "status": session.get("status") or ("active" if session.get("end_time") is None else "closed"),
            }
            for sid, session in filtered.items()
        }

    def get_active_session_ids(self) -> List[str]:
        return [sid for sid, s in self.sessions.items() if s.get("status") == "live"]

    # -------- One-shot DB commit --------

    def flush_to_supabase(
        self,
        supabase,
        session_id: str,
        *,
        company_id: str = None,
        office_id: str = None,
        phone_number_id: str = None,
        caller_id: str = "unknown",
    ):
        """
        Upsert conversation (mapped to current schema) and bulk-insert messages.
        Safe to call multiple times; conversation is upserted and only non-persisted
        messages are inserted. Requires company_id/office_id/phone_number_id either
        passed in or already stored on the session.
        """
        if session_id not in self.sessions:
            return

        sess = self.sessions[session_id]

        # Allow call-site to pass IDs; otherwise use what's on the session.
        sess.setdefault("company_id", company_id)
        sess.setdefault("office_id", office_id)
        sess.setdefault("phone_number_id", phone_number_id)

        # ✅ Validate required FKs for conversations table
        missing = [k for k in ("company_id", "office_id", "phone_number_id") if not sess.get(k)]
        if missing:
            raise ValueError(f"flush_to_supabase missing required IDs on session {session_id}: {', '.join(missing)}")

        # ✅ Ensure/Upsert conversation row with proper column mapping
        self._ensure_conversation_row(supabase, session_id, caller_id, sess)

        # ✅ Prepare message rows; insert only ones not yet persisted
        msgs = [m for m in sess.get("messages", []) if not m.get("_persisted")]
        if not msgs:
            logger.info(f"🪶 No new messages to persist for session {session_id}")
            return

        allowed_keys = {
            "role",
            "transcript",
            "language",
            "confidence",
            "created_at",
            "translated_text",
            "intent",
            "ai_response",
            "ai_response_translated",
            "urgent",
            "sentiment",
            "is_final",
            "timestamp",
            "metadata",   # jsonb column exists in your DDL
            "audio_id",   # text column exists in your DDL
        }

        rows = []
        for m in msgs:
            # default role if missing
            role = m.get("role") or ("assistant" if m.get("ai_response") else "user")
            row = {"session_id": session_id, "role": role}

            for k, v in m.items():
                if k in allowed_keys and v is not None:
                    row[k] = v

            # ensure timestamps exist
            from datetime import datetime
            if "created_at" not in row or not row["created_at"]:
                row["created_at"] = datetime.utcnow().isoformat()
            if "timestamp" not in row or not row["timestamp"]:
                row["timestamp"] = row["created_at"]

            rows.append(row)

        # ✅ Bulk insert
        if rows:
            CHUNK = 1000
            for i in range(0, len(rows), CHUNK):
                supabase.table("messages").insert(rows[i:i + CHUNK]).execute()
                logger.info(f"💾 Inserted {len(rows[i:i + CHUNK])} messages for session {session_id}")

            # mark as persisted only after successful insert
            for m in msgs:
                m["_persisted"] = True

        logger.info(f"✅ flush_to_supabase completed for session {session_id}")


    def _ensure_conversation_row(self, supabase, session_id: str, caller_id: str, sess: Dict[str, Any]):
        # Does it already exist?
        convo = supabase.table("conversations").select("id").eq("id", session_id).execute()

        # REQUIRED: these must be present on the session (set them earlier in your route)
        company_id = sess.get("company_id")
        office_id = sess.get("office_id")
        phone_number_id = sess.get("phone_number_id")

        if not (company_id and office_id and phone_number_id):
            # fail fast with a clear log if you forgot to resolve IDs from phone
            raise ValueError("Missing company_id/office_id/phone_number_id for conversation upsert")

        # Map old → new and normalize status
        mapped_status = sess.get("status") or ("closed" if sess.get("end_time") else "open")
        if mapped_status == "live":
            mapped_status = "open"

        meta = (sess.get("metadata") or {}).copy()
        if caller_id and not meta.get("caller_id"):
            meta["caller_id"] = caller_id

        payload = {
            "company_id": company_id,
            "office_id": office_id,
            "phone_number_id": phone_number_id,
            "direction": sess.get("direction", "inbound"),
            "status": mapped_status,
            "language": sess.get("language"),
            "intent_summary": sess.get("analysis") or self._analyze_session(sess),  # jsonb
            "recording_url": sess.get("recording_url"),
            "metadata": meta,
            "started_at": sess.get("start_time"),
            "ended_at": sess.get("end_time"),
        }

        if not convo.data:
            supabase.table("conversations").insert({"id": session_id, **payload}).execute()
        else:
            supabase.table("conversations").update(payload).eq("id", session_id).execute()

    def resolve_service_by_phone(self, supabase, phone_number: str):
        """
        Lookup service_name based on phone_number → office → service_config
        """
        try:
            result = (
                supabase.table("phone_numbers")
                .select("office_id, offices(company_id)")
                .eq("number", phone_number)
                .execute()
            )

            if not result.data:
                return "caregiving"  # default fallback

            office_id = result.data[0]["office_id"]
            config = (
                supabase.table("service_configs")
                .select("service_name")
                .eq("office_id", office_id)
                .limit(1)
                .execute()
            )

            return config.data[0]["service_name"] if config.data else "caregiving"

        except Exception as e:
            import logging
            logging.error(f"[Service Resolver] Failed for {phone_number}: {e}")
            return "caregiving"


conversation_manager = ConversationManager()
