from fastapi import APIRouter, Request
from typing import Optional
from app.db.supabase import supabase
from app.core.config import logger

router = APIRouter(prefix="/job-application", tags=["Job Applications"])

@router.post("/status")
async def check_application_status(request: Request):
    """
    Check the status of a job application by phone number or name.
    """
    body = await request.json()
    phone = body.get("phone")
    name = body.get("name")

    if not phone and not name:
        return {"error": "Must provide either phone or name"}

    try:
        query = supabase.table("job_applications").select("*")
        if phone:
            query = query.eq("phone_number", phone)
        elif name:
            query = query.ilike("name", f"%{name}%")

        response = query.execute()
        if not response.data:
            return {"status": "not_found", "message": "No application found"}

        app = response.data[0]  # take the first match

        return {
            "status": "success",
            "application": {
                "id": app["id"],
                "name": app["name"],
                "phone_number": app["phone_number"],
                "position": app["position"],
                "status": app["status"],
                "last_contact": app["last_contact"],
                "notes": app.get("notes")
            }
        }

    except Exception as e:
        logger.error(f"Job application lookup failed: {str(e)}")
        return {"error": "Database lookup failed", "details": str(e)}
