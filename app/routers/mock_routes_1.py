from collections import Counter
from datetime import datetime
import os
from typing import Optional
from fastapi import APIRouter, Request, Response
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents, SpeakOptions
import io
import uuid

from fastapi.responses import FileResponse


from app.models.mock_response import MOCK_RESPONSES
from app.models.mock_stt import mock_stt
from app.services.groq_client import groq_client
from app.core.connection_manager import manager
from app.models.mock_stt import mock_stt
from app.services.transcript_service import process_final_transcript
from app.services.conversation_manager import conversation_manager
from app.core.config import DEEPGRAM_API_KEY, logger
from app.utils.parsers import extract_name, extract_phone


router = APIRouter()
deepgram = DeepgramClient(DEEPGRAM_API_KEY)


import sounddevice as sd
import soundfile as sf
from threading import Thread

def speak_text(text: str):
    """Speak text locally on the server using Deepgram TTS + sounddevice."""
    if not text.strip():
        return

    def tts_thread():
        try:
            deepgram = DeepgramClient(DEEPGRAM_API_KEY)
            temp_file = "temp_response.wav"

            options = SpeakOptions(
                model="aura-2-janus-en",
                encoding="linear16",
                container="wav"
            )

            # Generate TTS → save to temp file
            deepgram.speak.rest.v("1").save(temp_file, {"text": text}, options)

            # Play audio locally
            data, fs = sf.read(temp_file, dtype="float32")
            sd.play(data, fs)
            sd.wait()

        except Exception as e:
            logger.error(f"TTS error: {str(e)}")
        finally:
            try:
                os.remove(temp_file)
            except:
                pass

    # Run TTS in background so API call isn't blocked
    Thread(target=tts_thread, daemon=True).start()


@router.post("/mock/groq")
async def mock_groq_endpoint(request: Request):
    body = await request.json()
    user_input = body.get("message", "").lower()
    response = MOCK_RESPONSES["default"]
    for key, mock in MOCK_RESPONSES.items():
        if key in user_input and key != "default":
            response = mock
            break
    return {
        **response,
        "translated_text": response["transcript"],
        "ai_response_translated": response["ai_response"],
        "is_final": True,
        "timestamp": datetime.now().isoformat()
    }

AUDIO_CACHE = {}   # { audio_id: bytes }


async def synthesize_audio_file(text: str, language: str = "en") -> Optional[str]:
    """Generate TTS from text, save to static folder, return audio_id."""
    if not text.strip():
        return None

    audio_id = f"{uuid.uuid4()}.wav"
    filepath = os.path.join("app/static", audio_id)

    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Choose model based on language
        model = "aura-2-estrella-es" if language == "es" else "aura-2-thalia-en"
        
        options = SpeakOptions(
            model=model,
            encoding="linear16",
            container="wav"
        )
        
        # Save audio file
        deepgram.speak.rest.v("1").save(filepath, {"text": text}, options)
        
        # Verify file was created
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"TTS file created: {filepath}, size: {os.path.getsize(filepath)} bytes")
            return audio_id
        else:
            logger.error("TTS file was not created or is empty")
            return None
            
    except Exception as e:
        logger.error(f"TTS error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

# @router.post("/mock-conversation")
# async def mock_conversation(request: Request):
#     body = await request.json()
#     user_text = body.get("text", "").strip()
#     stt_lang_hint = body.get("language", "en")  # Allow frontend to specify language
#     if not user_text:
#         return {"error": "No text provided"}

#     # Process input and generate AI response with language hint
#     session_id, entry = await process_final_transcript(user_text, stt_lang_hint=stt_lang_hint)

#     # ✅ Generate TTS audio file (use original language response, not translation)
#     audio_id = None
#     if entry.get("ai_response"):
#         # Use the detected language from the entry
#         detected_language = entry.get("language", stt_lang_hint)
#         audio_id = await synthesize_audio_file(entry["ai_response"], detected_language)
#         if audio_id:
#             entry["audio_id"] = audio_id  # ✅ Add to entry before broadcasting
#             logger.info(f"Generated audio ID: {audio_id}")

#     # ✅ Broadcast to WebSocket listeners (now includes audio_id)
#     await manager.broadcast(entry)

#     # ✅ Flag for frontend: session closed, new session will be created next time
#     new_session_available = entry.get("session_closed", False)
    
#     # ✅ If session closed (goodbye detected), flush to Supabase
#     if new_session_available:
#         try:
#             from app.services.conversation_manager import conversation_manager
#             conversation_manager.flush_to_supabase(supabase, session_id, caller_id="mock_user")
#             logger.info(f"✅ Mock conversation flushed to Supabase: {session_id}")
#         except Exception as e:
#             logger.error(f"❌ Mock conversation flush failed: {e}")
    
#     return {
#         "status": "success", 
#         "session_id": session_id,
#         "audio_id": audio_id,
#         "new_session_available": new_session_available,  # 🔑 <-- frontend can reset state if True
#         **entry
#     }

@router.post("/mock-conversation")
async def mock_conversation(request: Request):
    """
    Simulates a user message → AI response → optional TTS → save to Supabase when closed.
    Works with resolved phone number metadata to maintain company/office linkage.
    """
    body = await request.json()
    user_text = body.get("text", "").strip()
    stt_lang_hint = body.get("language", "en")
    phone_number = body.get("phone_number")  # optional: frontend can include it

    if not user_text:
        return {"error": "No text provided"}

    # 1️⃣ Run through your processing pipeline
    session_id, entry = await process_final_transcript(user_text, stt_lang_hint=stt_lang_hint)

    # 2️⃣ (Optional) Generate TTS audio file
    audio_id = None
    if entry.get("ai_response"):
        detected_language = entry.get("language", stt_lang_hint)
        audio_id = await synthesize_audio_file(entry["ai_response"], detected_language)
        if audio_id:
            entry["audio_id"] = audio_id
            logger.info(f"🎧 TTS generated for mock conversation: {audio_id}")

    # 3️⃣ Broadcast real-time update to WebSocket listeners
    await manager.broadcast(entry)

    # 4️⃣ Check if this session is finished
    new_session_available = entry.get("session_closed", False)

    # 5️⃣ If session ended, resolve phone IDs (once per session)
    if new_session_available:
        try:
            # Import here to avoid circular import
            from app.services.conversation_manager import conversation_manager

            # 🔍 Use provided phone number or fallback to a default test phone
            if not phone_number:
                phone_number = "+18702735332"  # Default test phone in your DB

            # Query the /resolve-phone equivalent logic directly here
            logger.info(f"🔍 Looking up phone number: {phone_number}")
            
            # Try exact match first
            phone_lookup = (
                supabase.table("phone_numbers")
                .select("id, company_id, office_id, e164")
                .eq("e164", phone_number)
                .execute()
            )
            
            # If no results, try different formats like the resolve_phone endpoint
            if not phone_lookup.data:
                logger.info(f"🔄 No exact match for {phone_number}, trying alternative formats...")
                
                # Try without the + prefix
                if phone_number.startswith("+"):
                    phone_without_plus = phone_number[1:]
                    logger.info(f"🔄 Trying without +: '{phone_without_plus}'")
                    phone_lookup = (
                        supabase.table("phone_numbers")
                        .select("id, company_id, office_id, e164")
                        .eq("e164", phone_without_plus)
                        .execute()
                    )
                
                # Try with + prefix if not present
                if not phone_lookup.data and not phone_number.startswith("+"):
                    phone_with_plus = f"+{phone_number}"
                    logger.info(f"🔄 Trying with +: '{phone_with_plus}'")
                    phone_lookup = (
                        supabase.table("phone_numbers")
                        .select("id, company_id, office_id, e164")
                        .eq("e164", phone_with_plus)
                        .execute()
                    )

            if not phone_lookup.data:
                logger.warning(f"⚠️ No phone match found for {phone_number} in any format, skipping Supabase flush.")
                # Let's also try to see what phone numbers are available in the database
                try:
                    sample_phones = supabase.table("phone_numbers").select("e164").limit(3).execute()
                    logger.info(f"📋 Sample phone numbers in DB: {[p['e164'] for p in sample_phones.data]}")
                except Exception as debug_e:
                    logger.error(f"Debug query failed: {debug_e}")
                
                return {
                    "status": "partial_saved",
                    "session_id": session_id,
                    "audio_id": audio_id,
                    "new_session_available": new_session_available,
                    **entry,
                }

            phone_data = phone_lookup.data[0]
            company_id = phone_data["company_id"]
            office_id = phone_data["office_id"]
            phone_number_id = phone_data["id"]

            # Validate that all required IDs are present
            if not all([company_id, office_id, phone_number_id]):
                logger.error(f"❌ Missing required IDs from phone lookup: company_id={company_id}, office_id={office_id}, phone_number_id={phone_number_id}")
                return {
                    "status": "error",
                    "session_id": session_id,
                    "audio_id": audio_id,
                    "new_session_available": new_session_available,
                    "error": "Missing required IDs from phone lookup",
                    **entry,
                }

            # 🧠 Attach IDs to in-memory session
            if session_id in conversation_manager.sessions:
                conversation_manager.sessions[session_id].update({
                    "company_id": company_id,
                    "office_id": office_id,
                    "phone_number_id": phone_number_id,
                })
                logger.info(f"✅ Attached IDs to session {session_id}: company_id={company_id}, office_id={office_id}, phone_number_id={phone_number_id}")
            else:
                logger.error(f"❌ Session {session_id} not found in conversation_manager.sessions")

            # 💾 Flush conversation and messages to Supabase
            conversation_manager.flush_to_supabase(
                supabase,
                session_id,
                company_id=company_id,
                office_id=office_id,
                phone_number_id=phone_number_id,
                caller_id="mock_user"
            )

            logger.info(f"✅ Mock conversation flushed to Supabase: {session_id}")

        except Exception as e:
            logger.error(f"❌ Error flushing mock conversation: {e}", exc_info=True)

    # 6️⃣ Return result to frontend
    return {
        "status": "success",
        "session_id": session_id,
        "audio_id": audio_id,
        "new_session_available": new_session_available,
        **entry
    }



@router.post("/tts")
async def generate_tts(request: Request):
    body = await request.json()
    text = body.get("text")
    if not text:
        return {"error": "No text provided"}

    # Use Deepgram TTS
    options = SpeakOptions(model="aura-2-thalia-en")
    buf = io.BytesIO()
    deepgram.speak.v("1").stream(buf, {"text": text}, options)
    buf.seek(0)

    return Response(content=buf.read(), media_type="audio/mpeg")

@router.get("/tts/{audio_id}")
async def get_tts_audio(audio_id: str):
    filepath = os.path.join("app/static", audio_id)
    if not os.path.exists(filepath):
        return {"error": "Audio not found"}
    return FileResponse(filepath, media_type="audio/wav")


from app.db.supabase import supabase

@router.get("/conversation-history")
async def get_conversation_history(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None
):
    try:
        query = supabase.table("conversations").select(
            "id, caller_id, start_time, end_time, status, "
            "messages!messages_session_id_fkey(id, transcript, translated_text, intent, ai_response, "
            "ai_response_translated, urgent, language, sentiment, is_final, timestamp, audio_id)"
        )


        # Filter by session
        if session_id:
            query = query.eq("id", session_id)

        # Filter by status
        if status:
            query = query.eq("status", status)

        response = query.execute()
        if not response.data:
            return {"message": "No conversations found"}

        results = {}
        # In your /conversation-history endpoint
        for conv in response.data:
            messages = conv.get("messages", [])
            
            # Generate analysis on the fly
            intents = [m.get("intent") for m in messages if m.get("intent")]
            counter = Counter(intents)
            
            analysis = {
                "summary": f"Conversation with {len(messages)} messages",
                "main_intent": counter.most_common(1)[0][0] if counter else "unknown",
                "urgent": any(m.get("urgent") for m in messages),
                "total_messages": len(messages),
                "intents_distribution": dict(counter),
                "ended_with_closure": any(m.get("intent") in ["polite_closure", "goodbye"] for m in messages),
            }
            
            results[conv["id"]] = {
                "caller_id": conv["caller_id"],
                "start_time": conv["start_time"],
                "end_time": conv["end_time"],
                "status": conv["status"],
                "analysis": analysis,  # ✅ Add this
                "messages": messages,
            }
        # for conv in response.data:
        #     messages = conv.get("messages", [])

        #     # ⏳ If "since" param is provided, filter messages
        #     if since:
        #         try:
        #             cutoff = datetime.fromisoformat(since)
        #             messages = [
        #                 m for m in messages
        #                 if datetime.fromisoformat(m["timestamp"]) > cutoff
        #             ]
        #         except Exception as e:
        #             return {"error": f"Invalid 'since' timestamp format: {e}"}

        #     results[conv["id"]] = {
        #         "caller_id": conv["caller_id"],
        #         "start_time": conv["start_time"],
        #         "end_time": conv["end_time"],
        #         "status": conv["status"],
        #         "analysis": conv.get("analysis"),
        #         "messages": messages,
        #     }

        return results

    except Exception as e:
        return {"error": str(e)}





# @router.get("/conversation-history")
# async def get_conversation_history(
#     session_id: Optional[str] = None,
#     status: Optional[str] = None,
#     since: Optional[str] = None
# ):
#     history = conversation_manager.get_history(session_id, status)

#     # ⏳ If "since" param is provided, filter messages
#     if since:
#         try:
#             cutoff = datetime.fromisoformat(since)
#             for session in history.values():
#                 session["messages"] = [
#                     msg for msg in session["messages"]
#                     if datetime.fromisoformat(msg["timestamp"]) > cutoff
#                 ]
#         except Exception as e:
#             return {"error": f"Invalid 'since' timestamp format: {e}"}

#     return history

@router.post("/reset-conversation")
async def reset_conversation():
    mock_stt.conversation_history = []
    return {"status": "success", "message": "Conversation reset"}

@router.post("/debug/parse-test")
async def debug_parse_test(request: Request):
    """Test the parser functions with sample text"""
    body = await request.json()
    text = body.get("text", "").strip()
    
    if not text:
        return {"error": "No text provided"}
    
    # Test the parser functions
    phone = extract_phone(text)
    name = extract_name(text)
    
    # Test database lookup with the extracted data
    found_applications = []
    if phone:
        # Try digits-only format
        result = supabase.table("job_applications").select("*").eq("phone_number", phone).execute()
        if result.data:
            found_applications.extend(result.data)
        else:
            # Try formatted phone
            formatted_phone = f"{phone[:3]}-{phone[3:6]}-{phone[6:]}" if phone and len(phone) == 10 else phone
            result = supabase.table("job_applications").select("*").eq("phone_number", formatted_phone).execute()
            if result.data:
                found_applications.extend(result.data)
    
    if not found_applications and name:
        result = supabase.table("job_applications").select("*").ilike("name", f"%{name}%").execute()
        if result.data:
            found_applications.extend(result.data)
    
    return {
        "input_text": text,
        "extracted_phone": phone,
        "extracted_name": name,
        "database_matches": found_applications,
        "database_match_count": len(found_applications)
    }


@router.get("/debug/job-applications")
async def debug_job_applications():
    """Debug endpoint to see what job applications are in the database"""
    try:
        result = supabase.table("job_applications").select("*").execute()
        return {
            "count": len(result.data),
            "applications": result.data
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/debug/add-test-application")
async def debug_add_test_application(request: Request):
    """Add test job application data for debugging"""
    body = await request.json()
    
    test_data = {
        "name": body.get("name", "Maria Johnson"),
        "phone_number": body.get("phone_number", "5014445566"),
        "position": body.get("position", "Nurse Assistant"),
        "status": body.get("status", "in review"),
        "last_contact": body.get("last_contact", "2024-01-15"),
        "notes": body.get("notes", "Test application for debugging")
    }
    
    try:
        result = supabase.table("job_applications").insert(test_data).execute()
        return {
            "status": "success",
            "added_application": result.data[0] if result.data else None
        }
    except Exception as e:
        return {"error": str(e)}

# Add this to your mock_routes.py

@router.post("/debug/test-job-logic")
async def test_job_application_logic(request: Request):
    """
    Comprehensive test endpoint for job application logic
    """
    body = await request.json()
    test_text = body.get("text", "").strip()
    
    if not test_text:
        return {"error": "No text provided for testing"}
    
    try:
        # Import the functions from your updated modules
        from app.utils.parsers import smart_extract_info
        from app.services.transcript_service import _is_job_application_inquiry, _handle_job_application_lookup
        
        # Test smart extraction
        extraction_result = smart_extract_info(test_text)
        
        # Test job inquiry detection
        mock_intent = {"intent": None}  # Simulate no intent from Groq
        is_job_inquiry = await _is_job_application_inquiry(test_text, mock_intent)
        
        # If it's a job inquiry, test the lookup
        job_response = None
        job_found = False
        if is_job_inquiry:
            job_response, job_found = await _handle_job_application_lookup(test_text)
        
        # Test database search directly
        from app.services.transcript_service import _search_job_applications
        phone = extraction_result.get('phone')
        name = extraction_result.get('name')
        db_results = await _search_job_applications(phone, name) if (phone or name) else []
        
        return {
            "test_input": test_text,
            "extraction_results": extraction_result,
            "is_job_inquiry": is_job_inquiry,
            "job_response": job_response,
            "job_found": job_found,
            "database_search": {
                "query_phone": phone,
                "query_name": name,
                "results_count": len(db_results),
                "results": db_results[:3]  # Limit to first 3 results
            },
            "recommendations": _generate_test_recommendations(extraction_result, is_job_inquiry, db_results)
        }
        
    except Exception as e:
        logger.error(f"Test endpoint error: {e}")
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "test_input": test_text
        }


def _generate_test_recommendations(extraction_result, is_job_inquiry, db_results):
    """
    Generate recommendations based on test results
    """
    recommendations = []
    
    phone = extraction_result.get('phone')
    name = extraction_result.get('name')
    confidence = extraction_result.get('confidence', {})
    
    # Phone extraction recommendations
    if confidence.get('has_phone', 0) > 0 and not phone:
        recommendations.append("Phone number detected but not extracted properly - check regex patterns")
    elif phone and len(phone) != 10:
        recommendations.append(f"Extracted phone '{phone}' is not 10 digits - validation needed")
    
    # Name extraction recommendations
    if confidence.get('has_name', 0) > 0.5 and not name:
        recommendations.append("Name likely present but not extracted - improve name patterns")
    
    # Job inquiry recommendations
    if confidence.get('is_job_inquiry', 0) > 0.5 and not is_job_inquiry:
        recommendations.append("Text seems job-related but not detected as job inquiry")
    elif is_job_inquiry and confidence.get('is_job_inquiry', 0) < 0.3:
        recommendations.append("Detected as job inquiry with low keyword confidence")
    
    # Database recommendations
    if (phone or name) and not db_results:
        recommendations.append("No database matches found - consider adding test data")
    elif db_results and not is_job_inquiry:
        recommendations.append("Found database matches but query not classified as job inquiry")
    
    if not recommendations:
        recommendations.append("All tests passed - logic is working correctly!")
    
    return recommendations


@router.post("/debug/simulate-conversation")
async def simulate_full_conversation(request: Request):
    """
    Simulate a full conversation flow with job application logic
    """
    body = await request.json()
    messages = body.get("messages", [])
    
    if not messages:
        return {"error": "No messages provided"}
    
    results = []
    
    for i, message in enumerate(messages):
        try:
            # Process each message through the full pipeline
            session_id, entry = await process_final_transcript(message, f"test_caller_{i}")
            
            results.append({
                "message_index": i,
                "input": message,
                "session_id": session_id,
                "output": entry,
                "intent_detected": entry.get("intent"),
                "job_inquiry": entry.get("metadata", {}).get("job_application_inquiry", False),
                "job_found": entry.get("metadata", {}).get("job_application_found", False)
            })
            
        except Exception as e:
            results.append({
                "message_index": i,
                "input": message,
                "error": str(e)
            })
    
    return {
        "conversation_simulation": results,
        "summary": {
            "total_messages": len(messages),
            "successful_processing": len([r for r in results if "error" not in r]),
            "job_inquiries_detected": len([r for r in results if r.get("job_inquiry", False)]),
            "applications_found": len([r for r in results if r.get("job_found", False)])
        }
    }

async def _synthesize_to_static(text: str) -> Optional[str]:
    if not text or not text.strip():
        return None
    try:
        from deepgram import DeepgramClient
        from app.core.config import DEEPGRAM_API_KEY
        dg = DeepgramClient(DEEPGRAM_API_KEY)
        audio_id = f"{uuid.uuid4()}.wav"
        path = os.path.join("app/static", audio_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        opts = SpeakOptions(model="aura-2-thalia-en", encoding="linear16", container="wav")
        dg.speak.rest.v("1").save(path, {"text": text}, opts)
        return audio_id if os.path.exists(path) and os.path.getsize(path) > 0 else None
    except Exception as e:
        logger.error(f"TTS error (mock stream): {e}")
        return None

@router.post("/mock/stream")
async def mock_stream(request: Request):
    """
    Simulate streaming:
      - Send partials with is_final=False (broadcast only)
      - Send final with is_final=True (runs full pipeline + broadcasts LLM/DB/tts result)
    Body:
      { "text": "...", "is_final": true|false, "stt_lang_hint": "en"|"es" }
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    is_final = bool(body.get("is_final", False))
    stt_lang_hint = body.get("stt_lang_hint", "en")

    if not text:
        return {"error": "no text"}

    # 1) always broadcast what the UI expects from the stream
    stream_payload = {
        "type": "transcript",
        "transcript": text,
        "is_final": is_final,
        "timestamp": datetime.now().isoformat()
    }
    await manager.broadcast(stream_payload)

    # 2) if final, run the full pipeline (Groq + optional job lookup + TTS)
    if is_final:
        session_id, entry = await process_final_transcript(text, stt_lang_hint=stt_lang_hint)

        # TTS for the AI response (attach audio_id like live)
        if entry.get("ai_response_translated"):
            audio_id = await _synthesize_to_static(entry["ai_response_translated"])
            if audio_id:
                entry["audio_id"] = audio_id

        # broadcast the final structured message (what your UI renders)
        await manager.broadcast(entry)

        return {"status": "final_broadcasted", "session_id": session_id, **entry}

    # 3) partial only
    return {"status": "partial_broadcasted"}

@router.post("/test/first-turn-inquiry")
async def test_first_turn_inquiry(request: Request):
    """Test endpoint for first-turn inquiry responses."""
    body = await request.json()
    text = body.get("text", "")
    language = body.get("language", "en")
    
    if not text:
        return {"error": "No text provided"}
    
    # Clear any existing conversation history to simulate first turn
    conversation_manager.sessions.clear()
    
    # Process the transcript
    session_id, entry = await process_final_transcript(text, stt_lang_hint=language)
    
    return {
        "session_id": session_id,
        "entry": entry,
        "is_first_turn": len(conversation_manager.sessions.get(session_id, {}).get("messages", [])) == 1,
        "message": "First-turn inquiry test completed"
    }

@router.post("/test/conversation-flow")
async def test_conversation_flow(request: Request):
    """Test endpoint for enhanced conversation flow with slot-filling memory."""
    body = await request.json()
    messages = body.get("messages", [])
    language = body.get("language", "en")
    
    if not messages:
        return {"error": "No messages provided"}
    
    # Clear any existing conversation history
    conversation_manager.sessions.clear()
    
    results = []
    session_id = None
    
    for i, message in enumerate(messages):
        text = message.get("text", "")
        if not text:
            continue
            
        # Process each message
        session_id, entry = await process_final_transcript(text, stt_lang_hint=language)
        
        # Get conversation context after each message
        context = conversation_manager.sessions.get(session_id, {}).get("conversation_context", {})
        
        results.append({
            "message_number": i + 1,
            "user_input": text,
            "ai_response": entry.get("ai_response", ""),
            "intent": entry.get("intent", ""),
            "conversation_context": context,
            "is_greeting_only": entry.get("is_greeting_only", False),
            "is_first_turn": entry.get("is_first_turn", False),
            "is_continuation": entry.get("is_continuation", False)
        })
    
    return {
        "session_id": session_id,
        "conversation_flow": results,
        "final_context": conversation_manager.sessions.get(session_id, {}).get("conversation_context", {}),
        "message": "Conversation flow test completed"
    }

@router.post("/test/debug-conversation")
async def test_debug_conversation(request: Request):
    """Test endpoint to debug the exact conversation from the user's example."""
    # Clear any existing conversation history
    conversation_manager.sessions.clear()
    
    # Simulate the exact conversation
    conversation = [
        "Hello good evening how are you doing",
        "I would like to know more about your caregiving services because I am very new to this",
        "can you discuss it though while waiting for the team?",
        "My mom has diabetes, and she needs constant medication reminders also, I would like her to keep walking or just having someone to talk to her",
        "ok, awesome, I need to talk or speak with your team then on what caregiver option is appropriate",
        "20 hours and during mornings"
    ]
    
    results = []
    session_id = None
    
    for i, text in enumerate(conversation):
        # Process each message
        session_id, entry = await process_final_transcript(text, stt_lang_hint="en")
        
        # Get conversation context after each message
        context = conversation_manager.sessions.get(session_id, {}).get("conversation_context", {})
        
        results.append({
            "message_number": i + 1,
            "user_input": text,
            "ai_response": entry.get("ai_response", ""),
            "intent": entry.get("intent", ""),
            "urgent": entry.get("urgent", False),
            "conversation_context": context
        })
    
    # Get final context safely
    final_context = {}
    if session_id and session_id in conversation_manager.sessions:
        final_context = conversation_manager.sessions[session_id].get("conversation_context", {})
    
    return {
        "session_id": session_id,
        "conversation_flow": results,
        "final_context": final_context,
        "message": "Debug conversation test completed"
    }


@router.post("/test/simple")
async def test_simple(request: Request):
    """Simple test endpoint to verify basic functionality."""
    try:
        # Clear any existing conversation history
        conversation_manager.sessions.clear()
        
        # Test a simple message
        session_id, entry = await process_final_transcript("Hello, I need help with my father who has dementia", stt_lang_hint="en")
        
        return {
            "success": True,
            "session_id": session_id,
            "entry": entry,
            "message": "Simple test completed successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Simple test failed"
        }
@router.post("/resolve-phone")
async def resolve_phone(request: Request):
    """
    Given a phone number, return the associated company_id, office_id, phone_number_id.
    This simulates what happens when a call comes in.
    """
    body = await request.json()
    phone = body.get("phone_number")
    
    if not phone:
        return {"error": "No phone number provided"}
    
    try:
        print(f"🔍 Searching for phone: '{phone}' (type: {type(phone)}, length: {len(phone)})")
        
        # Try exact match first
        result = supabase.table("phone_numbers").select(
            "id, company_id, office_id, e164"
        ).eq("e164", phone).execute()
        
        print(f"📊 Query result: {result.data}")
        print(f"📊 Result count: {len(result.data) if result.data else 0}")
        
        # If no results, let's check what's actually in the database
        if not result.data:
            all_phones = supabase.table("phone_numbers").select("e164").limit(5).execute()
            print(f"📋 Sample phones in DB: {all_phones.data}")
            
            # Try without the + prefix
            if phone.startswith("+"):
                phone_without_plus = phone[1:]
                print(f"🔄 Trying without +: '{phone_without_plus}'")
                result = supabase.table("phone_numbers").select(
                    "id, company_id, office_id, e164"
                ).eq("e164", phone_without_plus).execute()
            
            # Try with + prefix if not present
            if not result.data and not phone.startswith("+"):
                phone_with_plus = f"+{phone}"
                print(f"🔄 Trying with +: '{phone_with_plus}'")
                result = supabase.table("phone_numbers").select(
                    "id, company_id, office_id, e164"
                ).eq("e164", phone_with_plus).execute()
        
        if not result.data:
            return {"error": "Phone number not found in system"}
        
        phone_data = result.data[0]
        
        # Get company name
        company = supabase.table("companies").select("name").eq("id", phone_data["company_id"]).execute()
        company_name = company.data[0]["name"] if company.data else "Unknown"
        
        # Get office name
        office = supabase.table("offices").select("name").eq("id", phone_data["office_id"]).execute()
        office_name = office.data[0]["name"] if office.data else "Unknown"
        
        print(f"✅ Found phone: {phone_data['e164']}, Company: {company_name}, Office: {office_name}")
        
        return {
            "phone_number_id": phone_data["id"],
            "company_id": phone_data["company_id"],
            "office_id": phone_data["office_id"],
            "phone_number": phone_data["e164"],
            "company_name": company_name,
            "office_name": office_name
        }
        
    except Exception as e:
        print(f"❌ Error in resolve_phone: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}