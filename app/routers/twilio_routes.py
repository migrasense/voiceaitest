# app/routers/twilio_routes.py

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response, PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Start, Stream
from supabase import create_client, Client
from dotenv import load_dotenv
import os, logging

load_dotenv()
router = APIRouter(prefix="/twilio", tags=["Twilio"])

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PUBLIC_URL = os.getenv("PUBLIC_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@router.get("/debug/twiml")
async def debug_twiml():
    """
    Returns sample TwiML XML to verify the Stream tag is correctly formatted.
    """
    if not PUBLIC_URL:
        return PlainTextResponse("PUBLIC_URL not set", status_code=500)
    
    clean_url = PUBLIC_URL.strip().rstrip('/')
    if clean_url.startswith('https://'):
        clean_url = clean_url[8:]
    elif clean_url.startswith('http://'):
        clean_url = clean_url[7:]
    if clean_url.endswith('/'):
        clean_url = clean_url[:-1]
    
    stream_url = f"wss://{clean_url}/audio"
    
    response = VoiceResponse()
    response.say("Test message", voice="Polly.Joanna")
    start = Start()
    stream = Stream(url=stream_url)
    stream.parameter(name="caller", value="+18702735332")
    stream.parameter(name="receiver", value="+19094135795")
    start.append(stream)
    response.append(start)
    
    return Response(content=str(response), media_type="application/xml")


@router.get("/debug/stream-url")
async def debug_stream_url():
    """
    Diagnostic endpoint to verify the Stream URL format.
    Returns the exact URL that would be sent to Twilio.
    """
    if not PUBLIC_URL:
        return {"error": "PUBLIC_URL not set", "public_url": None}
    
    clean_url = PUBLIC_URL.strip().rstrip('/')
    if clean_url.startswith('https://'):
        clean_url = clean_url[8:]
    elif clean_url.startswith('http://'):
        clean_url = clean_url[7:]
    
    if clean_url.endswith('/'):
        clean_url = clean_url[:-1]
    
    stream_url = f"wss://{clean_url}/audio"
    
    # Generate sample TwiML to verify format
    response = VoiceResponse()
    response.say("Test", voice="Polly.Joanna")
    start = Start()
    stream = Stream(url=stream_url)
    stream.parameter(name="caller", value="+18702735332")
    stream.parameter(name="receiver", value="+19094135795")
    start.append(stream)
    response.append(start)
    sample_twiml = str(response)
    
    return {
        "public_url_env": PUBLIC_URL,
        "cleaned_url": clean_url,
        "stream_url": stream_url,
        "websocket_endpoint": "/audio",
        "test_endpoint": "/audio/test",
        "sample_twiml": sample_twiml,
        "twiml_contains_wss": "wss://" in sample_twiml,
        "twiml_contains_stream_url": stream_url in sample_twiml
    }


@router.post("/voice")
async def twilio_voice(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    CallSid: str = Form(...),
):
    """
    Twilio webhook for incoming calls.
    Streams live audio to /audio, sending both caller & receiver metadata.
    """
    try:
        logging.info(f"📞 Incoming Twilio call: {From} → {To} | CallSid={CallSid}")

        if not PUBLIC_URL:
            raise ValueError("❌ Missing PUBLIC_URL — please set in .env")

        response = VoiceResponse()
        response.say(
            "You have reached Servoice! Connecting you to our virtual assistant.",
            voice="Polly.Joanna",
        )

        # ✅ Use <Start><Stream> to pass both caller (client) and receiver (agency)
        # 🔧 CRITICAL: Clean PUBLIC_URL to ensure proper wss:// URL construction
        clean_url = PUBLIC_URL.strip().rstrip('/')
        if clean_url.startswith('https://'):
            clean_url = clean_url[8:]  # Remove 'https://'
        elif clean_url.startswith('http://'):
            clean_url = clean_url[7:]   # Remove 'http://'
        
        # Ensure no trailing slash before adding /audio
        if clean_url.endswith('/'):
            clean_url = clean_url[:-1]
        
        stream_url = f"wss://{clean_url}/audio"
        
        # ✅ Log the EXACT URL being sent to Twilio for debugging
        logging.info(f"🔗 Generated Stream URL: {stream_url}")
        logging.info(f"📋 PUBLIC_URL env var: {PUBLIC_URL}")
        
        start = Start()
        stream = Stream(url=stream_url)
        # Strip whitespace and ensure the "+" is preserved
        stream.parameter(name="caller", value=From.strip())
        stream.parameter(name="receiver", value=To.strip())

        start.append(stream)
        response.append(start)

        # Log the final TwiML for debugging
        twiml_content = str(response)
        logging.info(f"🎧 Streaming call {From} → {To} to {stream_url}")
        logging.info(f"📄 Generated TwiML XML:\n{twiml_content}")
        
        # ✅ Verify Stream URL appears in TwiML
        if stream_url not in twiml_content:
            logging.error(f"❌ CRITICAL: Stream URL {stream_url} NOT FOUND in TwiML!")
        if "wss://" not in twiml_content:
            logging.error(f"❌ CRITICAL: wss:// protocol NOT FOUND in TwiML!")

        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        logging.exception("❌ Twilio Voice Route Failed")
        return PlainTextResponse(f"Error: {e}", status_code=500)




# @router.post("/voice")
# async def twilio_voice(
#     From: str = Form(...),
#     To: str = Form(...),
#     SpeechResult: str = Form(None),
#     CallSid: str = Form(...),
# ):
#     """
#     Twilio webhook for voice calls.
#     1️⃣ Detect service type via phone_number → office → service_config
#     2️⃣ Pass caller's speech (if any) to GroqClient
#     3️⃣ Respond via TwiML to speak back the AI response
#     """

#     try:
#         incoming_number = From
#         text = SpeechResult or "Hello"
#         stt_lang_hint = "en"  # optionally detect later

#         # 🔍 Auto-resolve service type
#         service_name = conversation_manager.resolve_service_by_phone(supabase, incoming_number)
#         logging.info(f"Twilio Call {CallSid}: service={service_name}")

#         # 🧠 Create or continue conversation
#         session_id = conversation_manager.get_or_create_active_session(caller_id=incoming_number)

#         # 💬 Generate AI response
#         ai_result = groq_client.detect_intent(
#             text_to_analyze=text,
#             stt_lang_hint=stt_lang_hint,
#             context_messages=conversation_manager.sessions[session_id].get("messages", []),
#             is_first_turn=len(conversation_manager.sessions[session_id]["messages"]) == 0,
#             service_name=service_name,
#         )

#         # Save message to session
#         conversation_manager.add_message(session_id, {
#             "role": "user",
#             "transcript": text,
#             "language": stt_lang_hint,
#             "intent": ai_result.get("intent"),
#             "urgent": ai_result.get("urgent"),
#             "ai_response": ai_result.get("ai_response"),
#             "ai_response_translated": ai_result.get("ai_response_translated"),
#         })

#         # 🗣️ Respond back via Twilio
#         response = VoiceResponse()
#         response.say(ai_result["ai_response"], voice="Polly.Joanna")  # or "alice" / "Polly.Matthew"
#         response.pause(length=1)
#         response.listen(timeout=8, speech_timeout="auto", action="/twilio/voice")  # keep the loop open

#         return Response(content=str(response), media_type="application/xml")

#     except Exception as e:
#         logging.exception("Twilio Voice Route Failed")
#         return PlainTextResponse(f"Error: {e}", status_code=500)
