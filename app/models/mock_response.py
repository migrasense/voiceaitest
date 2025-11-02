from datetime import datetime

MOCK_RESPONSES = {
    "hello": {
        "transcript": "Hello, how are you?",
        "intent": "greeting",
        "ai_response": "I'm doing well, thanks for asking!",
        "language": "en",
        "urgent": False
    },
    "help": {
        "transcript": "I need help with billing",
        "intent": "billing_issue",
        "ai_response": "I'll connect you with our billing department.",
        "language": "en",
        "urgent": False
    },
    "emergency": {
        "transcript": "This is an emergency!",
        "intent": "urgent",
        "ai_response": "Please hold while I connect you to emergency services.",
        "language": "en",
        "urgent": True
    },
    "default": {
        "transcript": "I didn't understand that",
        "intent": "other",
        "ai_response": "Could you please rephrase that?",
        "language": "en",
        "urgent": False
    },
    "application": {
        "transcript": "Can you check my job application?",
        "intent": "job_application_status",
        "ai_response": "Sure, I can help with that. Could you please provide your full name or phone number?",
        "language": "en",
        "urgent": False
    },

}
