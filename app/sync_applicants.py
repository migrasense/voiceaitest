import os, httpx, time
from datetime import datetime, timedelta, timezone
from dateutil.parser import isoparse
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
AGENCY_ID = os.getenv("AGENCY_ID", "wondercare")

AXISCARE_SITE = os.environ["AXISCARE_SITE"]
AXISCARE_VERSION = os.getenv("AXISCARE_VERSION", "v1")
AXISCARE_BASE = f"https://{AXISCARE_SITE}.axiscare.com/api/{AXISCARE_VERSION}"
AXISCARE_TOKEN = os.environ["AXISCARE_TOKEN"]

PAGE_SIZE = 200

def axis_headers():
    # If AxisCare uses a different header than Bearer, change it here
    return {"Authorization": f"Bearer {AXISCARE_TOKEN}", "Accept": "application/json"}

def normalize(row: dict) -> dict:
    # Map AxisCare → your schema (adjust field names as needed)
    first = (row.get("first_name") or "").strip()
    last  = (row.get("last_name") or "").strip()
    status = row.get("status") or "unknown"
    status_label = (row.get("status", {}) or {}).get("label")
    status_norm = "active" if (row.get("status", {}).get("active") is True) else "inactive"
    created = row.get("created_at") or datetime.now(timezone.utc).isoformat()

    return {
        "id": str(row.get("id")),
        "agency_id": AGENCY_ID,
        "first_name": first,
        "last_name": last,
        "phone": row.get("phone"),
        "email": row.get("email"),
        "status": status,
        "status_label": status_label or status_norm.capitalize(),
        "created_at": created,
        "tags": row.get("tags") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "axiscare",
        "raw": row
    }

def get_updated_since() -> str:
    # Strategy: pull from the most recent updated_at in Supabase to do incremental sync
    # If empty, backfill last 90 days.
    sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    res = sb.table("applicants").select("updated_at").order("updated_at", desc=True).limit(1).execute()
    if res.data:
        dt = isoparse(res.data[0]["updated_at"])
        return dt.astimezone(timezone.utc).isoformat()
    return (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

def upsert_batch(rows: list[dict]):
    if not rows:
        return
    sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    # upsert by primary key id
    sb.table("applicants").upsert(rows, on_conflict="id").execute()

def fetch_axiscare_page(client: httpx.Client, offset: int, updated_since: str | None):
    params = {"limit": PAGE_SIZE, "offset": offset}
    if updated_since:
        params["updated_since"] = updated_since
    r = client.get(f"{AXISCARE_BASE}/applicants", params=params)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return []

def main():
    updated_since = get_updated_since()
    print(f"[sync] incremental since: {updated_since}")

    with httpx.Client(timeout=30, headers=axis_headers()) as c:
        offset = 0
        total = 0
        while True:
            batch = fetch_axiscare_page(c, offset, updated_since)
            if not batch:
                break
            normalized = [normalize(b) for b in batch if b.get("id")]
            upsert_batch(normalized)
            count = len(normalized)
            total += count
            print(f"[sync] upserted {count} (offset={offset})")
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            time.sleep(0.2)  # polite pacing
    print(f"[sync] done. total upserted: {total}")

if __name__ == "__main__":
    main()
