import asyncio
from datetime import datetime
import uuid
from app.core.connection_manager import manager
from app.services.groq_client import groq_client
from app.core.config import logger
from app.models.mock_stt import mock_stt
from app.services.conversation_manager import conversation_manager
import os
from supabase import create_client
from app.db.supabase import supabase  # ✅ assumes you have supabase client set up
from collections import Counter

from app.utils.parsers import extract_name, extract_phone


def on_error(_, error, **kwargs):
    logger.error(f"❌ Deepgram error: {error}")

def on_transcript(_, result, **kwargs):
    if not result or not result.channel or not result.channel.alternatives:
        return

    transcript = result.channel.alternatives[0].transcript
    if transcript.strip():
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({
                "type": "transcript",
                "transcript": transcript,
                "is_final": result.is_final,
                "timestamp": datetime.now().isoformat()
            }),
            manager.loop
        )

        if result.is_final:
            process_final_transcript(transcript)


GOODBYE_PHRASES = ["goodbye", "bye", "thanks bye", "thanks, that's all", "talk later", "adios", "hasta luego"]

# Number of past turns to keep in context
CONTEXT_WINDOW = 5  

# Number of past turns to keep in context

# transcript_service.py - Updated process_final_transcript function

async def process_final_transcript(transcript: str, caller_id: str = "unknown"):
    # 1. Get or create in-memory session ID
    session_id = conversation_manager.get_or_create_active_session(caller_id)

    # 2. Check if conversation already exists in Supabase, else create one
    convo_exists = supabase.table("conversations").select("id").eq("id", session_id).execute()
    if not convo_exists.data:
        supabase.table("conversations").insert({
            "id": session_id,
            "caller_id": caller_id,
            "start_time": datetime.now().isoformat(),
            "status": "live"
        }).execute()

    # === Enhanced Intent Detection ===
    history = conversation_manager.sessions[session_id]["messages"]
    recent_history = history[-CONTEXT_WINDOW:]
    context = "\n".join(
        [f"User: {m['transcript']}\nAI: {m['ai_response']}" for m in recent_history if m.get("ai_response")]
    )

    # Build prompt for Groq with better job application detection
    prompt = f"""
You are an AI caregiving assistant. Analyze the user's message and determine if they're asking about a job application status.

Conversation so far:
{context}

User: {transcript}

Instructions:
1. If the user is asking about job application status, employment, hiring, or interview status, respond with intent: "job_application_status"
2. Otherwise, continue the conversation naturally
3. Detect the language and provide appropriate response

Respond in this format:
Intent: [intent_type]
Response: [your response]
Language: [detected_language]
Urgent: [true/false]
    """

    # Call Groq
    intent = groq_client.detect_intent(prompt)
    
    # === Job Application Lookup Logic ===
    ai_response = None
    job_application_found = False
    
    # Check if this is a job application inquiry
    is_job_inquiry = await _is_job_application_inquiry(transcript, intent)
    
    if is_job_inquiry:
        logger.info(f"Job application inquiry detected: {transcript}")
        ai_response, job_application_found = await _handle_job_application_lookup(transcript)
    
    # If not a job inquiry or no specific response from job lookup, use Groq response
    if not ai_response:
        ai_response = intent.get("ai_response") or "I'm here to help, could you clarify your request?"

    # === Build final entry ===
    entry = {
        "transcript": transcript,
        "translated_text": intent.get("translated_text") or transcript,
        "intent": "job_application_status" if is_job_inquiry else intent.get("intent"),
        "ai_response": ai_response,
        "ai_response_translated": ai_response,
        "urgent": intent.get("urgent") or job_application_found,  # Mark as urgent if job found
        "language": intent.get("detected_language") or "en",
        "is_final": True,
        "timestamp": datetime.now().isoformat(),
        "metadata": {
            "job_application_inquiry": is_job_inquiry,
            "job_application_found": job_application_found
        }
    }

    # Save to in-memory manager
    conversation_manager.add_message(session_id, entry)

    # Run session-level analysis
    msgs = conversation_manager.sessions[session_id]["messages"]
    intents = [m.get("intent") for m in msgs if m.get("intent")]
    counter = Counter(intents)

    analysis = {
        "summary": f"Conversation had {len(msgs)} messages. Main intent: {counter.most_common(1)[0][0] if counter else 'unknown'}.",
        "main_intent": counter.most_common(1)[0][0] if counter else "unknown",
        "urgent": any(m.get("urgent") for m in msgs),
        "total_messages": len(msgs),
        "intents_distribution": dict(counter),
        "ended_with_closure": any(m.get("intent") == "polite_closure" for m in msgs),
        "job_inquiries": len([m for m in msgs if m.get("intent") == "job_application_status"])
    }

    conversation_manager.sessions[session_id]["analysis"] = analysis

    # Save to Supabase (messages table)
    try:
        supabase.table("messages").insert({
            "session_id": session_id,
            **{k: v for k, v in entry.items() if k != "metadata"}  # Exclude metadata from DB
        }).execute()
    except Exception as e:
        logger.error(f"Failed to save message to Supabase: {e}")

    # Check for conversation closure
    lowered = transcript.strip().lower()
    if any(phrase in lowered for phrase in GOODBYE_PHRASES):
        conversation_manager.end_session(session_id)
        entry["session_closed"] = True  

        try:
            supabase.table("conversations").update({
                "status": "closed",
                "end_time": datetime.now().isoformat(),
                "analysis": analysis
            }).eq("id", session_id).is_("end_time", None).execute()
        except Exception as e:
            logger.error(f"Failed to update conversation status: {e}")

    return session_id, entry


async def _is_job_application_inquiry(transcript: str, intent: dict) -> bool:
    """
    Determine if the user is asking about job application status
    """
    # Check Groq intent first
    if intent.get("intent") == "job_application_status":
        return True
    
    # Fallback: Check for job-related keywords
    job_keywords = [
        "job application", "application status", "applied", "status of my application",
        "follow up on my application", "hiring", "interview", "employment",
        "position", "job status", "application", "resume", "when will I hear back",
        "still under review", "applied for", "submitted application"
    ]
    
    transcript_lower = transcript.lower()
    return any(keyword in transcript_lower for keyword in job_keywords)


async def _handle_job_application_lookup(transcript: str) -> tuple[str, bool]:
    """
    Handle job application lookup and return response and found status
    """
    try:
        # Extract information from transcript
        phone = extract_phone(transcript)
        name = extract_name(transcript)
        
        logger.info(f"Extracted - Phone: {phone}, Name: {name}")
        
        # If no extractable info, ask for it
        if not phone and not name:
            return (
                "I'd be happy to help you check your job application status! "
                "Could you please provide your full name or the phone number you used when applying?",
                False
            )
        
        # Search for application
        applications = await _search_job_applications(phone, name)
        
        if applications:
            app = applications[0]  # Take the first match
            response = _format_job_application_response(app)
            logger.info(f"Job application found for: {app.get('name')} - {app.get('position')}")
            return response, True
        else:
            # Provide helpful response when not found
            if phone and name:
                response = (
                    f"I couldn't find an application for {name} with phone number ending in "
                    f"{phone[-4:]} in our records. Please double-check the information or "
                    f"contact our HR department directly."
                )
            elif phone:
                response = (
                    f"I couldn't find an application with phone number ending in {phone[-4:]}. "
                    f"Could you also provide the name you used when applying?"
                )
            elif name:
                response = (
                    f"I couldn't find an application for {name}. "
                    f"Could you provide the phone number you used when applying?"
                )
            
            logger.info(f"No job application found for phone: {phone}, name: {name}")
            return response, False
            
    except Exception as e:
        logger.error(f"Error in job application lookup: {e}")
        return (
            "I'm having trouble accessing our application database right now. "
            "Please try again in a moment or contact our HR department directly.",
            False
        )


async def _search_job_applications(phone: str, name: str) -> list:
    """
    Search for job applications by phone and/or name
    """
    applications = []
    
    try:
        # Strategy 1: Search by phone (most reliable)
        if phone:
            # Try different phone formats
            phone_formats = [
                phone,  # Original format (digits only)
                f"{phone[:3]}-{phone[3:6]}-{phone[6:]}" if len(phone) == 10 else phone,  # XXX-XXX-XXXX
                f"({phone[:3]}) {phone[3:6]}-{phone[6:]}" if len(phone) == 10 else phone,  # (XXX) XXX-XXXX
            ]
            
            for phone_format in phone_formats:
                result = supabase.table("job_applications").select("*").eq("phone_number", phone_format).execute()
                if result.data:
                    applications.extend(result.data)
                    break  # Found with this format, no need to try others
        
        # Strategy 2: If no results by phone, try name
        if not applications and name:
            # Try exact match first
            result = supabase.table("job_applications").select("*").ilike("name", name).execute()
            if result.data:
                applications.extend(result.data)
            else:
                # Try partial match (fuzzy search)
                name_parts = name.split()
                for part in name_parts:
                    if len(part) > 2:  # Only search for meaningful parts
                        result = supabase.table("job_applications").select("*").ilike("name", f"%{part}%").execute()
                        if result.data:
                            applications.extend(result.data)
                            break
        
        # Remove duplicates while preserving order
        seen = set()
        unique_applications = []
        for app in applications:
            app_id = app.get("id")
            if app_id not in seen:
                seen.add(app_id)
                unique_applications.append(app)
        
        return unique_applications
        
    except Exception as e:
        logger.error(f"Database search error: {e}")
        return []


def _format_job_application_response(app: dict) -> str:
    """
    Format a professional response for job application status
    """
    name = app.get('name', 'there')
    position = app.get('position', 'the position')
    status = app.get('status', 'under review')
    last_contact = app.get('last_contact')
    notes = app.get('notes', '')
    
    # Start with greeting and basic info
    response = f"Hi {name}! I found your application for the {position} position. "
    
    # Add status with appropriate tone
    status_messages = {
        'pending': f"Your application is currently **pending** and under review by our hiring team.",
        'under review': f"Your application is **under review** by our hiring team.",
        'in review': f"Your application is **in review** with our hiring manager.",
        'interview scheduled': f"Great news! Your application status is **interview scheduled**.",
        'hired': f"Congratulations! Your application status shows you've been **hired**!",
        'rejected': f"Thank you for your interest. Unfortunately, your application was **not selected** for this position.",
        'withdrawn': f"Your application shows as **withdrawn** from consideration."
    }
    
    response += status_messages.get(status.lower(), f"Your current status is **{status}**.")
    
    # Add timing information
    if last_contact:
        response += f" Our last update was on {last_contact}."
    
    # Add next steps based on status
    if status.lower() in ['pending', 'under review', 'in review']:
        response += " We'll contact you once we have an update on your application."
    elif status.lower() == 'interview scheduled':
        response += " You should receive interview details soon if you haven't already."
    
    # Add any additional notes
    if notes and notes.strip():
        response += f" Additional notes: {notes}"
    
    return response


# async def process_final_transcript(transcript: str, caller_id: str = "unknown"):
#     # 1. Get or create in-memory session ID
#     session_id = conversation_manager.get_or_create_active_session(caller_id)

#     # 2. Check if conversation already exists in Supabase, else create one
#     convo_exists = supabase.table("conversations").select("id").eq("id", session_id).execute()
#     if not convo_exists.data:
#         supabase.table("conversations").insert({
#             "id": session_id,
#             "caller_id": caller_id,
#             "start_time": datetime.now().isoformat(),
#             "status": "live"
#         }).execute()

#     # === Detect intent via Groq ===
#     history = conversation_manager.sessions[session_id]["messages"]
#     recent_history = history[-CONTEXT_WINDOW:]
#     context = "\n".join(
#         [f"User: {m['transcript']}\nAI: {m['ai_response']}" for m in recent_history if m.get("ai_response")]
#     )

#     # 4. Build prompt for Groq
#     prompt = f"""
# You are an AI caregiving assistant. Continue the conversation naturally.

# Conversation so far:
# {context}

# User: {transcript}
# AI:
#     """

#     # 5. Call Groq
#     intent = groq_client.detect_intent(prompt)

#     # === Handle special intents (Job Applications etc.) ===
#     ai_response = intent.get("ai_response") or "I'm here to help, could you clarify your request?"
#     # === Handle special intents (Job Applications etc.) ===
#     if intent.get("intent") in ["job application/application status", "job_application_status"]:
#         phone = None
#         name = None

#         if any(char.isdigit() for char in transcript):
#             phone = transcript.strip()
#         else:
#             name = transcript.strip()

#         query = supabase.table("job_applications").select("*")
#         if phone:
#             query = query.eq("phone_number", phone)
#         elif name:
#             query = query.ilike("name", f"%{name}%")

#         job_result = query.execute()

#         if job_result.data:
#             job = job_result.data[0]
#             ai_response = (
#                 f"Hi {job['name']}, I found your application for {job['position']}. "
#                 f"The current status is **{job['status']}**. "
#                 f"Last contact was on {job['last_contact']}. "
#                 f"Notes: {job['notes']}."
#             )
#         else:
#             ai_response = (
#                 "I couldn't find your job application in our records. "
#                 "Can you confirm the phone number or full name you used to apply?"
#             )

#     # === Build final entry (use ai_response consistently) ===
#     entry = {
#         "transcript": transcript,
#         "translated_text": intent.get("translated_text") or transcript,
#         "intent": intent.get("intent"),
#         "ai_response": ai_response,
#         "ai_response_translated": ai_response,   # 🔑 unify here
#         "urgent": intent.get("urgent"),
#         "language": intent.get("detected_language"),
#         "is_final": True,
#         "timestamp": datetime.now().isoformat(),
#     }


#     # 6. Build message entry
#     # entry = {
#     #     "transcript": transcript,
#     #     "translated_text": intent.get("translated_text") or transcript,
#     #     "intent": intent.get("intent"),
#     #     "ai_response": intent.get("ai_response"),
#     #     "ai_response_translated": intent.get("ai_response_translated"),
#     #     "urgent": intent.get("urgent"),
#     #     "language": intent.get("detected_language"),
#     #     "is_final": True,
#     #     "timestamp": datetime.now().isoformat(),
#     # }

#     # 7. Save to in-memory manager
#     conversation_manager.add_message(session_id, entry)

#     # 6. Run session-level analysis
#     msgs = conversation_manager.sessions[session_id]["messages"]
#     intents = [m.get("intent") for m in msgs if m.get("intent")]
#     counter = Counter(intents)

#     analysis = {
#         "summary": f"Conversation had {len(msgs)} messages. Main intent: {counter.most_common(1)[0][0] if counter else 'unknown'}.",
#         "main_intent": counter.most_common(1)[0][0] if counter else "unknown",
#         "urgent": any(m.get("urgent") for m in msgs),
#         "total_messages": len(msgs),
#         "intents_distribution": dict(counter),
#         "ended_with_closure": any(m.get("intent") == "polite_closure" for m in msgs),
#     }

#     conversation_manager.sessions[session_id]["analysis"] = analysis

#     # 8. Save to Supabase (messages table)
#     supabase.table("messages").insert({
#         "session_id": session_id,
#         **entry
#     }).execute()

#     # 9. If closure detected, update conversation
#     lowered = transcript.strip().lower()
#     if any(phrase in lowered for phrase in GOODBYE_PHRASES):
#         conversation_manager.end_session(session_id)
#         entry["session_closed"] = True  

#         supabase.table("conversations").update({
#             "status": "closed",
#             "end_time": datetime.now().isoformat(),
#             "analysis": analysis
#         }).eq("id", session_id).is_("end_time", None).execute()

#     return session_id, entry




