# transcript_service.py — Buffer-in-memory + language hint + Groq as source of truth

# import asyncio
# import re
# from datetime import datetime
# import uuid
# from collections import Counter

# from app.core.connection_manager import manager
# from app.core.config import logger
# from app.services.groq_client import groq_client
# from app.services.conversation_manager import conversation_manager
# from app.db.supabase import supabase

# from app.utils.parsers import extract_name, extract_phone

# # --- Constants ---
# GOODBYE_PHRASES = [
#     # English
#     "goodbye", "good bye", "bye", "bye-bye", "bye bye", "see you", "talk later",
#     "thanks, that's all", "that's all", "that is all", "i'm done", "im done",
#     "thank you", "thanks", "have a good day", "good day", "have a great day",
#     "no, that's it", "no thats it", "no that's it", "no thats it",
#     "no thank you", "no thanks", "no thank you", "no thanks",
#     "that's it", "thats it", "that is it", "that's all", "thats all",
#     "nothing else", "nothing more", "all set", "all good",
#     # Spanish
#     "adios", "adiós", "hasta luego", "hasta pronto", "no gracias", "no más",
# ]
# CONTEXT_WINDOW = 5
# MIN_WORDS_FOR_LLM = 3  # don't classify/respond to tiny backchannel utterances


# # ---------------- Deepgram callbacks ----------------

# def on_error(_, error, **kwargs):
#     logger.error(f"⛔ Deepgram error: {error}")

# def on_transcript(_, result, **kwargs):
#     if not result or not result.channel or not result.channel.alternatives:
#         return

#     alt = result.channel.alternatives[0]
#     transcript = getattr(alt, "transcript", "") or ""
#     if not transcript.strip():
#         return

#     # Try to grab a language hint from STT (fallback to 'en' for MVP)
#     stt_lang_hint = getattr(alt, "language", None) or getattr(result.channel, "language", None) or "en"

#     # Broadcast everything to the UI live (no DB writes here)
#     asyncio.run_coroutine_threadsafe(
#         manager.broadcast({
#             "type": "transcript",
#             "transcript": transcript,
#             "is_final": result.is_final,
#             "timestamp": datetime.now().isoformat()
#         }),
#         manager.loop
#     )

#     if result.is_final:
#         # IMPORTANT: do not await here inside Deepgram thread; schedule the coroutine
#         asyncio.run_coroutine_threadsafe(
#             process_final_transcript(transcript, stt_lang_hint=stt_lang_hint),
#             manager.loop
#         )


# # ---------------- Core pipeline ----------------

# def _extract_slot_information(transcript: str, language: str) -> dict:
#     """
#     Extract slot information from transcript for conversation memory.
#     """
#     slots = {}
#     transcript_lower = transcript.lower()
    
#     # Extract care needs
#     care_needs = []
#     if any(word in transcript_lower for word in ["medication", "medicamento", "pills", "pastillas"]):
#         care_needs.append("medication_reminders")
#     if any(word in transcript_lower for word in ["companion", "compañía", "company", "conversation", "conversación"]):
#         care_needs.append("companionship")
#     if any(word in transcript_lower for word in ["walking", "caminar", "exercise", "ejercicio", "activity", "actividad"]):
#         care_needs.append("walking_support")
#     if any(word in transcript_lower for word in ["meal", "comida", "cooking", "cocinar", "food", "alimento"]):
#         care_needs.append("meal_prep")
#     if any(word in transcript_lower for word in ["housekeeping", "limpieza", "cleaning", "housework", "trabajo doméstico"]):
#         care_needs.append("light_housekeeping")
    
#     if care_needs:
#         slots["care_needs"] = care_needs
    
    
#     # Extract schedule information
#     if any(word in transcript_lower for word in ["morning", "mañana", "mornings", "mañanas"]):
#         slots["time_preference"] = "morning"
#     elif any(word in transcript_lower for word in ["afternoon", "tarde", "afternoons", "tardes"]):
#         slots["time_preference"] = "afternoon"
#     elif any(word in transcript_lower for word in ["evening", "noche", "evenings", "noches"]):
#         slots["time_preference"] = "evening"
    
#     # Extract hours per week
#     import re
#     hours_match = re.search(r'(\d+)\s*(?:hours?|horas?)', transcript_lower)
#     if hours_match:
#         slots["hours_per_week"] = int(hours_match.group(1))
    
#     # Extract days
#     if any(word in transcript_lower for word in ["weekday", "weekdays", "días de semana"]):
#         slots["days"] = "weekdays"
#     elif any(word in transcript_lower for word in ["weekend", "weekends", "fines de semana"]):
#         slots["days"] = "weekends"
#     elif any(word in transcript_lower for word in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
#         days = []
#         day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
#         for day in day_names:
#             if day in transcript_lower:
#                 days.append(day)
#         if days:
#             slots["days"] = days
    
#     # Extract start date
#     date_match = re.search(r'(?:start|begin|comenzar|iniciar).*?(?:on|el|la)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2})', transcript_lower)
#     if date_match:
#         slots["start_date"] = date_match.group(1)
    
#     return slots

# def _extract_slots_from_transcript(transcript: str) -> dict:
#     """
#     Extract lightweight slot information from transcript for conversation memory.
#     Returns slots dict with care_needs, hours_per_week, days, time_of_day.
#     """
#     slots = {
#         "care_needs": set(),
#         "hours_per_week": None,
#         "days": set(),
#         "time_of_day": None
#     }
    
#     transcript_lower = transcript.lower()
    
#     # Extract care needs
#     care_keywords = {
#         "medication reminders": ["medication", "medicine", "pills", "medicamento", "medicina", "pastillas"],
#         "companionship": ["companion", "company", "someone to talk", "conversation", "compañía", "conversación"],
#         "walking": ["walking", "walk", "exercise", "caminar", "caminata", "ejercicio"],
#         "meal prep": ["meal", "cooking", "food", "comida", "cocinar", "preparar"],
#         "light housekeeping": ["housekeeping", "cleaning", "housework", "limpieza", "trabajo doméstico"]
#     }
    
#     for need, keywords in care_keywords.items():
#         if any(keyword in transcript_lower for keyword in keywords):
#             slots["care_needs"].add(need)
    
#     # Extract hours per week
#     hours_match = re.search(r'(\d+)\s*(?:hours?|hrs?|horas?)\s*(?:per|a)\s*(?:week|semana)', transcript_lower)
#     if hours_match:
#         slots["hours_per_week"] = int(hours_match.group(1))
    
#     # Extract days
#     day_keywords = {
#         "monday": ["monday", "mon", "lunes"],
#         "tuesday": ["tuesday", "tue", "martes"],
#         "wednesday": ["wednesday", "wed", "miércoles"],
#         "thursday": ["thursday", "thu", "jueves"],
#         "friday": ["friday", "fri", "viernes"],
#         "saturday": ["saturday", "sat", "sábado"],
#         "sunday": ["sunday", "sun", "domingo"]
#     }
    
#     for day, keywords in day_keywords.items():
#         if any(keyword in transcript_lower for keyword in keywords):
#             slots["days"].add(day)
    
#     # Extract time of day
#     if any(word in transcript_lower for word in ["morning", "mornings", "mañana", "mañanas"]):
#         slots["time_of_day"] = "mornings"
#     elif any(word in transcript_lower for word in ["afternoon", "afternoons", "tarde", "tardes"]):
#         slots["time_of_day"] = "afternoons"
#     elif any(word in transcript_lower for word in ["evening", "evenings", "noche", "noches"]):
#         slots["time_of_day"] = "evenings"
    
#     return slots

# def _update_slots(session_id: str, new_slots: dict):
#     """
#     Update session slots with new information.
#     """
#     if session_id not in conversation_manager.sessions:
#         return
    
#     current_slots = conversation_manager.sessions[session_id].get("slots", {})
    
#     # Merge care_needs sets
#     if "care_needs" in new_slots:
#         current_slots["care_needs"].update(new_slots["care_needs"])
    
#     # Update other fields if provided
#     for key in ["hours_per_week", "time_of_day"]:
#         if key in new_slots and new_slots[key] is not None:
#             current_slots[key] = new_slots[key]
    
#     # Merge days sets
#     if "days" in new_slots:
#         current_slots["days"].update(new_slots["days"])
    
#     conversation_manager.sessions[session_id]["slots"] = current_slots

# def _get_conversation_context(session_id: str) -> dict:
#     """
#     Get conversation context including slot information.
#     """
#     if session_id not in conversation_manager.sessions:
#         logger.warning(f"Session {session_id} not found when getting conversation context")
#         return {}
    
#     session = conversation_manager.sessions[session_id]
#     return session.get("conversation_context", {})

# def _update_conversation_context(session_id: str, new_slots: dict):
#     """
#     Update conversation context with new slot information.
#     """
#     if session_id not in conversation_manager.sessions:
#         logger.warning(f"Session {session_id} not found when updating conversation context")
#         return
    
#     current_context = conversation_manager.sessions[session_id].get("conversation_context", {})
    
#     # Merge new slots with existing context
#     for key, value in new_slots.items():
#         if key == "care_needs" and "care_needs" in current_context:
#             # Merge care needs lists
#             existing = set(current_context["care_needs"])
#             new = set(value)
#             current_context["care_needs"] = list(existing.union(new))
#         else:
#             current_context[key] = value
    
#     conversation_manager.sessions[session_id]["conversation_context"] = current_context

# async def process_final_transcript(transcript: str, caller_id: str = "unknown", stt_lang_hint: str = "en"):
#     """
#     Handle a final transcript chunk:
#       - classify with Groq (using STT language hint),
#       - optionally do job-applicant lookup,
#       - buffer message in memory (no DB write),
#       - on goodbye -> close + single commit to Supabase.
#     """
#     # 1) Get or create in-memory session ID
#     session_id = conversation_manager.get_or_create_active_session(caller_id)

#     # 2) Context (recent messages)
#     history = conversation_manager.sessions[session_id]["messages"]
#     recent_history = history[-CONTEXT_WINDOW:]
#     context = "\n".join([
#         f"User: {m.get('transcript','')}\nAI: {m.get('ai_response','')}"
#         for m in recent_history if m.get("ai_response")
#     ])
    
#     # Build context_messages for Groq (OpenAI-style format)
#     context_messages = []
#     for msg in recent_history:
#         if msg.get("transcript") and msg.get("ai_response"):
#             # Skip backchannels and polite closures for context
#             if msg.get("intent") not in ["backchannel", "polite_closure", "goodbye"]:
#                 context_messages.append({
#                     "role": "user",
#                     "content": msg.get("transcript", "")
#                 })
#                 context_messages.append({
#                     "role": "assistant", 
#                     "content": msg.get("ai_response", "")
#                 })

#     # 3) If the utterance is too short, don't spam LLM/TTS; store in memory and exit
#     if len(transcript.strip().split()) < MIN_WORDS_FOR_LLM:
#         entry = {
#             "message_id": str(uuid.uuid4()),
#             "transcript": transcript,
#             "translated_text": transcript,
#             "intent": "backchannel",
#             "ai_response": None,
#             "ai_response_translated": None,
#             "urgent": False,
#             "language": stt_lang_hint or "en",
#             "is_final": True,
#             "timestamp": datetime.now().isoformat(),
#         }
#         conversation_manager.add_message(session_id, entry)
#         return session_id, entry

#     # 4) Extract slot information for conversation memory
#     new_slots = _extract_slot_information(transcript, stt_lang_hint)
#     if new_slots:
#         _update_conversation_context(session_id, new_slots)
    
#     # Also extract lightweight slots for conversation flow
#     lightweight_slots = _extract_slots_from_transcript(transcript)
#     if any(lightweight_slots.values()):
#         _update_slots(session_id, lightweight_slots)

#     # 5) Determine conversation flow type
#     is_greeting_only = _is_greeting_only(transcript)
#     is_meaningful_inquiry = _is_meaningful_inquiry(transcript)
#     is_continuation = _is_continuation_phrase(transcript)
#     is_first_turn = _is_first_turn_inquiry(transcript, history)
    
#     # Get conversation context for slot information
#     conversation_context = _get_conversation_context(session_id)
    
#     # Debug logging
#     logger.info(f"🔍 Conversation flow detection for '{transcript}':")
#     logger.info(f"  - is_greeting_only: {is_greeting_only}")
#     logger.info(f"  - is_meaningful_inquiry: {is_meaningful_inquiry}")
#     logger.info(f"  - is_continuation: {is_continuation}")
#     logger.info(f"  - is_first_turn: {is_first_turn}")
#     logger.info(f"  - history length: {len(history)}")
#     logger.info(f"  - conversation_context: {conversation_context}")
#     logger.info(f"  - slots: {conversation_manager.sessions[session_id].get('slots', {})}")

#     # 6) Primary path: use Groq for intent + response (with language hint)
#     intent_result = None
#     ai_response = None
#     detected_intent = None
#     job_application_found = False

#     # If we think it's a NEW job application inquiry, run lookup directly;
#     # otherwise, ask Groq first (Groq may also say it's a job application).
#     is_new_job_inquiry = await _is_new_job_application_inquiry(transcript, history)

#     if is_new_job_inquiry:
#         logger.info(f"NEW job application inquiry detected (pre-Groq): {transcript}")
#         ai_response, job_application_found = await _handle_job_application_lookup(transcript)
#         detected_intent = "job_application_status"
#         # Minimal result so downstream fields exist
#         intent_result = {
#             "translated_text": transcript,
#             "detected_language": stt_lang_hint or "en",
#             "intent": detected_intent,
#             "urgent": False,  # lookup itself not urgent
#             "ai_response": ai_response,
#             "ai_response_translated": ai_response,
#         }
#     else:
#         # Ask Groq for structured JSON (intent, language, responses, urgent)
#         intent_result = await _handle_natural_conversation(
#             transcript, context, history, stt_lang_hint, session_id,
#             is_first_turn, is_greeting_only, is_continuation, False,  # No urgent escalation
#             context_messages, is_meaningful_inquiry
#         )
#         ai_response = intent_result.get("ai_response") or "I'm here to help. What can I assist you with?"
#         detected_intent = intent_result.get("intent", "general_conversation")

#         # If Groq says this *is* a job application/status request, run the lookup and overwrite response
#         if detected_intent in {"job_application", "application_status", "job_application_status"}:
#             ai_response, job_application_found = await _handle_job_application_lookup(transcript)
#             detected_intent = "job_application_status"
#             intent_result["ai_response"] = ai_response
#             intent_result["ai_response_translated"] = ai_response

#     # 5) Build final entry (pull fields from Groq result wherever possible)
#     entry = {
#         "message_id": str(uuid.uuid4()),
#         "transcript": transcript,
#         "translated_text": intent_result.get("translated_text", transcript),
#         "intent": detected_intent,
#         "ai_response": intent_result.get("ai_response", ai_response),
#         "ai_response_translated": intent_result.get("ai_response_translated", ai_response),
#         "urgent": bool(intent_result.get("urgent", False)),
#         "language": intent_result.get("detected_language", stt_lang_hint or "en"),
#         "is_final": True,
#         "timestamp": datetime.now().isoformat(),
#     }

#     # 6) Save to in-memory manager ONLY (no DB write here)
#     conversation_manager.add_message(session_id, entry)

#     # 7) Session-level analysis (cached in memory)
#     msgs = conversation_manager.sessions[session_id]["messages"]
#     intents = [m.get("intent") for m in msgs if m.get("intent")]
#     counter = Counter(intents)
#     analysis = {
#         "summary": f"Conversation with {len(msgs)} messages",
#         "main_intent": counter.most_common(1)[0][0] if counter else "unknown",
#         "urgent": any(bool(m.get("urgent")) for m in msgs),
#         "total_messages": len(msgs),
#         "intents_distribution": dict(counter),
#         "ended_with_closure": any(m.get("intent") in ["polite_closure", "goodbye"] for m in msgs),
#     }
#     conversation_manager.sessions[session_id]["analysis"] = analysis

#     # 8) Check for conversation closure
#     lowered = transcript.strip().lower()
#     # Remove punctuation for better matching
#     cleaned_transcript = lowered.replace(",", "").replace(".", "").replace("!", "").replace("?", "")
    
#     logger.info(f"🔍 Checking goodbye phrases in: '{cleaned_transcript}'")
    
#     if any(phrase in cleaned_transcript for phrase in GOODBYE_PHRASES):
#         logger.info(f"✅ Goodbye detected! Closing session {session_id}")
#         # Mark closed and do a single commit to Supabase
#         conversation_manager.mark_closed(session_id, analysis)
#         try:
#             conversation_manager.flush_to_supabase(supabase, session_id, caller_id)
#         except Exception as e:
#             logger.error(f"Commit on goodbye failed: {e}")
#         entry["session_closed"] = True
#     else:
#         logger.info(f"❌ No goodbye phrase found in: '{cleaned_transcript}'")

#     return session_id, entry


# # ---------------- Intent helpers ----------------

# def _is_greeting_only(transcript: str) -> bool:
#     """
#     Determine if this is just a greeting without meaningful inquiry.
#     """
#     greeting_phrases = [
#         "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
#         "how are you", "how are you doing", "how's it going",
#         "hola", "buenos días", "buenas tardes", "buenas noches", "¿cómo está?",
#         "¿cómo está usted?", "¿cómo estás?", "¿qué tal?"
#     ]
    
#     transcript_lower = transcript.lower().strip()
#     # Check if it's only greetings and common pleasantries
#     words = transcript_lower.split()
#     if len(words) <= 3:  # Short phrases
#         return any(phrase in transcript_lower for phrase in greeting_phrases)
    
#     return False

# def _is_meaningful_inquiry(transcript: str) -> bool:
#     """
#     Determine if this is a meaningful inquiry about caregiving services.
#     """
#     inquiry_keywords = [
#         "caregiving", "caregiver", "care", "services", "help", "assistance",
#         "elderly", "senior", "aging", "support", "companion", "medication",
#         "housekeeping", "meal", "walking", "activity", "schedule", "needs",
#         "information", "about", "tell me", "know more", "learn", "details",
#         "would like to know", "want to know", "need to know", "interested in",
#         "cuidado", "cuidador", "servicios", "ayuda", "asistencia", "anciano",
#         "mayor", "envejecimiento", "apoyo", "compañía", "medicamento",
#         "limpieza", "comida", "caminar", "actividad", "horario", "necesidades",
#         "información", "sobre", "cuéntame", "saber más", "aprender", "detalles",
#         "me gustaría saber", "quiero saber", "necesito saber", "estoy interesado"
#     ]
    
#     transcript_lower = transcript.lower()
#     return any(keyword in transcript_lower for keyword in inquiry_keywords)

# def _is_continuation_phrase(transcript: str) -> bool:
#     """
#     Determine if this is a continuation phrase that should maintain context.
#     """
#     continuation_phrases = [
#         "i'd like to discuss further", "please tell me more", "can we continue",
#         "can you discuss", "can you talk", "can you tell me more",
#         "ok", "okay", "yes", "sure", "that sounds good", "let's continue",
#         "tell me more", "go on", "continue", "next", "what else",
#         "awesome", "great", "perfect", "that works", "sounds good",
#         "i just told you", "i already told you", "i said", "as i mentioned",
#         "like i said", "as i said", "i need", "i want", "i would like",
#         "me gustaría discutir más", "por favor cuéntame más", "podemos continuar",
#         "puedes discutir", "puedes hablar", "puedes contarme más",
#         "ok", "sí", "seguro", "suena bien", "continuemos", "cuéntame más",
#         "continúa", "siguiente", "qué más", "genial", "perfecto",
#         "ya te dije", "como mencioné", "como dije", "necesito", "quiero"
#     ]
    
#     transcript_lower = transcript.lower().strip()
#     return any(phrase in transcript_lower for phrase in continuation_phrases)

# def _is_first_turn_inquiry(transcript: str, history: list) -> bool:
#     """
#     Determine if this is a first-turn inquiry about caregiving services.
#     Returns True if:
#     1. This is the first meaningful message in the conversation (no previous AI responses)
#     2. The transcript contains inquiry keywords about caregiving services
#     """
#     # Check if there are any previous AI responses (indicating this isn't the first turn)
#     has_previous_ai_responses = any(msg.get("ai_response") for msg in history)
#     if has_previous_ai_responses:
#         return False
    
#     return _is_meaningful_inquiry(transcript)



# async def _handle_natural_conversation(transcript: str, context: str, history: list, stt_lang_hint: str, session_id: str, is_first_turn: bool = False, is_greeting_only: bool = False, is_continuation: bool = False, requires_urgent_escalation: bool = False, context_messages: list = None, is_meaningful_inquiry: bool = False) -> dict:
#     """
#     Ask Groq for structured JSON (intent, language, responses, urgency).
#     Then layer tiny empathy/thanks tweaks AFTER we have a base response.
#     """
#     try:
#         # Use Groq classifier as the source of truth (with the language hint and conversation flow flags)
#         intent_result = groq_client.detect_intent(
#             transcript, 
#             stt_lang_hint=stt_lang_hint, 
#             is_first_turn=is_first_turn,
#             is_greeting_only=is_greeting_only,
#             is_continuation=is_continuation,
#             context_messages=context_messages
#         )

#         # Special handling for different conversation flow types - OVERRIDE Groq responses
#         logger.info(f"🔍 Response override check: greeting={is_greeting_only}, first_turn={is_first_turn}, meaningful={is_meaningful_inquiry}, continuation={is_continuation}")
        
#         if is_greeting_only:
#             logger.info("🎯 Using GREETING response template")
#             ai_response, ai_response_translated = groq_client._generate_greeting_response(stt_lang_hint)
#             intent_result["ai_response"] = ai_response
#             intent_result["ai_response_translated"] = ai_response_translated
#             intent_result["intent"] = "greeting"
#         elif is_first_turn and is_meaningful_inquiry:
#             logger.info("🎯 Using FIRST-TURN INQUIRY response template")
#             ai_response, ai_response_translated = groq_client._generate_first_turn_inquiry_response(stt_lang_hint)
#             intent_result["ai_response"] = ai_response
#             intent_result["ai_response_translated"] = ai_response_translated
#             intent_result["intent"] = "inquiry"
#         elif is_continuation:
#             logger.info("🎯 Using CONTINUATION response template")
#             # Get conversation context and slots for continuation responses
#             conversation_context = _get_conversation_context(session_id)
#             slots = conversation_manager.sessions[session_id].get("slots", {})
#             logger.info(f"📋 Conversation context: {conversation_context}")
#             logger.info(f"📋 Slots: {slots}")
#             ai_response, ai_response_translated = groq_client._generate_continuation_response(stt_lang_hint, conversation_context, slots)
#             intent_result["ai_response"] = ai_response
#             intent_result["ai_response_translated"] = ai_response_translated
#             intent_result["intent"] = "continuation"
#         else:
#             logger.info("🎯 Using GROQ response (no special template)")

#         # Optional: light tone tweaks after the fact
#         recent_messages = history[-3:] if history else []
#         last_ai = (recent_messages[-1].get("ai_response") or "") if recent_messages else ""
#         is_after_bad_news = any(k in last_ai.lower() for k in ["not selected", "unfortunately", "rejected", "not chosen", "unsuccessful"])

#         tl = transcript.lower()
#         if is_after_bad_news and any(w in tl for w in ["sad", "disappointed", "upset", "thank"]):
#             msg = (
#                 "I'm sorry this feels discouraging. If you'd like, I can help you explore other opportunities "
#                 "or answer any questions about next steps."
#             )
#             intent_result["ai_response"] = msg
#             intent_result["ai_response_translated"] = msg

#         elif "thank" in tl:
#             msg = "You're very welcome! Is there anything else I can help you with today?"
#             intent_result["ai_response"] = msg
#             intent_result["ai_response_translated"] = msg

#         return intent_result

#     except Exception as e:
#         logger.error(f"Error in natural conversation handling: {e}")
#         # Minimal fallback shape (mirrors groq_client._fallback_response)
#         return {
#             "translated_text": transcript,
#             "detected_language": stt_lang_hint or "en",
#             "intent": "general_conversation",
#             "urgent": False,
#             "ai_response": "I'm here to help. What can I assist you with?",
#             "ai_response_translated": "I'm here to help. What can I assist you with?",
#         }


# # ---------------- Job applicant flow (same logic, minor safety) ----------------

# async def _is_new_job_application_inquiry(transcript: str, history: list) -> bool:
#     """Determine if this is a NEW job application inquiry (not a follow-up)."""
#     recent_job_responses = [msg for msg in history[-3:] if msg.get("intent") == "job_application_status"]
#     if recent_job_responses:
#         indicators = [
#             "i applied", "my application", "job application", "application status",
#             "check my status", "what's my status", "status of my application"
#         ]
#         tl = transcript.lower()
#         if not any(ind in tl for ind in indicators):
#             logger.info("Treating as follow-up conversation, not new job inquiry")
#             return False

#     job_keywords = [
#         "job application", "application status", "applied", "status of my application",
#         "follow up on my application", "hiring", "interview", "employment",
#         "position", "job status", "application", "when will I hear back",
#         "still under review", "applied for", "submitted application"
#     ]
#     tl = transcript.lower()
#     return any(keyword in tl for keyword in job_keywords)


# async def _handle_job_application_lookup(transcript: str) -> tuple[str, bool]:
#     """
#     Handle job application lookup and return response and found status.
#     """
#     try:
#         phone = extract_phone(transcript)
#         name = extract_name(transcript)
#         logger.info(f"Extracted - Phone: {phone}, Name: {name}")

#         if not phone and not name:
#             return (
#                 "I'd be happy to help you check your job application status! "
#                 "Could you please provide your full name or the phone number you used when applying?",
#                 False
#             )

#         applications = await _search_job_applications(phone, name)
#         if applications:
#             app = applications[0]
#             response = _format_job_application_response(app)
#             logger.info(f"Job application found for: {app.get('name')} - {app.get('position')}")
#             return response, True

#         # Not found → helpful prompt
#         if phone and name:
#             response = (
#                 f"I couldn't find an application for {name} with phone number ending in "
#                 f"{phone[-4:]} in our records. Please double-check the information or "
#                 f"contact our HR department directly."
#             )
#         elif phone:
#             response = (
#                 f"I couldn't find an application with phone number ending in {phone[-4:]}. "
#                 f"Could you also provide the name you used when applying?"
#             )
#         else:
#             response = (
#                 f"I couldn't find an application for {name}. "
#                 f"Could you provide the phone number you used when applying?"
#             )
#         logger.info(f"No job application found for phone: {phone}, name: {name}")
#         return response, False

#     except Exception as e:
#         logger.error(f"Error in job application lookup: {e}")
#         return (
#             "I'm having trouble accessing our application database right now. "
#             "Please try again in a moment or contact our HR department directly.",
#             False
#         )


# async def _search_job_applications(phone: str, name: str) -> list:
#     applications = []
#     try:
#         if phone:
#             phone_formats = [
#                 phone,
#                 f"{phone[:3]}-{phone[3:6]}-{phone[6:]}" if len(phone) == 10 else phone,
#                 f"({phone[:3]}) {phone[3:6]}-{phone[6:]}" if len(phone) == 10 else phone,
#             ]
#             for phone_format in phone_formats:
#                 result = supabase.table("job_applications").select("*").eq("phone_number", phone_format).execute()
#                 if result.data:
#                     applications.extend(result.data)
#                     break

#         if not applications and name:
#             result = supabase.table("job_applications").select("*").ilike("name", name).execute()
#             if result.data:
#                 applications.extend(result.data)
#             else:
#                 for part in name.split():
#                     if len(part) > 2:
#                         result = supabase.table("job_applications").select("*").ilike("name", f"%{part}%").execute()
#                         if result.data:
#                             applications.extend(result.data)
#                             break

#         # de-dup while preserving order
#         seen = set()
#         unique = []
#         for app in applications:
#             app_id = app.get("id")
#             if app_id not in seen:
#                 seen.add(app_id)
#                 unique.append(app)
#         return unique

#     except Exception as e:
#         logger.error(f"Database search error: {e}")
#         return []


# def _format_job_application_response(app: dict) -> str:
#     name = app.get('name', 'there')
#     position = app.get('position', 'the position')
#     status = app.get('status', 'under review')
#     last_contact = app.get('last_contact')
#     notes = app.get('notes', '')

#     response = f"Hi {name}! I found your application for the {position} position. "

#     status_messages = {
#         'pending': "Your application is currently **pending** and under review by our hiring team.",
#         'under review': "Your application is **under review** by our hiring team.",
#         'in review': "Your application is **in review** with our hiring manager.",
#         'interview scheduled': "Great news! Your application status is **interview scheduled**.",
#         'hired': "Congratulations! Your application status shows you've been **hired**!",
#         'rejected': "Thank you for your interest. Unfortunately, your application was **not selected** for this position.",
#         'withdrawn': "Your application shows as **withdrawn** from consideration."
#     }
#     response += status_messages.get(status.lower(), f"Your current status is **{status}**.")

#     if last_contact:
#         response += f" Our last update was on {last_contact}."

#     if status.lower() in ['pending', 'under review', 'in review']:
#         response += " We'll contact you once we have an update on your application."
#     elif status.lower() == 'interview scheduled':
#         response += " You should receive interview details soon if you haven't already."

#     if notes and notes.strip():
#         response += f" Additional notes: {notes}"

#     return response
# # ---- Manual end/flush helpers ----

# async def end_active_session(caller_id: str = "unknown"):
#     """
#     Close the in-memory active session (if any) and flush once to Supabase.
#     Useful for STOP button or when audio WebSocket disconnects without a goodbye.
#     """
#     # grab active session
#     active_ids = conversation_manager.get_active_session_ids()
#     if not active_ids:
#         return {"ok": True, "message": "No active session to end."}

#     # end & flush each active (usually one)
#     from app.db.supabase import supabase
#     ended = []
#     for sid in active_ids:
#         try:
#             # mark closed (recompute analysis if needed)
#             conversation_manager.mark_closed(sid, analysis=None)
#             # single-shot commit to DB
#             conversation_manager.flush_to_supabase(supabase, sid, caller_id=caller_id)
#             ended.append(sid)
#         except Exception as e:
#             return {"ok": False, "error": f"Failed to flush session {sid}: {e}"}

#     return {"ok": True, "ended": ended}

# app/services/transcript_service.py
# Simple, context-aware flow: last 6 pairs as context + tiny slot memory + one-next-question cadence.

# app/services/transcript_service.py
# Simple, context-aware flow: last 6 pairs as context + tiny slot memory + one-next-question cadence.

# app/services/transcript_service.py
# Simple, context-aware flow:
# - Uses last ~6 user/AI pairs as context for the LLM
# - Tiny slot memory (needs, hours, days, time_of_day, start_date, time_window)
# - Always: confirmation ("Got it — …") + ONE next question (no loops)
# - Compatibility wrappers: on_transcript, on_error, end_active_session

# app/services/transcript_service.py
# Simple, context-aware flow:
# - Uses last ~6 user/AI pairs as context for the LLM
# - Tiny slot memory (needs, hours, days, time_of_day, start_date, time_window, contact_name, contact_phone)
# - Always: confirmation ("Got it — …") + ONE next question (no loops)
# - Compatibility wrappers: on_transcript, on_error, end_active_session

# app/services/transcript_service.py
# Simple, context-aware flow:
# - Uses last ~6 user/AI pairs as context for the LLM
# - Tiny slot memory (needs, hours, days, time_of_day, start_date, time_window, contact_name, contact_phone)
# - Always: brief confirmation + ONE next question (no loops)
# - Compatibility wrappers: on_transcript, on_error, end_active_session

# app/services/transcript_service.py
# Context-aware flow with language lock + clean closures.

# import re
# from datetime import datetime
# from typing import Dict, Any, List, Set, Optional

# from app.core.config import logger
# from app.services.conversation_manager import conversation_manager
# from app.services.groq_client import groq_client
# from app.db.supabase import supabase

# # ---------- Constants / helpers ----------

# DAY_EN = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
# DAY_ES = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]

# _CONTINUATION = {
#     "ok","okay","sure","yes","yeah","yep",
#     "i’d like to discuss further","i would like to discuss further",
#     "please tell me more","tell me more","continue","can we continue","go on",
#     "sounds good","that works","let’s continue","lets continue","discuss further"
# }

# GOODBYE_PHRASES = [
#     # English
#     "goodbye","good bye","bye","bye bye","bye-bye","see you","talk later",
#     "thanks, that's all","that's all","that is all","i'm done","im done",
#     "thank you, that is all","thank you so much","that is it","that's it","thats it",
#     "nothing else","all set","all good","i will wait","i’ll wait","i will wait for your call",
#     "have a great day", "have a good day", "have an amazing day", "thanks bye", "thank you bye",
#     "thanks, bye", "thank you, bye"
#     # Spanish
#     "adios","adiós","hasta luego","hasta pronto","no gracias","no más","eso es todo",
# ]

# MONTHS = {
#     "january": "January","february":"February","march":"March","april":"April","may":"May","june":"June",
#     "july":"July","august":"August","september":"September","october":"October","november":"November","december":"December",
#     "jan":"January","feb":"February","mar":"March","apr":"April","jun":"June","jul":"July","aug":"August","sep":"September","sept":"September","oct":"October","nov":"November","dec":"December",
# }

# def _norm(s: str) -> str:
#     return (s or "").strip().lower()

# def _new_empty_slots() -> Dict[str, Any]:
#     return {
#         "care_needs": set(),
#         "hours_per_week": None,
#         "days": set(),
#         "time_of_day": None,
#         "start_date": None,     # e.g., "September 29" or "next week"
#         "time_window": None,    # e.g., "8:00am–12:00pm" or "8–12"
#         "contact_name": None,
#         "contact_phone": None,
#     }

# def _ensure_slots(session_state: Dict[str, Any]) -> Dict[str, Any]:
#     slots = session_state.get("slots")
#     if not slots:
#         slots = _new_empty_slots()
#         session_state["slots"] = slots
#     if not isinstance(slots.get("care_needs"), set):
#         slots["care_needs"] = set(slots.get("care_needs", []))
#     if not isinstance(slots.get("days"), set):
#         slots["days"] = set(slots.get("days", []))
#     return slots

# # ---------- Language preference (session-locked) ----------

# def _detect_lang_switch(text: str) -> Optional[str]:
#     """Return 'en' or 'es' if the user explicitly asks for a language; else None."""
#     t = _norm(text)
#     if any(p in t for p in ["english only","english please","only english","speak english","in english"]):
#         return "en"
#     if any(p in t for p in ["spanish only","solo español","solo espanol","en español","en espanol","habla español","habla espanol"]):
#         return "es"
#     return None

# def _get_session_lang(session: Dict[str, Any], stt_lang_hint: str) -> str:
#     """Pinned language for the whole session."""
#     pref = session.get("preferred_language")
#     if not pref:
#         pref = "es" if stt_lang_hint == "es" else "en"
#         session["preferred_language"] = pref
#     return pref

# def _set_session_lang(session: Dict[str, Any], lang: str):
#     session["preferred_language"] = "es" if lang == "es" else "en"

# # ---------- Extraction: slots ----------

# def _extract_hours(text: str) -> Optional[int]:
#     m = re.search(r'(\d{1,3})\s*(hours?|hrs?|horas?)\b(?:\s*(?:per|a)\s*(?:week|semana))?', _norm(text))
#     return int(m.group(1)) if m else None

# def _extract_time_of_day(text: str) -> Optional[str]:
#     t = _norm(text)
#     # English
#     if "morning" in t or "mornings" in t: return "mornings"
#     if "afternoon" in t or "afternoons" in t: return "afternoons"
#     if any(k in t for k in ["evening","evenings","night","nights"]): return "evenings"
#     # Basic Spanish
#     if "mañana" in t or "manana" in t: return "mornings"
#     if "tarde" in t or "tardes" in t: return "afternoons"
#     if "noche" in t or "noches" in t: return "evenings"
#     return None

# def _expand_range_en(start: str, end: str) -> List[str]:
#     i1, i2 = DAY_EN.index(start), DAY_EN.index(end)
#     return DAY_EN[i1:i2+1] if i1 <= i2 else (DAY_EN[i1:] + DAY_EN[:i2+1])

# def _extract_days(text: str) -> Set[str]:
#     """Extract days (EN), supports ranges and Spanish mapping."""
#     t = _norm(text)
#     t = t.replace("–","-").replace("—","-").replace(" to ","-").replace(" thru ","-").replace(" through ","-")
#     short = {"mon":"monday","tue":"tuesday","tues":"tuesday","wed":"wednesday","thu":"thursday","thur":"thursday","fri":"friday","sat":"saturday","sun":"sunday"}
#     for s,f in short.items():
#         t = re.sub(rf"\b{s}\b", f, t)

#     if "weekday" in t or "weekdays" in t or "lunes a viernes" in t:
#         return set(DAY_EN[:5])
#     if "weekend" in t or "weekends" in t or "fin de semana" in t or "fines de semana" in t:
#         return {"saturday","sunday"}

#     es2en = {"lunes":"monday","martes":"tuesday","miércoles":"wednesday","miercoles":"wednesday","jueves":"thursday","viernes":"friday","sábado":"saturday","sabado":"saturday","domingo":"sunday"}
#     t_es_mapped = t
#     for es,en in es2en.items():
#         t_es_mapped = re.sub(rf"\b{es}\b", en, t_es_mapped)

#     m = re.search(r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*-\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', t_es_mapped)
#     if m:
#         return set(_expand_range_en(m.group(1), m.group(2)))

#     return {d for d in DAY_EN if re.search(rf'\b{d}\b', t_es_mapped)}

# def _normalize_time(h: str, m: Optional[str], ap: Optional[str]) -> str:
#     hh = int(h)
#     mm = int(m) if m else 0
#     ap = (ap or "").lower()
#     if ap in ("am","pm"):
#         return f"{hh}:{mm:02d}{ap}"
#     return f"{hh}:{mm:02d}"

# def _extract_time_window(text: str) -> Optional[str]:
#     t = _norm(text)
#     m = re.search(
#         r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|-|–|—)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b',
#         t
#     )
#     if m:
#         s = _normalize_time(m.group(1), m.group(2), m.group(3))
#         e = _normalize_time(m.group(4), m.group(5), m.group(6))
#         return f"{s}–{e}"
#     m = re.search(r'\b(?:around\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', t)
#     if m:
#         s = _normalize_time(m.group(1), m.group(2), m.group(3))
#         return f"{s}"
#     return None

# def _extract_start_date(text: str) -> Optional[str]:
#     t = _norm(text)
#     m = re.search(r'\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b', t)
#     if m and m.group(1) in MONTHS:
#         month = MONTHS[m.group(1)]; day = int(m.group(2)); return f"{month} {day}"
#     m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+of\s+([a-z]{3,9})\b', t)
#     if m and m.group(2) in MONTHS:
#         month = MONTHS[m.group(2)]; day = int(m.group(1)); return f"{month} {day}"
#     m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', t)
#     if m:
#         mm, dd = int(m.group(1)), int(m.group(2))
#         if 1 <= mm <= 12:
#             month_name = list(MONTHS.values())[mm-1]
#             return f"{month_name} {dd}"
#     if "next week" in t:
#         return "next week"
#     return None

# def _extract_phone(raw: str) -> Optional[str]:
#     m = re.search(r'(?:\+?1[\s\-.]?)?\(?(\d{3})\)?[\s\-.]?(\d{3})[\s\-.]?(\d{4})', raw)
#     if not m:
#         m = re.search(r'(\d{3})[\s\-\.]?(\d{3})[\s\-\.]?(\d{4})', raw)
#     if m:
#         return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
#     return None

# def _extract_name(raw: str) -> Optional[str]:
#     m = re.search(r'\b(?:my\s+name\s+is|this\s+is|i\s+am)\s+([A-Za-z][A-Za-z\-\'\.]{1,})', raw, re.IGNORECASE)
#     if m:
#         return m.group(1).strip().rstrip('.')
#     m = re.search(r'\b([A-Za-z][A-Za-z\-\'\.]{2,})\b.*\b(my\s+phone|phone\s+number|best\s+phone)\b', raw, re.IGNORECASE)
#     if m:
#         return m.group(1).strip().rstrip('.')
#     m = re.match(r'\s*([A-Za-z][A-Za-z\-\'\.]{2,})\b', raw)
#     return m.group(1) if m else None

# def _update_slots_from_user(slots: Dict[str, Any], text: str, raw_text: str):
#     t = _norm(text)
#     if "compan" in t: slots["care_needs"].add("companionship")
#     if "medicat" in t or "meds" in t or "remind" in t or "recordatorio" in t: slots["care_needs"].add("medication reminders")
#     if "walk" in t or "caminar" in t: slots["care_needs"].add("walking/light activity")
#     hpw = _extract_hours(t)
#     if hpw: slots["hours_per_week"] = hpw
#     ds = _extract_days(t)
#     if ds: slots["days"].update(ds)
#     tod = _extract_time_of_day(t)
#     if tod: slots["time_of_day"] = tod
#     tw = _extract_time_window(text)
#     if tw: slots["time_window"] = tw
#     sd = _extract_start_date(text)
#     if sd: slots["start_date"] = sd
#     ph = _extract_phone(raw_text)
#     if ph: slots["contact_phone"] = ph
#     nm = _extract_name(raw_text)
#     if nm: slots["contact_name"] = nm

# # ---------- Formatting helpers ----------

# def _pretty_days_en(ds: Set[str]) -> str:
#     if not ds: return ""
#     s = set(d.lower() for d in ds)
#     if s == set(DAY_EN[:5]): return "Mon–Fri"
#     if s == set(DAY_EN): return "Mon–Sun"
#     ordered = [d for d in DAY_EN if d in s]
#     return ", ".join(d.title() for d in ordered)

# def _pretty_days_es(ds: Set[str]) -> str:
#     if not ds: return ""
#     s = set(d.lower() for d in ds)
#     if s == set(DAY_EN[:5]): return "Lun–Vie"
#     if s == set(DAY_EN): return "Lun–Dom"
#     en2es = dict(zip(DAY_EN, DAY_ES))
#     ordered = [en2es[d] for d in DAY_EN if d in s]
#     return ", ".join(w.capitalize() for w in ordered)

# def _confirmation_localized(slots: Dict[str, Any], lang: str) -> str:
#     needs = []
#     if slots["care_needs"]:
#         if lang == "es":
#             map_es = {
#                 "companionship": "compañía",
#                 "medication reminders": "recordatorios de medicamentos",
#                 "walking/light activity": "apoyo para caminar/actividad ligera",
#             }
#             needs = [map_es.get(n, n) for n in sorted(slots["care_needs"])]
#         else:
#             needs = sorted(slots["care_needs"])

#     tod = slots["time_of_day"]
#     if lang == "es":
#         if tod == "mornings": tod = "mañanas"
#         elif tod == "afternoons": tod = "tardes"
#         elif tod == "evenings": tod = "noches"

#     bits = []
#     if needs: bits.append(" & ".join(needs))
#     if tod: bits.append(tod)
#     if slots["hours_per_week"]:
#         bits.append(f'~{slots["hours_per_week"]} ' + ("horas/semana" if lang == "es" else "hrs/week"))
#     if slots["days"]:
#         bits.append(_pretty_days_es(slots["days"]) if lang == "es" else _pretty_days_en(slots["days"]))
#     if slots.get("start_date"):
#         bits.append(slots["start_date"])
#     if slots.get("time_window"):
#         bits.append(slots["time_window"])

#     prefix = "Entendido — " if lang == "es" else "Got it — "
#     return (prefix + ", ".join(bits) + ".") if bits else ("Entendido." if lang == "es" else "Got it.")

# def _next_question_localized(slots: Dict[str, Any], lang: str) -> str:
#     if slots["hours_per_week"] is None:
#         return "¿Cuántas horas por semana le gustaría?" if lang == "es" else "How many hours per week would you like?"
#     if not slots["days"]:
#         return "¿Qué días funcionan mejor (p. ej., Lun–Vie, fines de semana)?" if lang == "es" else "Which days work best (e.g., Mon–Fri, weekends)?"
#     if not slots["time_of_day"]:
#         return "¿Qué hora del día funciona mejor — mañanas, tardes o noches?" if lang == "es" else "What time of day works best — mornings, afternoons, or evenings?"
#     if not slots.get("start_date"):
#         return "¿Qué fecha de inicio le viene mejor?" if lang == "es" else "What start date works best for you?"
#     if not slots.get("time_window"):
#         return "¿Qué horario de trabajo prefiere (p. ej., 8–12 o 9–1)?" if lang == "es" else "What work window do you prefer (e.g., 8–12 or 9–1)?"

#     name_missing = not slots.get("contact_name")
#     phone_missing = not slots.get("contact_phone")
#     if name_missing and phone_missing:
#         return "¿Me comparte su nombre y el mejor número de teléfono para confirmar?" if lang == "es" else "May I have your name and best phone number to confirm?"
#     if name_missing:
#         return "¿Cuál es su nombre para confirmar?" if lang == "es" else "May I have your name to confirm?"
#     if phone_missing:
#         return "¿Cuál es el mejor número de teléfono para confirmar?" if lang == "es" else "What is the best phone number to reach you?"

#     return "Gracias. Un miembro de nuestro equipo se comunicará con usted para confirmar los detalles. ¿Algo más en lo que pueda ayudarle?" if lang == "es" \
#         else "Thank you. A member of our team will follow up to confirm details. Is there anything else I can help with?"

# def _is_greeting_only(text: str) -> bool:
#     t = _norm(text)
#     greet = ["hello","hi","hey","good morning","good afternoon","good evening","how are you","how are you doing","hola","buenos días","buenas tardes","buenas noches"]
#     has_greet = any(p in t for p in greet)
#     has_inquiry = any(k in t for k in ["service","services","care","caregiving","help","need","interested","learn more","quote","pricing","servicio","cuidado"])
#     return has_greet and not has_inquiry

# def _is_polite_closure(text: str) -> bool:
#     t = _norm(text)
#     return any(p in t for p in GOODBYE_PHRASES)

# def _build_context_messages(messages: List[Dict[str, Any]]) -> List[dict]:
#     ctx: List[dict] = []
#     for m in messages[-12:]:
#         u = (m.get("transcript") or "").strip()
#         a = (m.get("ai_response") or "").strip()
#         if u and a:
#             ctx.append({"role": "user", "content": u})
#             ctx.append({"role": "assistant", "content": a})
#     return ctx[-12:]

# # ---------- Main entry ----------

# async def process_final_transcript(session_id_or_transcript: str,
#                                    transcript: Optional[str] = None,
#                                    stt_lang_hint: str = "en") -> tuple[str, Dict[str, Any]]:
#     # Back-compat signature handling
#     if transcript is None:
#         transcript = (session_id_or_transcript or "").strip()
#         session_id = conversation_manager.get_or_create_active_session(caller_id="unknown")
#     else:
#         session_id = session_id_or_transcript

#     transcript = (transcript or "").strip()

#     # --- Pull session & history ---
#     session = conversation_manager.sessions.get(session_id)
#     if not session:
#         new_id = conversation_manager.start_session("unknown")
#         session_id = new_id
#         session = conversation_manager.sessions[new_id]

#     messages: List[Dict[str, Any]] = session.get("messages", [])
#     has_prior_ai = any(m.get("ai_response") for m in messages)
#     first_turn = not has_prior_ai

#     # 🔒 Language lock
#     lang_pref = _get_session_lang(session, stt_lang_hint or "en")
#     # Allow explicit user switch
#     maybe_switch = _detect_lang_switch(transcript)
#     if maybe_switch:
#         _set_session_lang(session, maybe_switch)
#         lang_pref = maybe_switch

#     greeting_only = _is_greeting_only(transcript)
#     is_continuation = any(p in _norm(transcript) for p in _CONTINUATION)
#     is_closure = _is_polite_closure(transcript)

#     # Fresh intake: reset slots on first meaningful turn
#     if first_turn:
#         session["slots"] = _new_empty_slots()
#     slots = _ensure_slots(session)

#     # Do NOT learn schedule from greetings
#     if not greeting_only:
#         _update_slots_from_user(slots, transcript, raw_text=transcript)

#     # Build context for Groq
#     context_messages = _build_context_messages(messages)

#     # Call Groq with pinned language
#     result = groq_client.detect_intent(
#         transcript,
#         stt_lang_hint=lang_pref,
#         context_messages=context_messages,
#         is_first_turn=first_turn,
#         is_greeting_only=greeting_only,
#         is_continuation=is_continuation,
#     )

#     detected_intent = result.get("intent") or "inquiry"
#     lang = lang_pref  # always use session-pinned language

#     # --- Compose reply ---
#     if greeting_only:
#         ai_response = "Hello! How can I help you today?" if lang == "en" else "¡Hola! ¿En qué puedo ayudarle hoy?"
#     elif is_closure:
#         # Warm wrap-up; no new question
#         if lang == "en":
#             tail = "Thank you — we’ll follow up to confirm details."
#             if slots.get("contact_phone"):
#                 tail = f"Thank you — we’ll follow up at {slots['contact_phone']} to confirm details."
#             ai_response = tail + " Have a great day!"
#         else:
#             tail = "Gracias — nos comunicaremos para confirmar los detalles."
#             if slots.get("contact_phone"):
#                 tail = f"Gracias — nos comunicaremos al {slots['contact_phone']} para confirmar los detalles."
#             ai_response = tail + " ¡Que tenga un buen día!"

#     elif detected_intent in {"inquiry","other","backchannel","scheduling","appointment","caregiver_reschedule"} or is_continuation:
#         ai_response = f"{_confirmation_localized(slots, lang)} {_next_question_localized(slots, lang)}"
#     else:
#         model_resp = result.get("ai_response")
#         ai_response = model_resp if model_resp else f"{_confirmation_localized(slots, lang)} {_next_question_localized(slots, lang)}"

#     # Tone cleanups
#     ai_response = ai_response.replace("Perfect - ", "Got it — ").replace("Perfect. ", "Got it — ")

#     # Build English translation consistently
#     if lang == "en":
#         ai_response_translated = ai_response
#     else:
#         if is_closure:
#             tail = "Thank you — we'll follow up to confirm details."
#             if slots.get("contact_phone"):
#                 tail = f"Thank you — we’ll follow up at {slots['contact_phone']} to confirm details."
#             ai_response_translated = tail + " Have a great day!"
#         else:
#             ai_response_translated = f"{_confirmation_localized(slots, 'en')} {_next_question_localized(slots, 'en')}"

#     # Record the message
#     entry = {
#         "id": str(datetime.utcnow().timestamp()),
#         "session_id": session_id,
#         "transcript": transcript,
#         "translated_text": result.get("translated_text") or transcript,
#         "intent": "polite_closure" if is_closure else detected_intent,
#         "ai_response": ai_response,
#         "ai_response_translated": ai_response_translated,
#         "urgent": bool(result.get("urgent", False)),
#         "language": lang,
#         "is_final": True,
#         "timestamp": datetime.utcnow().isoformat(),
#     }

#     # Persist in memory
#     conversation_manager.sessions[session_id] = session
#     conversation_manager.add_message(session_id, entry)

#     # Optional: auto-close session on clear closure (keeps DB clean)
#     # Comment out if you prefer manual closing.
#     if is_closure:
#         try:
#             conversation_manager.mark_closed(session_id, analysis=None)
#             conversation_manager.flush_to_supabase(supabase, session_id, caller_id=session.get("caller_id") or "unknown")
#             entry["session_closed"] = True
#         except Exception as e:
#             logger.error(f"flush on closure failed: {e}")

#     return session_id, entry

# # ---------- Compatibility wrappers ----------

# async def on_transcript(event_or_session_id=None, transcript: Optional[str] = None, stt_lang_hint: str = "en", **kwargs):
#     if isinstance(event_or_session_id, dict):
#         payload = event_or_session_id
#         session_id = payload.get("session_id") or payload.get("sessionId")
#         txt = payload.get("transcript") or payload.get("text") or payload.get("message") or ""
#         lang = payload.get("stt_lang_hint") or payload.get("language") or stt_lang_hint or "en"
#         if session_id:
#             return await process_final_transcript(session_id, txt, lang)
#         return await process_final_transcript(txt, stt_lang_hint=lang)
#     if transcript is None:
#         return await process_final_transcript(event_or_session_id, stt_lang_hint=stt_lang_hint or "en")
#     else:
#         return await process_final_transcript(event_or_session_id, transcript, stt_lang_hint or "en")

# async def on_error(event_or_session_id=None, error: Exception | str | None = None, **kwargs):
#     if isinstance(event_or_session_id, dict):
#         payload = event_or_session_id
#         session_id = payload.get("session_id") or payload.get("sessionId")
#         err = payload.get("error") or error
#     else:
#         session_id = event_or_session_id
#         err = error
#     logger.error(f"[transcript_service.on_error] session={session_id} error={err}")
#     msg = {
#         "id": str(datetime.utcnow().timestamp()),
#         "session_id": session_id,
#         "transcript": None,
#         "translated_text": None,
#         "intent": "system_error",
#         "ai_response": None,
#         "ai_response_translated": None,
#         "urgent": False,
#         "language": "en",
#         "is_final": True,
#         "timestamp": datetime.utcnow().isoformat(),
#         "meta": {"error": str(err) if err is not None else "unknown"},
#     }
#     if session_id not in conversation_manager.sessions:
#         conversation_manager.start_session(caller_id="unknown")
#     conversation_manager.add_message(session_id, msg)
#     return {"ok": True}

# async def end_active_session(session_id: Optional[str] = None, caller_id: Optional[str] = None) -> dict:
#     try:
#         if session_id:
#             if session_id not in conversation_manager.sessions:
#                 return {"ok": False, "error": f"Unknown session_id: {session_id}"}
#             conversation_manager.mark_closed(session_id, analysis=None)
#             conversation_manager.flush_to_supabase(
#                 supabase,
#                 session_id,
#                 caller_id=caller_id or conversation_manager.sessions[session_id].get("caller_id") or "unknown",
#             )
#             return {"ok": True, "ended": [session_id]}

#         active_ids = conversation_manager.get_active_session_ids()
#         ended: List[str] = []
#         for sid in active_ids:
#             conversation_manager.mark_closed(sid, analysis=None)
#             conversation_manager.flush_to_supabase(
#                 supabase,
#                 sid,
#                 caller_id=caller_id or conversation_manager.sessions[sid].get("caller_id") or "unknown",
#             )
#             ended.append(sid)
#         return {"ok": True, "ended": ended}
#     except Exception as e:
#         logger.error(f"[transcript_service.end_active_session] {e}")
#         return {"ok": False, "error": str(e)}

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service_natural.py
# Simplified, context-aware conversation flow that responds naturally to user input

# app/services/transcript_service.py
# Complete natural conversation system with all fixes applied

# app/services/transcript_service.py
# Complete natural conversation system with all fixes applied

# app/services/transcript_service.py
# Complete natural conversation system with all fixes applied

# app/services/transcript_service.py
# Complete natural conversation system with all fixes applied

# app/services/transcript_service.py
# Complete natural conversation system with all fixes applied

import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.core.config import logger
from app.services.conversation_manager import conversation_manager
from app.services.groq_client import groq_client
from app.db.supabase import supabase

# ---------- Core conversation logic ----------

async def process_final_transcript(session_id_or_transcript: str,
                                   transcript: Optional[str] = None,
                                   stt_lang_hint: str = "en") -> tuple[str, Dict[str, Any]]:
    """
    Main entry point - processes user input and generates natural responses
    """
    # Handle back-compat signature
    if transcript is None:
        transcript = (session_id_or_transcript or "").strip()
        session_id = conversation_manager.get_or_create_active_session(caller_id="unknown")
    else:
        session_id = session_id_or_transcript

    transcript = (transcript or "").strip()
    if not transcript:
        return session_id, {"error": "Empty transcript"}

    # Get or create session
    session = conversation_manager.sessions.get(session_id)
    if not session:
        session_id = conversation_manager.start_session("unknown")
        session = conversation_manager.sessions[session_id]

    if session.get("status") == "closed":
        logger.info(f"[CLOSURE] Session {session_id} already closed, ignoring follow-up message '{transcript}'")
        return session_id, {"message": "Session already closed", "transcript": transcript}
    # Build conversation context
    messages = session.get("messages", [])
    context_messages = _build_context_messages(messages)
    
    # Determine conversation state
    is_first_meaningful_turn = not any(m.get("ai_response") for m in messages)
    user_language = _determine_language(session, transcript, stt_lang_hint)
    
    # Check for conversation closure
    if _is_goodbye(transcript):
        return await _handle_goodbye(session_id, session, transcript, user_language)
    
    # Get AI response using improved prompt
    result = await _get_natural_response(
        transcript=transcript,
        context_messages=context_messages,
        language=user_language,
        is_first_turn=is_first_meaningful_turn,
        session_context=session
    )
    
    # Build and store message entry
    entry = _create_message_entry(
        session_id=session_id,
        transcript=transcript,
        result=result,
        language=user_language
    )
    
    # Update session
    session["preferred_language"] = user_language
    conversation_manager.add_message(session_id, entry)
    
    return session_id, entry

# ---------- Natural response generation ----------

async def _get_natural_response(transcript: str, 
                               context_messages: List[dict],
                               language: str,
                               is_first_turn: bool,
                               session_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate natural response based on user input and conversation context
    """
    
    # IMPORTANT: Check for goodbye/closure FIRST before any handoff logic
    # This prevents triggering handoff on closure phrases
    if _is_goodbye(transcript):
        logger.info("[CLOSURE] Goodbye detected - generating closure response")
        return _create_goodbye_response(transcript, language, session_context)
    
    # Check if this is an appointment scheduling request that needs admin handoff
    # Do this check SECOND (after goodbye check)
    if _needs_admin_handoff(transcript, context_messages):
        logger.info("[HANDOFF] Admin handoff triggered - extracting care context")
        return _create_admin_handoff_response(transcript, language, context_messages)
    
    # Check if this is a complete client intake that needs handoff
    if _is_client_intake_complete(session_context):
        intake_info = _extract_intake_information(session_context)
        logger.info(f"[INTAKE] Intake complete - forwarding to admin: {intake_info}")
        return _create_intake_completion_response(intake_info, language)
    
    # Use Groq with natural conversation approach
    try:
        result = groq_client.detect_intent(
            transcript,
            stt_lang_hint=language,
            context_messages=context_messages,
            is_first_turn=is_first_turn,
        )
        
        # Validate the response makes sense
        ai_response = result.get("ai_response", "").strip()
        
        # Check if response seems to be repeating old context
        if context_messages and len(context_messages) >= 2:
            last_ai_msg = context_messages[-1].get("content", "") if context_messages[-1].get("role") == "assistant" else ""
            
            # If the new response is identical to a recent AI response, flag it
            if ai_response and ai_response == last_ai_msg:
                logger.warning(f"[WARNING] Detected repeated response, regenerating...")
                if language == "es":
                    ai_response = "Entiendo. ¿Hay algo más en lo que pueda ayudarle?"
                else:
                    ai_response = "I understand. Is there anything else I can help you with?"
                result["ai_response"] = ai_response
                result["ai_response_translated"] = ai_response if language == "en" else "I understand. Is there anything else I can help you with?"
        
        # Post-process for more natural responses
        result = _enhance_response_naturalness(result, transcript, language, context_messages)
        
        logger.info(f"[AI] Response generated: '{result.get('ai_response', '')[:100]}...'")
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating natural response: {e}")
        return _fallback_response(transcript, language)

def _create_goodbye_response(transcript: str, language: str, session_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a natural goodbye response without triggering handoff
    """
    transcript_lower = transcript.lower().strip()
    messages = session_context.get("messages", [])
    has_shared_info = any(msg.get("intent") in ["inquiry", "scheduling", "admin_handoff"] for msg in messages)
    
    if language == "es":
        if any(phrase in transcript_lower for phrase in ["gracias", "muchas gracias"]):
            if has_shared_info:
                ai_response = "¡De nada! Nuestro equipo se comunicará pronto para organizar todo. ¡Que tenga un buen día!"
            else:
                ai_response = "¡De nada! Estamos aquí para cuando nos necesite. ¡Que tenga un buen día!"
        else:
            if has_shared_info:
                ai_response = "¡Gracias por llamarnos! Nuestro equipo se comunicará muy pronto. ¡Que tenga un buen día!"
            else:
                ai_response = "¡Gracias por llamarnos! Estamos aquí cuando necesite apoyo. ¡Que tenga un buen día!"
        
        ai_response_translated = "Thank you for calling! Have a great day!"
    else:
        if any(phrase in transcript_lower for phrase in ["thank you", "thanks", "awesome", "have a great day", "have a wonderful day"]):
            if has_shared_info:
                ai_response = "You're very welcome! Our team will follow up with you soon. Have a wonderful day!"
            else:
                ai_response = "You're very welcome! We're here whenever you need us. Have a great day!"
        else:
            if has_shared_info:
                ai_response = "Thank you for calling! Our team will be in touch soon. Have a wonderful day!"
            else:
                ai_response = "Thank you for calling! We're here whenever you need support. Have a great day!"
        
        ai_response_translated = ai_response
    
    return {
        "original_text": transcript,
        "translated_text": transcript,
        "detected_language": language,
        "intent": "polite_closure",
        "urgent": False,
        "ai_response": ai_response,
        "ai_response_translated": ai_response_translated,
        "is_goodbye": True
    }

def _needs_admin_handoff(transcript: str, context_messages: List[dict]) -> bool:
    """
    Detect if caller provided contact info OR complete care details that need admin follow-up
    BUT NOT if we already have contact info and they're just adding details
    """
    transcript_lower = transcript.lower()
    
    # Check if they provided phone number in THIS message
    has_phone = bool(re.search(r'\b\d{3}[\s\-]?\d{3}[\s\-]?\d{4}\b', transcript))
    
    # Check if we already have contact info from PREVIOUS messages
    all_previous_conversation = " ".join([
        msg.get("content", "") for msg in context_messages 
        if msg.get("role") == "user"
    ])
    already_have_phone = bool(re.search(r'\b\d{3}[\s\-]?\d{3}[\s\-]?\d{4}\b', all_previous_conversation))
    already_have_name = any(pattern in all_previous_conversation.lower() for pattern in [
        "my name is", "i am", "this is", "i'm"
    ])
    
    # If we already have contact info, don't trigger handoff again
    # (they're just providing additional details)
    if already_have_phone and already_have_name and not has_phone:
        logger.info("[HANDOFF] Already have contact info - not triggering handoff again")
        return False
    
    # Check if they're ASKING about the process (don't trigger handoff)
    asking_for_phone_process = any(phrase in transcript_lower for phrase in [
        "do you need my phone", "need my number", "want my phone", "should i give you my phone",
        "can i give you my number", "do you want my number"
    ])
    
    if asking_for_phone_process and not has_phone:
        return False
    
    # Check for complete care details with schedule
    has_complete_care_schedule = _has_complete_care_and_schedule_details(transcript, context_messages)
    
    # Check if recent conversation mentioned scheduling
    recent_context = " ".join([msg.get("content", "") for msg in context_messages[-4:]])
    mentioned_scheduling = any(word in recent_context.lower() for word in [
        "schedule", "appointment", "call me", "contact", "follow up"
    ])
    
    # Check for scheduling-related phrases in current message
    scheduling_phrases = [
        "call me", "contact me", "schedule", "appointment", "phone number", 
        "number is", "reach me", "best time", "tomorrow", "next week"
    ]
    has_scheduling_intent = any(phrase in transcript_lower for phrase in scheduling_phrases)
    
    # Trigger handoff if: phone provided OR (scheduling intent + context) OR complete care details
    # BUT NOT if we already have all contact info
    return has_phone or (has_scheduling_intent and mentioned_scheduling) or (has_complete_care_schedule and not (already_have_phone and already_have_name))

def _has_complete_care_and_schedule_details(transcript: str, context_messages: List[dict]) -> bool:
    """
    Check if the conversation contains complete care details AND schedule information
    """
    # Combine current transcript with recent user messages
    all_conversation = transcript + " " + " ".join([
        msg.get("content", "") for msg in context_messages[-8:] 
        if msg.get("role") == "user"
    ])
    
    conversation_lower = all_conversation.lower()
    
    # Check for care recipient
    has_care_recipient = any(pattern in conversation_lower for pattern in [
        "my mom", "my mother", "my dad", "my father", "my husband", "my wife",
        "my parent", "my grandmother", "my grandfather", "for my", "care for"
    ])
    
    # Check for specific care needs
    care_needs_mentioned = any(need in conversation_lower for need in [
        "companionship", "medication", "housekeeping", "cooking", "meal",
        "walking", "exercise", "personal care", "assistance", "help with",
        "dementia", "alzheimer", "diabetic", "mobility", "safety", "remind"
    ])
    
    # Check for specific schedule details
    has_hours = bool(re.search(r'\d+\s*hours?\s*(?:per\s*)?week', conversation_lower))
    has_days = any(day in conversation_lower for day in [
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "weekday", "weekdays", "weekend", "mon", "tue", "wed", "thu", "fri", "sat", "sun"
    ])
    has_time_window = bool(re.search(r'\d{1,2}\s*(?:to|-|am|pm)', conversation_lower))
    has_specific_time = bool(re.search(r'\d{1,2}\s*(?:am|pm)', conversation_lower))
    
    # Must have care recipient + care needs + schedule
    schedule_complete = (has_hours and has_days) or has_time_window or has_specific_time
    
    logger.info(f"[INTAKE] Complete care check: recipient={has_care_recipient}, needs={care_needs_mentioned}, schedule={schedule_complete}")
    logger.info(f"[INTAKE] Schedule details: hours={has_hours}, days={has_days}, time_window={has_time_window}, specific_time={has_specific_time}")
    
    return has_care_recipient and care_needs_mentioned and schedule_complete

def _is_client_intake_complete(session: Dict[str, Any]) -> bool:
    """
    Check if we have collected essential intake information
    """
    messages = session.get("messages", [])
    
    full_conversation = " ".join([
        msg.get("transcript", "") for msg in messages 
        if msg.get("transcript")
    ]).lower()
    
    has_caller_name = any(pattern in full_conversation for pattern in [
        "my name is", "i am", "this is", "i'm"
    ])
    
    has_care_recipient = any(pattern in full_conversation for pattern in [
        "my mom", "my mother", "my dad", "my father", "my husband", "my wife",
        "my parent", "my grandmother", "my grandfather", "for my", "care for"
    ])
    
    care_need_keywords = [
        "companionship", "medication", "housekeeping", "cooking", "meal",
        "walking", "exercise", "personal care", "assistance", "help with",
        "dementia", "alzheimer", "diabetic", "mobility", "safety"
    ]
    has_care_needs = any(keyword in full_conversation for keyword in care_need_keywords)
    
    return has_caller_name and has_care_recipient and has_care_needs

def _extract_intake_information(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key intake information from conversation
    """
    messages = session.get("messages", [])
    
    intake_info = {
        "caller_name": None,
        "care_recipient": None,
        "care_needs": [],
        "schedule_preference": None,
        "contact_phone": None
    }
    
    for msg in messages:
        transcript = msg.get("transcript", "").lower()
        
        # Extract caller name
        if not intake_info["caller_name"]:
            name_patterns = [
                r"my name is ([a-z\s]+)",
                r"i am ([a-z\s]+)",
                r"this is ([a-z\s]+)"
            ]
            for pattern in name_patterns:
                match = re.search(pattern, transcript)
                if match:
                    intake_info["caller_name"] = match.group(1).strip().title()
                    break
        
        # Extract care recipient
        if not intake_info["care_recipient"]:
            recipient_patterns = [
                "my mom", "my mother", "my dad", "my father", 
                "my husband", "my wife", "my parent"
            ]
            for pattern in recipient_patterns:
                if pattern in transcript:
                    intake_info["care_recipient"] = pattern.replace("my ", "").title()
                    break
        
        # Extract care needs
        care_mappings = {
            "companionship": ["companionship", "company", "conversation"],
            "medication_reminders": ["medication", "medicine", "pills", "remind"],
            "light_housekeeping": ["housekeeping", "cleaning"],
            "meal_preparation": ["meal", "cooking", "food"],
            "walking_support": ["walking", "walk", "exercise"],
        }
        
        for need_type, keywords in care_mappings.items():
            if need_type not in intake_info["care_needs"]:
                if any(keyword in transcript for keyword in keywords):
                    intake_info["care_needs"].append(need_type)
        
        # Extract phone number
        if not intake_info["contact_phone"]:
            phone_match = re.search(r'\b(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{4})\b', transcript)
            if phone_match:
                intake_info["contact_phone"] = f"{phone_match.group(1)}-{phone_match.group(2)}-{phone_match.group(3)}"
        
        # Extract schedule
        if "hour" in transcript and "week" in transcript:
            hours_match = re.search(r'(\d+)\s*hours?\s*(?:per\s*)?week', transcript)
            if hours_match:
                intake_info["schedule_preference"] = f"{hours_match.group(1)} hours per week"
    
    return intake_info

def _create_intake_completion_response(intake_info: Dict[str, Any], language: str) -> Dict[str, Any]:
    """
    Create response when intake is complete
    """
    caller_name = intake_info.get("caller_name", "")
    care_recipient = intake_info.get("care_recipient", "someone")
    care_needs = intake_info.get("care_needs", [])
    contact_phone = intake_info.get("contact_phone")
    
    care_summary = ", ".join(care_needs) if care_needs else "general care assistance"
    
    if language == "es":
        if caller_name and contact_phone:
            ai_response = f"Perfecto, {caller_name}. Tengo toda la información sobre el cuidado para su {care_recipient}, incluyendo {care_summary}. Nuestro equipo de admisiones se comunicará con usted al {contact_phone} dentro de las próximas 24 horas. ¿Hay algo más que le gustaría agregar?"
        elif caller_name:
            ai_response = f"Excelente, {caller_name}. Tengo la información sobre el cuidado para su {care_recipient}. ¿Podría proporcionarme su mejor número de teléfono?"
        else:
            ai_response = f"Tengo la información sobre las necesidades de cuidado. ¿Podría darme su nombre y número de teléfono para el seguimiento?"
        
        ai_response_translated = "I have all the information. Our intake team will contact you within 24 hours."
    else:
        if caller_name and contact_phone:
            ai_response = f"Perfect, {caller_name}. I have all the information about care for your {care_recipient}, including {care_summary}. Our intake team will contact you at {contact_phone} within the next 24 hours. Is there anything else you'd like to add?"
        elif caller_name:
            ai_response = f"Excellent, {caller_name}. I have the information about care for your {care_recipient}. Could you provide your best phone number?"
        else:
            ai_response = "I have the care information. Could you give me your name and phone number for follow-up?"
        
        ai_response_translated = ai_response
    
    return {
        "original_text": "[Intake Complete]",
        "translated_text": "[Intake Complete]", 
        "detected_language": language,
        "intent": "intake_complete",
        "urgent": False,
        "ai_response": ai_response,
        "ai_response_translated": ai_response_translated,
        "intake_complete": True,
        "intake_info": intake_info
    }

def _create_admin_handoff_response(transcript: str, language: str, context_messages: List[dict]) -> Dict[str, Any]:
    """
    Create response for admin handoff with full context awareness
    """
    # Extract phone number if provided
    phone_match = re.search(r'\b(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{4})\b', transcript)
    phone_number = f"{phone_match.group(1)}-{phone_match.group(2)}-{phone_match.group(3)}" if phone_match else None
    
    # Extract name if provided
    name_match = re.search(r'\b(?:my\s+name\s+is|this\s+is|i\s+am)\s+([A-Za-z][A-Za-z\s\-\'\.]{1,20})', transcript, re.IGNORECASE)
    caller_name = name_match.group(1).strip().title() if name_match else None
    
    # Check conversation context for job application vs client care
    all_conversation = " ".join([msg.get("content", "") for msg in context_messages[-10:]])
    conversation_lower = all_conversation.lower()
    
    is_job_application = any(phrase in conversation_lower for phrase in [
        "job application", "applied for", "caregiver job", "hiring", "application status",
        "follow up on my application", "i applied"
    ])
    
    # Extract care context details
    care_context = _extract_care_context_from_conversation(context_messages)
    logger.info(f"[HANDOFF] Care context extracted: '{care_context}'")
    
    # DIFFERENT RESPONSES FOR JOB APPLICATION vs CLIENT CARE
    if is_job_application:
        return _create_job_application_handoff_response(transcript, language, phone_number, caller_name)
    
    # CLIENT CARE HANDOFF
    if language == "es":
        if phone_number and caller_name:
            if care_context:
                ai_response = f"Perfecto, {caller_name}. Tengo su número {phone_number} y toda la información: {care_context}. Voy a pasar esto a nuestro equipo de admisiones quien se comunicará con usted dentro de las próximas 24 horas. ¿Algo más en lo que pueda ayudarle?"
            else:
                ai_response = f"Excelente, {caller_name}. Tengo su número {phone_number}. Voy a transferir esta información a nuestro equipo de admisiones. ¿Hay algo más en lo que pueda ayudarle?"
        elif phone_number:
            if care_context:
                ai_response = f"Perfecto, tengo su número {phone_number} y todos los detalles: {care_context}. Voy a transferir esta información a nuestro equipo de admisiones quien se pondrá en contacto dentro de las próximas 24 horas. ¿Hay algo más?"
            else:
                ai_response = f"Perfecto, tengo su número {phone_number}. Voy a transferir esto a nuestro equipo de admisiones. ¿Hay algo más?"
        else:
            # NO CONTACT INFO - Ask for it with context
            if care_context:
                ai_response = f"¡Perfecto! Tengo toda la información: {care_context}. Para organizar esto con nuestro equipo de admisiones, necesito su nombre y mejor número de teléfono."
                logger.info(f"[HANDOFF] Using care context in Spanish response: {care_context}")
            else:
                ai_response = "Entiendo que le gustaría programar el cuidado. Para que nuestro equipo se comunique, ¿podría darme su nombre y número de teléfono?"
        
        ai_response_translated = ai_response.replace("Perfecto", "Perfect").replace("Excelente", "Excellent")
    else:
        if phone_number and caller_name:
            if care_context:
                ai_response = f"Perfect, {caller_name}! I have your number as {phone_number} and all the details: {care_context}. I'm passing this to our intake team who will contact you within 24 hours. Anything else I can help with?"
            else:
                ai_response = f"Excellent, {caller_name}! I have your number as {phone_number}. I'm forwarding this to our intake team. Is there anything else?"
        elif phone_number:
            if care_context:
                ai_response = f"Perfect! I have your number as {phone_number} and all the details: {care_context}. I'm forwarding this to our intake team who will contact you within 24 hours. Anything else?"
            else:
                ai_response = f"Perfect! I have your number as {phone_number}. I'm forwarding this to our intake team. Is there anything else?"
        else:
            # NO CONTACT INFO - Ask for it with context
            if care_context:
                ai_response = f"Perfect! I have all the information: {care_context}. To get this set up with our intake team, I'll need your name and best phone number so they can contact you within 24 hours."
                logger.info(f"[HANDOFF] Using care context in English response: {care_context}")
            else:
                ai_response = "I understand you'd like to schedule care. To have our intake team contact you, could you give me your name and phone number?"
        
        ai_response_translated = ai_response
    
    return {
        "original_text": transcript,
        "translated_text": transcript,
        "detected_language": language,
        "intent": "admin_handoff",
        "urgent": False,
        "ai_response": ai_response,
        "ai_response_translated": ai_response_translated,
        "admin_handoff_triggered": True,
        "contact_phone": phone_number,
        "contact_name": caller_name,
        "care_context": care_context
    }

def _create_job_application_handoff_response(transcript: str, language: str, phone_number: str, caller_name: str) -> Dict[str, Any]:
    """
    Create handoff response for job applications
    """
    if language == "es":
        if phone_number and caller_name:
            ai_response = f"Gracias, {caller_name}. Tengo su número {phone_number}. Voy a comunicar esto a nuestro equipo de contratación quien se pondrá en contacto dentro de 1-2 días hábiles. ¿Hay algo más?"
        elif phone_number:
            ai_response = f"Gracias. Tengo su número {phone_number}. Nuestro equipo de contratación le llamará dentro de 1-2 días hábiles. ¿Algo más?"
        elif caller_name:
            ai_response = f"Gracias, {caller_name}. ¿Podría darme su mejor número de teléfono?"
        else:
            ai_response = "Para conectarlo con nuestro equipo de contratación, ¿podría darme su nombre y número de teléfono?"
        
        ai_response_translated = "Thank you. I'll forward this to our hiring team who will contact you within 1-2 business days."
    else:
        if phone_number and caller_name:
            ai_response = f"Thank you, {caller_name}. I have your number as {phone_number}. I'm forwarding this to our hiring team who will reach out within 1-2 business days. Anything else?"
        elif phone_number:
            ai_response = f"Thank you. I have your number as {phone_number}. Our hiring team will call within 1-2 business days. Anything else?"
        elif caller_name:
            ai_response = f"Thank you, {caller_name}. Could you provide your best phone number?"
        else:
            ai_response = "To connect you with our hiring team, could you give me your name and phone number?"
        
        ai_response_translated = ai_response
    
    return {
        "original_text": transcript,
        "translated_text": transcript,
        "detected_language": language,
        "intent": "job_application_followup",
        "urgent": False,
        "ai_response": ai_response,
        "ai_response_translated": ai_response_translated,
        "admin_handoff_triggered": True,
        "handoff_type": "hiring",
        "contact_phone": phone_number,
        "contact_name": caller_name
    }

def _extract_care_context_from_conversation(context_messages: List[dict]) -> str:
    """
    Extract and summarize care details from conversation
    """
    # Increase from 10 to 16 to capture more history
    all_conversation = " ".join([msg.get("content", "") for msg in context_messages[-16:]])
    conversation_lower = all_conversation.lower()
    
    logger.info(f"[CONTEXT] Extracting care context from: {conversation_lower[:200]}...")
    
    context_parts = []
    
    # Extract care recipient
    if "my mom" in conversation_lower or "my mother" in conversation_lower:
        context_parts.append("care for your mom")
        logger.info("[CONTEXT] Found: care for your mom")
    elif "my dad" in conversation_lower or "my father" in conversation_lower:
        context_parts.append("care for your dad")
        logger.info("[CONTEXT] Found: care for your dad")
    
    # Extract care needs
    needs = []
    if "companionship" in conversation_lower:
        needs.append("companionship")
        logger.info("[CONTEXT] Found need: companionship")
    if "medication" in conversation_lower and "remind" in conversation_lower:
        needs.append("medication reminders")
        logger.info("[CONTEXT] Found need: medication reminders")
    if needs:
        context_parts.append(" and ".join(needs))
    
    # Extract schedule - IMPROVED REGEX
    # Match: "20 hours a week", "20 hours per week", "20 hrs/week", etc.
    hours_match = re.search(r'(\d+)\s*(?:hours?|hrs?)\s*(?:a|per|/)\s*week', conversation_lower)
    if hours_match:
        context_parts.append(f"{hours_match.group(1)} hours per week")
        logger.info(f"[CONTEXT] Found schedule: {hours_match.group(1)} hours per week")
    
    # Extract days
    if "monday" in conversation_lower and "friday" in conversation_lower:
        context_parts.append("Monday through Friday")
        logger.info("[CONTEXT] Found days: Monday through Friday")
    elif "weekday" in conversation_lower:
        context_parts.append("weekdays")
        logger.info("[CONTEXT] Found days: weekdays")
    
    # Extract time window - IMPROVED REGEX
    # Match: "8 am to 12 pm", "8am to 12pm", "8 to 12pm", "8-12pm"
    time_match = re.search(r'(\d{1,2})\s*(?:am|a\.m\.)?\s*(?:to|-|–)\s*(\d{1,2})\s*(?:am|pm|p\.m\.)', conversation_lower)
    if time_match:
        time_str = f"{time_match.group(1)}am to {time_match.group(2)}{time_match.group(3) if len(time_match.groups()) > 2 else 'pm'}"
        context_parts.append(time_str)
        logger.info(f"[CONTEXT] Found time: {time_str}")
    
    result = ", ".join(context_parts) if context_parts else ""
    logger.info(f"[CONTEXT] Final care context: '{result}'")
    
    return result

def _enhance_response_naturalness(result: Dict[str, Any], 
                                 user_input: str, 
                                 language: str,
                                 context: List[dict]) -> Dict[str, Any]:
    """Post-process response for naturalness"""
    
    response = result.get("ai_response", "")
    
    # Remove overly formal patterns
    response = response.replace("Perfect - ", "")
    response = response.replace("Perfect. ", "")
    response = re.sub(r"Got it[\-—]\s*", "", response)
    response = re.sub(r"Entendido[\-—]\s*", "", response)
    
    # Check for inappropriate repetition
    if context and len(context) >= 6:
        earlier_ai_responses = []
        for i in range(len(context)):
            if context[i].get("role") == "ai" and i < len(context) - 4:
                earlier_ai_responses.append(context[i].get("content", ""))
        
        for earlier_response in earlier_ai_responses:
            if response.strip() == earlier_response.strip():
                logger.warning(f"[WARNING] Detected repetition of earlier response")
                if language == "es":
                    response = "Gracias. ¿Hay algo más en lo que pueda ayudarle hoy?"
                else:
                    response = "Thank you. Is there anything else I can help you with today?"
                break
    
    # Add natural acknowledgments
    user_lower = user_input.lower()
    
    if any(word in user_lower for word in ["worried", "concerned", "scared"]):
        if language == "es":
            response = "Entiendo su preocupación. " + response
        else:
            response = "I understand your concern. " + response
    elif any(word in user_lower for word in ["thank", "appreciate"]):
        if language == "es":
            response = "De nada, es un placer ayudarle. " + response  
        else:
            response = "You're very welcome. " + response
    
    result["ai_response"] = response.strip()
    
    if language == "es":
        result["ai_response_translated"] = response
    else:
        result["ai_response_translated"] = response
    
    return result

# ---------- Helper functions ----------

def _determine_language(session: Dict[str, Any], transcript: str, stt_hint: str) -> str:
    """Determine conversation language"""
    transcript_lower = transcript.lower()
    if any(phrase in transcript_lower for phrase in ["english please", "speak english"]):
        return "en"
    if any(phrase in transcript_lower for phrase in ["español por favor", "en español"]):
        return "es"
    
    existing_pref = session.get("preferred_language")
    if existing_pref:
        return existing_pref
    
    return "es" if stt_hint == "es" else "en"

def _build_context_messages(messages: List[Dict[str, Any]]) -> List[dict]:
    """Build OpenAI-style context from conversation history"""
    context = []
    
    for msg in messages[-16:]:
        transcript = msg.get("transcript", "").strip()
        ai_response = msg.get("ai_response", "").strip()
        
        if transcript and ai_response:
            if msg.get("intent") not in ["system_error", "backchannel"]:
                context.append({"role": "user", "content": transcript})
                context.append({"role": "assistant", "content": ai_response})  # ✅ Fixed: "assistant" not "ai"
    
    if len(context) > 0:
        logger.info(f"[CONTEXT] Built with {len(context)} messages")
    
    return context

def _is_goodbye(text: str) -> bool:
    """Check if user is ending the conversation"""
    text_lower = text.lower().strip()
    
    goodbye_phrases = [
        "goodbye", "good bye", "bye", "bye bye", "see you later", "talk to you later",
        "that's all", "that's it", "that is all", "nothing else", "all set", "all good",
        "thank you that's all", "thanks that's all", "thank you so much", "thanks so much",
        "not that i know of", "nothing that i know of", "no that's it", "no thanks",
        "have a good day", "have a great day", "take care",
        "i'll wait for your call", "call me back", "talk to you soon",
        "adiós", "hasta luego", "gracias", "eso es todo", "nada más"
    ]
    
    if any(phrase in text_lower for phrase in goodbye_phrases):
        return True
        
    if text_lower in ["thank you", "thanks", "gracias"] and len(text.split()) <= 2:
        return True
        
    return False

async def _handle_goodbye(session_id: str, session: Dict[str, Any], transcript: str, language: str) -> Tuple[str, Dict[str, Any]]:
    """Handle conversation closure"""
    
    transcript_lower = transcript.lower().strip()
    messages = session.get("messages", [])
    has_shared_info = any(msg.get("intent") in ["inquiry", "scheduling"] for msg in messages)
    
    if language == "es":
        if any(phrase in transcript_lower for phrase in ["gracias", "muchas gracias"]):
            if has_shared_info:
                ai_response = "¡De nada! Nuestro equipo se comunicará pronto para organizar todo. ¡Que tenga un buen día!"
            else:
                ai_response = "¡De nada! Estamos aquí para cuando nos necesite. ¡Que tenga un buen día!"
        else:
            if has_shared_info:
                ai_response = "¡Gracias por llamarnos! Nuestro equipo se comunicará muy pronto. ¡Que tenga un buen día!"
            else:
                ai_response = "¡Gracias por llamarnos! Estamos aquí cuando necesite apoyo. ¡Que tenga un buen día!"
        
        ai_response_translated = "Thank you for calling! Have a great day!"
    else:
        if any(phrase in transcript_lower for phrase in ["thank you", "thanks"]):
            if has_shared_info:
                ai_response = "You're very welcome! Our team will follow up with you soon. Have a wonderful day!"
            else:
                ai_response = "You're very welcome! We're here whenever you need us. Have a great day!"
        else:
            if has_shared_info:
                ai_response = "Thank you for calling! Our team will be in touch soon. Have a wonderful day!"
            else:
                ai_response = "Thank you for calling! We're here whenever you need support. Have a great day!"
        
        ai_response_translated = ai_response
    
    entry = _create_message_entry(
        session_id=session_id,
        transcript=transcript,
        result={
            "original_text": transcript,
            "translated_text": transcript,
            "detected_language": language,
            "intent": "polite_closure",
            "urgent": False,
            "ai_response": ai_response,
            "ai_response_translated": ai_response_translated
        },
        language=language
    )
    
    try:
        conversation_manager.add_message(session_id, entry)
        conversation_manager.mark_closed(session_id, analysis=None)
        # Note: flush_to_supabase is handled by the calling function (e.g., mock_conversation)
        # which has access to the required company_id, office_id, phone_number_id
        entry["session_closed"] = True
    except Exception as e:
        logger.error(f"Error closing session: {e}")
    
    return session_id, entry

def _create_message_entry(session_id: str, 
                         transcript: str, 
                         result: Dict[str, Any], 
                         language: str) -> Dict[str, Any]:
    """Create standardized message entry"""
    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "transcript": transcript,
        "translated_text": result.get("translated_text", transcript),
        "intent": result.get("intent", "inquiry"),
        "ai_response": result.get("ai_response", "I'm here to help. How can I assist you?"),
        "ai_response_translated": result.get("ai_response_translated", result.get("ai_response", "I'm here to help. How can I assist you?")),
        "urgent": bool(result.get("urgent", False)),
        "language": language,
        "is_final": True,
        "timestamp": datetime.utcnow().isoformat(),
    }

def _fallback_response(transcript: str, language: str) -> Dict[str, Any]:
    """Fallback response when AI fails"""
    if language == "es":
        response = "Disculpe, ¿podría repetir eso? Quiero asegurarme de entender cómo puedo ayudarle."
        translated = "I'm sorry, could you repeat that? I want to make sure I understand how I can help you."
    else:
        response = "I'm sorry, could you repeat that? I want to make sure I understand how I can help you."
        translated = response
    
    return {
        "original_text": transcript,
        "translated_text": transcript,
        "detected_language": language,
        "intent": "clarification_needed",
        "urgent": False,
        "ai_response": response,
        "ai_response_translated": translated
    }

# ---------- Compatibility wrappers ----------

async def on_transcript(event_or_session_id=None, transcript: Optional[str] = None, stt_lang_hint: str = "en", **kwargs):
    """Compatibility wrapper for existing callers"""
    if isinstance(event_or_session_id, dict):
        payload = event_or_session_id
        session_id = payload.get("session_id") or payload.get("sessionId")
        txt = payload.get("transcript") or payload.get("text") or payload.get("message") or ""
        lang = payload.get("stt_lang_hint") or payload.get("language") or stt_lang_hint or "en"
        if session_id:
            return await process_final_transcript(session_id, txt, lang)
        return await process_final_transcript(txt, stt_lang_hint=lang)
    
    if transcript is None:
        return await process_final_transcript(event_or_session_id, stt_lang_hint=stt_lang_hint or "en")
    else:
        return await process_final_transcript(event_or_session_id, transcript, stt_lang_hint or "en")

async def on_error(event_or_session_id=None, error: Exception | str | None = None, **kwargs):
    """Compatibility wrapper for error handling"""
    if isinstance(event_or_session_id, dict):
        payload = event_or_session_id
        session_id = payload.get("session_id") or payload.get("sessionId")
        err = payload.get("error") or error
    else:
        session_id = event_or_session_id
        err = error
    
    logger.error(f"[transcript_service.on_error] session={session_id} error={err}")
    return {"ok": True, "message": "Error logged"}

# async def end_active_session(session_id: Optional[str] = None, caller_id: Optional[str] = None) -> dict:
#     """End active session and commit to database"""
#     try:
#         if session_id:
#             if session_id not in conversation_manager.sessions:
#                 return {"ok": False, "error": f"Unknown session_id: {session_id}"}
#             conversation_manager.mark_closed(session_id, analysis=None)


#                         # ✅ Persist conversation + messages to Supabase on goodbye
#             from app.db.supabase import supabase

#             sess = conversation_manager.sessions.get(session_id, {})
#             company_id = sess.get("company_id")
#             office_id = sess.get("office_id")
#             phone_number_id = sess.get("phone_number_id")

#             if company_id and office_id and phone_number_id:
#                 conversation_manager.flush_to_supabase(
#                     supabase,
#                     session_id,
#                     company_id=company_id,
#                     office_id=office_id,
#                     phone_number_id=phone_number_id,
#                     caller_id="live_audio"
#                 )
#                 logger.info(f"💾 Flushed live session {session_id} to Supabase after goodbye.")
#             else:
#                 logger.warning(f"⚠️ Skipped Supabase flush for session {session_id} — missing IDs.")

#             # Note: flush_to_supabase requires company_id, office_id, phone_number_id
#             # These should be provided by the calling function that has access to phone resolution
#             logger.warning(f"Session {session_id} marked as closed but not flushed to Supabase (missing required IDs)")
#             return {"ok": True, "ended": [session_id]}

#         # End all active sessions
#         active_ids = conversation_manager.get_active_session_ids()
#         ended = []
#         for sid in active_ids:
#             conversation_manager.mark_closed(sid, analysis=None)
#             # Note: flush_to_supabase requires company_id, office_id, phone_number_id
#             # These should be provided by the calling function that has access to phone resolution
#             logger.warning(f"Session {sid} marked as closed but not flushed to Supabase (missing required IDs)")
#             ended.append(sid)
        
#         return {"ok": True, "ended": ended}
        
#     except Exception as e:
#         logger.error(f"[transcript_service.end_active_session] {e}")
#         return {"ok": False, "error": str(e)}
async def end_active_session(session_id: Optional[str] = None, caller_id: Optional[str] = None) -> dict:
    """End active session and commit to database."""
    try:
        if session_id:
            if session_id not in conversation_manager.sessions:
                return {"ok": False, "error": f"Unknown session_id: {session_id}"}

            # Mark closed in memory
            conversation_manager.mark_closed(session_id, analysis=None)

            # ✅ Persist conversation + messages to Supabase
            from app.db.supabase import supabase

            sess = conversation_manager.sessions.get(session_id, {})
            company_id = sess.get("company_id")
            office_id = sess.get("office_id")
            phone_number_id = sess.get("phone_number_id")

            if company_id and office_id and phone_number_id:
                conversation_manager.flush_to_supabase(
                    supabase,
                    session_id,
                    company_id=company_id,
                    office_id=office_id,
                    phone_number_id=phone_number_id,
                    caller_id=caller_id or "live_audio"
                )
                logger.info(f"💾 Flushed live session {session_id} to Supabase (via end_active_session).")
            else:
                logger.warning(
                    f"⚠️ Session {session_id} closed but not flushed — missing company_id/office_id/phone_number_id."
                )

            return {"ok": True, "ended": [session_id]}

        # If no session_id passed → close all active sessions
        active_ids = conversation_manager.get_active_session_ids()
        ended = []
        for sid in active_ids:
            conversation_manager.mark_closed(sid, analysis=None)

            sess = conversation_manager.sessions.get(sid, {})
            company_id = sess.get("company_id")
            office_id = sess.get("office_id")
            phone_number_id = sess.get("phone_number_id")

            if company_id and office_id and phone_number_id:
                conversation_manager.flush_to_supabase(
                    supabase,
                    sid,
                    company_id=company_id,
                    office_id=office_id,
                    phone_number_id=phone_number_id,
                    caller_id=caller_id or "live_audio"
                )
                logger.info(f"💾 Flushed session {sid} to Supabase (bulk close).")
            else:
                logger.warning(
                    f"⚠️ Session {sid} closed but not flushed — missing company_id/office_id/phone_number_id."
                )

            ended.append(sid)

        return {"ok": True, "ended": ended}

    except Exception as e:
        logger.error(f"[transcript_service.end_active_session] ❌ {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
