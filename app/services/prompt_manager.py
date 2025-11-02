import asyncio
from datetime import datetime, timedelta
from app.db.supabase import supabase
from app.core.config import logger

class PromptManager:
    def __init__(self):
        # Cache format: { company_id: { data: dict, ts: datetime } }
        self._cache = {}
        self._lock = asyncio.Lock()

    async def get_prompt(self, company_id: str, office_id: str | None = None):
        """
        Fetch prompt-related data from cache or Supabase.
        Returns a dict:
        {
            "prompt_template": str or None,
            "services_description": str or None,
            "tone": str,
            "role": str,
            "urgency": str,
            "business_type": str,
            "key_terms": dict
        }
        """
        if not company_id:
            return self._default_data()

        async with self._lock:
            cached = self._cache.get(company_id)
            if cached and datetime.now() - cached["ts"] < timedelta(minutes=10):
                return cached["data"]

            try:
                loop = asyncio.get_running_loop()
                def _query():
                    q = (
                        supabase.table("service_configs")
                        .select(
                            "prompt_template, services_description, tone, role, "
                            "default_urgency, business_type, key_terms"
                        )
                        .eq("company_id", company_id)
                    )
                    # 👇 Add office_id filter only if provided
                    if office_id:
                        q = q.eq("office_id", office_id)
                    return q.execute()

                result = await loop.run_in_executor(None, _query)

                if result.data and len(result.data) > 0:
                    record = result.data[0]
                    data = {
                        "prompt_template": record.get("prompt_template"),
                        "services_description": record.get("services_description"),
                        "tone": record.get("tone", "Professional"),
                        "role": record.get("role", "Receptionist"),
                        "urgency": record.get("default_urgency", "Normal"),
                        "business_type": record.get("business_type", "general"),
                        "key_terms": record.get("key_terms") or {},
                    }

                    # cache for 10 minutes
                    self._cache[company_id] = {"data": data, "ts": datetime.now()}
                    return data

                else:
                    logger.warning(f"No prompt found for company_id={company_id}, office_id={office_id}")
                    return self._default_data()

            except Exception as e:
                logger.error(f"Supabase prompt fetch failed: {e}")
                return self._default_data()


    def _default_prompt(self, business_type: str = "general"):
        """Default tone/prompt message depending on business type."""
        tone_map = {
            "caregiving": "You are a warm, compassionate receptionist for a home care agency.",
            "plumbing": "You are a confident, practical assistant for a plumbing business.",
            "cleaning": "You are a cheerful and professional assistant for a home cleaning service.",
            "dental": "You are a polite and knowledgeable receptionist for a dental office.",
            "other": "You are a warm, professional virtual receptionist for a small business."
        }
        return tone_map.get(business_type.lower(), tone_map["other"])

    def _default_data(self):
        """Default fallback dataset when Supabase or cache miss occurs."""
        return {
            "prompt_template": None,
            "services_description": (
                "- Companionship and conversation / Compañía y conversación\n"
                "- Medication reminders / Recordatorios de medicamentos\n"
                "- Light housekeeping / Limpieza ligera del hogar\n"
                "- Meal preparation / Preparación de comidas\n"
                "- Walking/light exercise support / Apoyo para caminar/ejercicio ligero\n"
                "- Personal care assistance / Asistencia con cuidado personal"
            ),
            "tone": "Warm",
            "role": self._default_prompt(),
            "urgency": "Normal",
            "business_type": "caregiving",
            "key_terms": {
                "customer": "client",
                "service": "caregiver",
                "visit": "visit"
            },
        }
