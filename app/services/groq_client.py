# import json
# import re
# import requests
# from typing import Dict, Any
# from app.core.config import GROQ_API_KEY, logger

# class GroqClient:
#     def __init__(self):
#         self.api_key = GROQ_API_KEY
#         self.model = "llama3-70b-8192"
#         self.base_url = "https://api.groq.com/openai/v1/chat/completions"
#         self.headers = {"Authorization": f"Bearer {self.api_key}"}

#     def detect_intent(self, text_to_analyze: str) -> Dict[str, Any]:
#         prompt = self._create_prompt(text_to_analyze)
#         try:
#             response = requests.post(
#                 self.base_url,
#                 headers=self.headers,
#                 json={
#                     "model": self.model,
#                     "messages": [
#                         {"role": "system", "content": "You are a senior care agency multilingual administrative assistant."},
#                         {"role": "user", "content": prompt}
#                     ],
#                     "temperature": 0.1
#                 },
#                 timeout=15
#             )
#             response.raise_for_status()
#             return self._parse_response(response.json())
#         except Exception as e:
#             logger.error(f"[Groq] ❌ Error: {e}")
#             return self._fallback_response(text_to_analyze)

#     def _create_prompt(self, text: str) -> str:
#         return f"""
#             You are a warm and professional AI assistant supporting a caregiving agency. Your role is to assist callers clearly and kindly, as if you're a friendly front desk team member. Follow these steps carefully:

#             1. LANGUAGE DETECTION & TRANSLATION:
#             - Detect if the message contains Spanish (fully or partially)
#             - Translate Spanish to English, preserving proper names and terms

#             2. INTENT & URGENCY ANALYSIS:
#             - Determine intent (choose one):
#             * billing_issue
#             * appointment
#             * caregiver_reschedule
#             * complaint
#             * inquiry
#             * job application/application status
#             * medical
#             * Urgent
#             * polite_closure 
#             * other
#             - Urgency:
#             * true ONLY if the message suggests an urgent issue such as a caregiver no-show, immediate care disruption, or medical emergency. Otherwise, mark as false.

#             3. AI RESPONSE:
#             - If urgency is true, respond with a calm and professional message like: 
#             - "An admin will be with you shortly." (English)
#             - "Un administrador se comunicará con usted en breve." (Spanish)
#             - Otherwise, generate a polite response that matches the detected language (en/es) exactly.
#             - If detected_language is "en", respond only in English.
#             - If detected_language is "es", respond only in Spanish.
#             - Do not mix or switch languages.
#             - If the intent is "other", respond in English with a generic message: "We received your message and will respond soon."
#             - If intent is "polite_closure", respond with a polite acknowledgment that mirrors the tone. For example:
#             - If the caller says "thank you", reply "You're very welcome!"
#             - If they say "goodbye" or "bye", reply "Thank you for calling us, you have a wonderful day!"(English)
#             - "Gracias por su llamada. ¡Que tenga un buen día!" (Spanish)
#             - If the intent is "job application/application status", respond with a message like: "Thank you for your interest in joining our team. We will review your application and get back to you soon."
#             - If the intent is "medical", respond with a message like: "Thank you for reaching out. We will connect you with our admin team shortly."
#             - If the intent is "inquiry", respond politely in the detected language. Keep the answer general and helpful unless the message includes specific service questions (like pricing or hours), in which case provide a placeholder or suggest follow-up.

#             4. STRICT JSON OUTPUT:
#             {{
#             "original_text": "{text}",
#             "translated_text": "Translate the original_text to English here",
#             "detected_language": "en/es/mixed",
#             "intent": "specific_intent_from_list",
#             "urgent": boolean,
#             "confidence": 0.0-1.0,
#             "key_phrases": ["list", "of", "phrases"],
#             "ai_response": "Response in caller's language",
#             "ai_response_translated": "Response translated to English"
#             }}

#             INPUT MESSAGE:
#             \"{text}\"
#             """

#     def _parse_response(self, response: Dict) -> Dict[str, Any]:
#         raw_output = response["choices"][0]["message"]["content"]
#         match = re.search(r'{.*}', raw_output, re.DOTALL)
#         return json.loads(match.group()) if match else {}

#     def _fallback_response(self, text: str) -> Dict[str, Any]:
#         return {
#             "success": False,
#             "intent": "other",
#             "ai_response": "We received your message and will respond soon.",
#             "ai_response_translated": "We received your message and will respond soon.",
#             "detected_language": "error",
#             "translated_text": text,
#             "urgent": False,
#             "confidence": 0.0,
#             "key_phrases": []
#         }

# groq_client = GroqClient()

# app/services/groq_client.py

# import json, re, random, time
# from typing import Dict, Any, List, Optional
# import requests
# from app.core.config import GROQ_API_KEY, logger

# class GroqClient:
#     def __init__(self):
#         self.api_key = GROQ_API_KEY
#         self.model = "llama-3.1-8b-instant"
#         self.base_url = "https://api.groq.com/openai/v1/chat/completions"
#         self.headers = {
#             "Authorization": f"Bearer {self.api_key}",
#             "Content-Type": "application/json",
#         }

#     # ---------- HTTP with retry (429/5xx only) ----------
#     def _post_with_retry(self, payload, retries: int = 2, backoff: float = 2.0):
#         r = None
#         for attempt in range(retries):
#             try:
#                 r = requests.post(self.base_url, headers=self.headers, json=payload, timeout=15)
#                 if r.status_code == 400:
#                     logger.error(f"[Groq 400] payload={json.dumps(payload, ensure_ascii=False)[:800]}")
#                     logger.error(f"[Groq 400] resp={r.text[:800]}")
#                 r.raise_for_status()
#                 return r
#             except requests.exceptions.RequestException as e:
#                 status = getattr(r, "status_code", None)
#                 transient = status in (429, 500, 502, 503, 504)
#                 if attempt < retries - 1 and transient:
#                     wait = backoff * (2 ** attempt) + random.uniform(0, 0.5)
#                     logger.warning(f"[Groq] retry in {wait:.1f}s due to {e}")
#                     time.sleep(wait)
#                     continue
#                 raise

#     # ---------- Public API ----------
#     def detect_intent(
#         self,
#         text_to_analyze: str,
#         stt_lang_hint: str = "en",
#         context_messages: Optional[List[dict]] = None,
#         is_first_turn: bool = False,
#         is_greeting_only: bool = False,
#         is_continuation: bool = False,
#     ) -> Dict[str, Any]:
#         """
#         Returns JSON with keys:
#         original_text, translated_text, detected_language (en|es), intent, urgent, ai_response, ai_response_translated
#         """
#         try:
#             if not text_to_analyze or not text_to_analyze.strip():
#                 return self._fallback_response(text_to_analyze)

#             text = text_to_analyze.strip()
#             if len(text) > 800:
#                 text = text[:800]

#             messages = self._build_messages(
#                 text=text,
#                 stt_lang_hint=stt_lang_hint,
#                 is_first_turn=is_first_turn,
#                 is_greeting_only=is_greeting_only,
#                 is_continuation=is_continuation,
#                 context_messages=context_messages,
#             )

#             payload = {
#                 "model": self.model,
#                 "messages": messages,
#                 "temperature": 0.2,
#                 "max_tokens": 400,
#                 "response_format": {"type": "json_object"},
#             }

#             r = self._post_with_retry(payload, retries=2, backoff=2)
#             out = self._parse_response(r.json())

#             # Post enforcement so TTS/pipeline doesn't drift
#             out["detected_language"] = "es" if stt_lang_hint == "es" else "en"
#             if stt_lang_hint == "en":
#                 if not out.get("ai_response"):
#                     out["ai_response"] = out.get("ai_response_translated") or "Thanks for reaching out. How can I help today?"
#                 if not out.get("ai_response_translated"):
#                     out["ai_response_translated"] = out["ai_response"]
#             else:  # Spanish (or default es)
#                 if not out.get("ai_response"):
#                     out["ai_response"] = out.get("ai_response_translated") or "Entiendo. ¿Cómo puedo ayudarle hoy?"
#                 # ai_response_translated should be English:
#                 if not out.get("ai_response_translated"):
#                     out["ai_response_translated"] = "I understand. How can I help you today?"

#             return out

#         except Exception as e:
#             logger.error(f"[Groq] ❌ Error: {e}")
#             return self._fallback_response(text_to_analyze)

#     # ---------- Messages / Prompt ----------
#     def _build_messages(
#         self,
#         text: str,
#         stt_lang_hint: str,
#         is_first_turn: bool,
#         is_greeting_only: bool,
#         is_continuation: bool,
#         context_messages: Optional[List[dict]] = None,
#     ) -> List[dict]:
#         # System prompt with natural tone & flow + runtime flags
#         system_content = f"""
#     NATURAL TONE & FLOW — CAREGIVING RECEPTION

#     Goals
#     - Feel like a warm, capable human receptionist.
#     - Acknowledge and empathize before asking.
#     - Ask ONE next, relevant question per turn.
#     - Keep context; never reset unless it's a brand-new session.

#     Language
#     - If caller speaks English → reply only in English.
#     - If Spanish → reply only in Spanish.
#     - Mirror their words (e.g., “mom,” “companionship,” “medication reminders”).

#     Greeting Handling (very important)
#     - If the turn is just a salutation (e.g., “hello,” “good evening”), DO NOT infer schedule and DO NOT update time-of-day.
#     - Respond briefly: “Hello! How can I help you today?” (ES: “¡Hola! ¿En qué puedo ayudarle hoy?”)

#     First Meaningful Inquiry (warm intro)
#     - Start with empathy + capability:
#     EN: “Thanks for reaching out—we can absolutely help with {{needs}}. We also offer medication reminders, friendly companionship, walking/light activity support, meal prep, and light housekeeping.”
#     ES: “Gracias por comunicarse—con gusto ayudamos con {{needs}}. También ofrecemos recordatorios de medicamentos, compañía, apoyo para caminar/actividad ligera, preparación de comidas y limpieza ligera.”
#     - Then ask ONE next question (see order below).

#     Turn-Taking Order (collect one at a time)
#     1) hours_per_week
#     2) days
#     3) time_of_day
#     4) start_date
#     5) time_window
#     6) contact (name, phone)

#     Confirmation Style
#     - Use a light recap only when helpful, then ask the next single question.
#     - Prefer “Absolutely,” “Of course,” “Happy to help,” “That’s helpful.”
#     - Avoid the exact phrase “Perfect -”.

#     What NOT to do
#     - Don't infer “evenings” from “good evening.”
#     - Don't ask two questions in one turn.
#     - Don't restart or repeat a full summary every turn.
#     - Don't mention office hours unless asked.

#     When Caller Is Unsure/Nervous
#     - EN: “Totally okay—we’ll take it step by step. To start, how many hours per week feels right?”
#     - ES: “Está bien, iremos paso a paso. Para empezar, ¿cuántas horas por semana le gustaría?”

#     Closing
#     - After capturing name + phone:
#     EN: “Thank you, {{name}}. We’ll follow up at {{phone}} to confirm. Is there anything else I can help with?”
#     ES: “Gracias, {{name}}. Nos comunicaremos al {{phone}} para confirmar. ¿Algo más en lo que pueda ayudarle?”

#     STRICT JSON OUTPUT — return ONE object only with keys:
#     {{
#     "original_text": "<original>",
#     "translated_text": "English translation of original_text",
#     "detected_language": "en|es (must equal STT_LANGUAGE_HINT)",
#     "intent": "urgent|job_application|appointment|caregiver_reschedule|billing|complaint|inquiry|polite_closure|backchannel|other",
#     "urgent": true|false,
#     "ai_response": "reply in detected_language",
#     "ai_response_translated": "reply in English"
#     }}

#     Runtime flags (use these exactly as given):
#     STT_LANGUAGE_HINT={stt_lang_hint}
#     IS_FIRST_TURN={is_first_turn}
#     IS_GREETING_ONLY={is_greeting_only}
#     IS_CONTINUATION={is_continuation}

#     You MUST output a single valid JSON object ONLY—no prose.
#     """

#         messages: List[dict] = [{"role": "system", "content": system_content}]

#         # Include recent context (cap ~6 exchanges = 12 messages)
#         if context_messages:
#             messages.extend(context_messages[-12:])

#         # User turn with compact task/spec (keeps schema stable)
#         messages.append({
#             "role": "user",
#             "content": self._create_prompt(
#                 text,
#                 is_first_turn=is_first_turn,
#                 is_greeting_only=is_greeting_only,
#                 is_continuation=is_continuation,
#             ),
#         })
#         return messages


#     def _create_prompt(
#         self,
#         text: str,
#         is_first_turn: bool = False,
#         is_greeting_only: bool = False,
#         is_continuation: bool = False,
#     ) -> str:
#         intents = [
#             "greeting",
#             "inquiry",
#             "caregiver_reschedule",
#             "appointment",
#             "medical",
#             "job_application",
#             "billing",
#             "complaint",
#             "polite_closure",
#             "backchannel",
#             "other",
#         ]

#         flow = []
#         if is_greeting_only:
#             flow.append("- Greeting only: reply briefly and politely; ask how you can help today.")
#         if is_first_turn:
#             flow.append(
#                 "- First meaningful inquiry: warm welcome + brief list of services; "
#                 "end with ONE focused question about needs or schedule; avoid generic 'How can we assist?'."
#             )
#         if is_continuation:
#             flow.append(
#                 "- Continuation (ok/yes/sure/tell me more/discuss further): keep the current topic; "
#                 "acknowledge briefly and ask ONE next specific question."
#             )

#         return (
#             "Task: Return ONLY one JSON object with these keys:\n"
#             "{"
#             '"original_text":"<original>",'
#             '"translated_text":"<English translation of original_text, or repeat if English>",'
#             '"detected_language":"en|es",'
#             '"intent":"one of ' + str(intents) + '",'
#             '"urgent":false,'
#             '"ai_response":"reply in detected_language",'
#             '"ai_response_translated":"reply in English"'
#             "}\n"
#             "Rules:\n"
#             "- Use conversation context to keep the thread; do NOT restart topics.\n"
#             "- Ask only ONE next question that advances scheduling/needs: order = hours/week → days → time_of_day → start_date.\n"
#             "- If the user already gave a detail, do NOT ask it again.\n"
#             "- Normalize day ranges (e.g., 'Monday to Friday' / 'Mon–Fri' / 'weekdays' → Mon–Fri).\n"
#             "- Never mention office hours unless explicitly asked.\n"
#             "- Do NOT output the phrase 'Perfect -'. Keep tone warm, concise, professional.\n"
#             + ("\n".join(flow) + "\n" if flow else "")
#             + f'INPUT:\n"{text}"'
#         )

#     # ---------- Parse / Fallback ----------
#     def _parse_response(self, response: Dict) -> Dict[str, Any]:
#         raw = response["choices"][0]["message"]["content"]
#         try:
#             parsed = json.loads(raw)
#         except json.JSONDecodeError:
#             m = re.search(r"{.*}", raw, re.DOTALL)
#             parsed = json.loads(m.group()) if m else {}

#         return {
#             "original_text": parsed.get("original_text", ""),
#             "translated_text": parsed.get("translated_text", ""),
#             "detected_language": parsed.get("detected_language", "en"),
#             "intent": parsed.get("intent", "other"),
#             "urgent": parsed.get("urgent", False),
#             "ai_response": parsed.get("ai_response", ""),
#             "ai_response_translated": parsed.get("ai_response_translated", ""),
#         }

#     def _fallback_response(self, text: str) -> Dict[str, Any]:
#         return {
#             "original_text": text or "",
#             "translated_text": text or "",
#             "detected_language": "en",
#             "intent": "other",
#             "urgent": False,
#             "ai_response": "Thanks for reaching out. How can I help today?",
#             "ai_response_translated": "Thanks for reaching out. How can I help today?",
#         }

# groq_client = GroqClient()

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client_natural.py
# Simplified Groq client focused on natural conversation flow

# app/services/groq_client.py
# Complete Groq client with unified proactive system prompt

import json, re, random, time
from typing import Dict, Any, List, Optional
import requests
from app.core.config import GROQ_API_KEY, logger
from app.services.prompt_manager import PromptManager

prompt_manager = PromptManager()




class GroqClient:
    def __init__(self):
        self.api_key = GROQ_API_KEY
        self.model = "llama-3.1-8b-instant"
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ---------- Main API ----------
    def detect_intent(
        self,
        text_to_analyze: str,
        stt_lang_hint: str = "en",
        context_messages: Optional[List[dict]] = None,
        is_first_turn: bool = False,
        **kwargs  # Accept other params for compatibility but ignore them
    ) -> Dict[str, Any]:
        """
        Generate natural conversational response based on user input and context.
        Simplified approach - let the AI decide how to respond naturally.
        """
        try:
            if not text_to_analyze or not text_to_analyze.strip():
                return self._fallback_response(text_to_analyze, stt_lang_hint)

            text = text_to_analyze.strip()
            if len(text) > 800:
                text = text[:800]

            messages = self._build_natural_messages(
                text=text,
                language=stt_lang_hint,
                context_messages=context_messages or [],
                is_first_turn=is_first_turn
            )

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,  # Slightly higher for more natural variation
                "max_tokens": 300,   # Shorter responses are often better
                "response_format": {"type": "json_object"},
            }

            response = self._post_with_retry(payload, retries=2, backoff=2)
            result = self._parse_response(response.json())

            # Ensure consistent language
            result["detected_language"] = stt_lang_hint
            
            # Clean up response to make it more natural
            result = self._post_process_response(result, text, stt_lang_hint)

            return result

        except Exception as e:
            logger.error(f"[Groq] Error: {e}")
            return self._fallback_response(text_to_analyze, stt_lang_hint)

    # ---------- Message Building ----------
    def _build_natural_messages(
        self,
        text: str,
        language: str,
        context_messages: List[dict],
        is_first_turn: bool
    ) -> List[dict]:
        """Build messages for natural conversation"""
        
        system_prompt = self._create_natural_system_prompt(language, is_first_turn)
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent context (increased from 8 to 12 for better context retention)
        if context_messages:
            messages.extend(context_messages[-12:])
        
        # Add current user input
        messages.append({"role": "user", "content": text})
        
        # Debug logging
        logger.info(f"🔧 Groq context: {len(context_messages)} messages, sending {len(messages)} total messages")
        
        return messages

    # def _create_natural_system_prompt(self, language: str, is_first_turn: bool, service_name: str = "caregiving") -> str:
    #     try:
    #         response = requests.get(f"{BACKEND_BASE_URL}/prompt-templates/{service_name}", timeout=5)
    #         if response.status_code == 200:
    #             data = response.json()
    #             return data.get("prompt_template") or self._default_prompt(language, is_first_turn)
    #         else:
    #             logger.warning(f"[Prompt] Template not found for {service_name}, using default")
    #             return self._default_prompt(language, is_first_turn)
    #     except Exception as e:
    #         logger.error(f"[Prompt Fetch Error] {e}")
    #         return self._default_prompt(language, is_first_turn)


    def _create_natural_system_prompt(self, language: str, is_first_turn: bool) -> str:
        """Create a unified system prompt that handles both languages naturally"""
        
        system_prompt = f"""You are a warm, professional receptionist for a caregiving agency. Your goal is to have natural, helpful conversations with callers who need care services.

CORE PRINCIPLES:
1. RESPOND TO WHAT THEY ACTUALLY SAY - Don't force a rigid script
2. BE CONVERSATIONAL - Match their tone and energy
3. GATHER INFO NATURALLY - Ask follow-up questions that flow from their responses
4. SHOW UNDERSTANDING - Acknowledge their specific situation and concerns
5. BE PROACTIVE - When they show interest, guide them toward concrete next steps

SERVICES WE OFFER:
- Companionship and conversation / Compañía y conversación
- Medication reminders / Recordatorios de medicamentos
- Light housekeeping / Limpieza ligera del hogar
- Meal preparation / Preparación de comidas
- Walking/light exercise support / Apoyo para caminar/ejercicio ligero
- Personal care assistance / Asistencia con cuidado personal

CONVERSATION FLOW:
- If they ask a direct question, answer it directly first, then ask a relevant follow-up
- If they share information, acknowledge it specifically before asking for more details
- If they seem unsure or overwhelmed, offer guidance and support
- If they ask "what's next?" or "what do we do now?", be PROACTIVE - guide them toward concrete next steps
- Don't stick rigidly to a predetermined order of questions

PROACTIVE EXAMPLES:
{"English" if language == "en" else "Spanish"} Examples:
Instead of: "{"Can you tell me more about your mom's needs?" if language == "en" else "¿Puede contarme más sobre las necesidades de su mamá?"}"
Try: "{"Let's get you set up! What kind of schedule were you thinking? Some families prefer daily visits, others just a few times a week." if language == "en" else "¡Organicemos esto! ¿Qué tipo de horario estaba pensando? Algunas familias prefieren visitas diarias, otras solo unas veces por semana."}"

Instead of: "{"What else can I help with?" if language == "en" else "¿En qué más puedo ayudarle?"}"
Try: "{"To find the perfect caregiver for your mom, I'll need a few details. What days would work best for visits?" if language == "en" else "Para encontrar el cuidador perfecto para su mamá, necesito algunos detalles. ¿Qué días funcionarían mejor para las visitas?"}"

LANGUAGE RULE: Respond ONLY in {"English" if language == "en" else "Spanish"}. Be warm and professional.

TONE: Warm, empathetic, professional but not robotic. Like a caring neighbor who works in healthcare.

{"FIRST CONVERSATION: This appears to be their first time calling. Take a moment to welcome them warmly and understand their situation before diving into logistics." if is_first_turn else ""}

CRITICAL: Return JSON with these exact keys:
{{
    "original_text": "<original user input>",
    "translated_text": "{"English translation if needed, otherwise same as original" if language == "en" else "traducción al inglés si es necesario, o igual que el original"}",
    "detected_language": "{language}",
    "intent": "inquiry|appointment|urgent|greeting|scheduling|polite_closure|other",
    "urgent": {"true|false only for real emergencies" if language == "en" else "true|false si es una emergencia real"},
    "ai_response": "<your response in {"English" if language == "en" else "español"}>",
    "ai_response_translated": "<your response in English>"
}}

IMPORTANT: Mark "urgent": true ONLY for real emergencies (caregiver no-show, medical emergency). Normal inquiries are NOT urgent.
If they want to end the conversation, mark intent as "polite_closure" but keep your response brief.
When they ask about next steps, be PROACTIVE and help them move forward."""

        return system_prompt

    # def _create_natural_system_prompt(
    #     self,
    #     language: str,
    #     is_first_turn: bool,
    #     company_data: dict | None = None
    # ) -> str:
    #     """Create a unified system prompt that adapts based on business configuration."""

    #     # 🧠 Extract from company_data (fallbacks if missing)
    #     business_type = company_data.get("business_type", "general") if company_data else "general"
    #     tone = company_data.get("tone", "Professional") if company_data else "Professional"
    #     role = company_data.get("role", "Receptionist") if company_data else "Receptionist"
    #     services = company_data.get("services_description") or "General customer support and scheduling."
    #     urgency = company_data.get("urgency", "Normal")

    #     # 🧩 Base intro varies by business type
    #     business_intros = {
    #         "caregiving": "You are a warm, professional receptionist for a caregiving agency. Your goal is to have natural, helpful conversations with callers who need care services.",
    #         "plumbing": "You are a confident, practical assistant for a plumbing business. Your goal is to help customers describe their issue and schedule service quickly.",
    #         "cleaning": "You are a cheerful and professional assistant for a cleaning service. Your goal is to assist clients in booking or learning about cleaning options.",
    #         "general": "You are a helpful, professional virtual receptionist. Your goal is to have natural, helpful conversations with callers about their needs."
    #     }

    #     intro = business_intros.get(business_type.lower(), business_intros["general"])

    #     # 🔹 Full System Prompt Template
    #     system_prompt = f"""
    # {intro}

    # CORE PRINCIPLES:
    # 1. RESPOND TO WHAT THEY ACTUALLY SAY — Don't force a rigid script.
    # 2. BE CONVERSATIONAL — Match their tone and energy.
    # 3. GATHER INFO NATURALLY — Ask follow-up questions that flow from their responses.
    # 4. SHOW UNDERSTANDING — Acknowledge their specific situation and concerns.
    # 5. BE PROACTIVE — When they show interest, guide them toward concrete next steps.

    # SERVICES WE OFFER:
    # {services}

    # TONE: {tone}, empathetic, professional but not robotic. Like a caring neighbor who works in this field.

    # URGENCY HANDLING: {urgency}

    # {"FIRST CONVERSATION: This appears to be their first time calling. Take a moment to welcome them warmly and understand their situation before diving into logistics." if is_first_turn else ""}

    # CRITICAL: Return JSON with these exact keys:
    # {{
    #     "original_text": "<original user input>",
    #     "translated_text": "{"English translation if needed, otherwise same as original" if language == "en" else "traducción al inglés si es necesario, o igual que el original"}",
    #     "detected_language": "{language}",
    #     "intent": "inquiry|appointment|urgent|greeting|scheduling|polite_closure|other",
    #     "urgent": {"true|false only for real emergencies" if language == "en" else "true|false solo para emergencias reales"},
    #     "ai_response": "<your response in {"English" if language == "en" else "español"}>",
    #     "ai_response_translated": "<your response in English>"
    # }}
    # """

    #     return system_prompt.strip()


    # ---------- Response Processing ----------
    def _post_process_response(self, result: Dict[str, Any], user_input: str, language: str) -> Dict[str, Any]:
        """Clean up and improve the response for naturalness"""
        
        ai_response = result.get("ai_response", "")
        
        # Remove overly formal patterns
        ai_response = re.sub(r'^(Perfect[\.!]*\s*[\-—]?\s*)', '', ai_response)
        ai_response = re.sub(r'^(Perfecto[\.!]*\s*[\-—]?\s*)', '', ai_response)
        ai_response = re.sub(r'^(Got it[\-—]\s*)', '', ai_response)
        ai_response = re.sub(r'^(Entendido[\-—]\s*)', '', ai_response)
        
        # Remove redundant confirmations at the start
        ai_response = re.sub(r'^(Thank you for that information\.?\s*)', '', ai_response)
        ai_response = re.sub(r'^(Gracias por esa información\.?\s*)', '', ai_response)
        
        # Clean up multiple spaces and ensure proper capitalization
        ai_response = re.sub(r'\s+', ' ', ai_response).strip()
        if ai_response:
            ai_response = ai_response[0].upper() + ai_response[1:]
        
        # Ensure we have a response
        if not ai_response:
            if language == "es":
                ai_response = "¿En qué puedo ayudarle hoy?"
            else:
                ai_response = "How can I help you today?"
        
        result["ai_response"] = ai_response
        
        # Handle translation
        if language == "es":
            # For Spanish responses, provide English translation
            if not result.get("ai_response_translated"):
                # Simple fallback - in production you might want actual translation
                result["ai_response_translated"] = "How can I help you today?"
        else:
            # For English responses, translation is the same
            result["ai_response_translated"] = ai_response
        
        return result

    # ---------- HTTP & Parsing ----------
    def _post_with_retry(self, payload, retries: int = 2, backoff: float = 2.0):
        """HTTP POST with retry logic for transient errors"""
        last_error = None
        
        for attempt in range(retries + 1):
            try:
                response = requests.post(
                    self.base_url, 
                    headers=self.headers, 
                    json=payload, 
                    timeout=15
                )
                
                if response.status_code == 400:
                    logger.error(f"[Groq 400] payload={json.dumps(payload, ensure_ascii=False)[:500]}")
                    logger.error(f"[Groq 400] response={response.text[:500]}")
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                last_error = e
                status = getattr(response, "status_code", None) if 'response' in locals() else None
                
                # Only retry on transient errors
                transient = status in (429, 500, 502, 503, 504) if status else True
                
                if attempt < retries and transient:
                    wait_time = backoff * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(f"[Groq] Attempt {attempt + 1} failed, retrying in {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    raise last_error
        
        raise last_error

    def _parse_response(self, response: Dict) -> Dict[str, Any]:
        """Parse Groq response and extract JSON"""
        try:
            raw_output = response["choices"][0]["message"]["content"]
            
            # Try direct JSON parsing first
            try:
                parsed = json.loads(raw_output)
            except json.JSONDecodeError:
                # Extract JSON from text if wrapped in other content
                json_match = re.search(r'{.*}', raw_output, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    raise ValueError("No valid JSON found in response")
            
            # Ensure all required keys exist
            return {
                "original_text": parsed.get("original_text", ""),
                "translated_text": parsed.get("translated_text", ""),
                "detected_language": parsed.get("detected_language", "en"),
                "intent": parsed.get("intent", "other"),
                "urgent": bool(parsed.get("urgent", False)),
                "ai_response": parsed.get("ai_response", ""),
                "ai_response_translated": parsed.get("ai_response_translated", "")
            }
            
        except Exception as e:
            logger.error(f"[Groq] Failed to parse response: {e}")
            logger.error(f"[Groq] Raw response: {response}")
            raise

    def _fallback_response(self, text: str, language: str) -> Dict[str, Any]:
        """Fallback response when API fails"""
        
        if language == "es":
            ai_response = "Disculpe, ¿podría repetir eso? Quiero asegurarme de ayudarle de la mejor manera."
            ai_translated = "I'm sorry, could you repeat that? I want to make sure I help you in the best way possible."
        else:
            ai_response = "I'm sorry, could you repeat that? I want to make sure I help you in the best way possible."
            ai_translated = ai_response
        
        return {
            "original_text": text or "",
            "translated_text": text or "",
            "detected_language": language,
            "intent": "clarification_needed",
            "urgent": False,
            "ai_response": ai_response,
            "ai_response_translated": ai_translated,
        }
    
# Create global instance
groq_client = GroqClient()