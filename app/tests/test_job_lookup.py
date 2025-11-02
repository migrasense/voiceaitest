import asyncio
from app.services.transcript_service import process_final_transcript

async def run_tests():
    test_cases = [
        "I want to follow up on my job application. My name is Maria Johnson",
        "Can you check my application? My phone is 501-444-5566",
        "I applied as a Nurse Assistant, phone number 5014445566",
        "Check my application, name is Anna Cruz"    ]

    for case in test_cases:
        print(f"\n--- Test: {case}")
        session_id, entry = await process_final_transcript(case)
        print(f"Session ID: {session_id}")
        print(f"Transcript: {entry['transcript']}")
        print(f"AI Response: {entry['ai_response']}")

if __name__ == "__main__":
    asyncio.run(run_tests())
