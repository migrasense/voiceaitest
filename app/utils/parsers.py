# parsers.py - Enhanced version

import re
from typing import Optional, List

def extract_phone(text: str) -> Optional[str]:
    """
    Enhanced phone number extraction with better pattern matching.
    Accepts various formats and returns normalized digits-only format.
    """
    # Remove common words that might interfere
    cleaned_text = re.sub(r'\b(phone|number|call|contact|reach|at)\b', '', text.lower())
    
    # Comprehensive phone pattern
    phone_patterns = [
        r'(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})',  # US format with optional +1
        r'(\d{3})[-.\s]?(\d{3})[-.\s]?(\d{4})',  # XXX-XXX-XXXX or similar
        r'(\(?\d{3}\)?)\s*(\d{3})\s*(\d{4})',    # (XXX) XXX XXXX
        r'\b(\d{10})\b',                         # 10 digits together
    ]
    
    for pattern in phone_patterns:
        matches = re.finditer(pattern, cleaned_text)
        for match in matches:
            # Extract all digits
            phone_digits = re.sub(r'\D', '', match.group())
            
            # Handle US numbers (remove leading 1 if present)
            if len(phone_digits) == 11 and phone_digits.startswith('1'):
                phone_digits = phone_digits[1:]
            
            # Validate length
            if len(phone_digits) == 10:
                return phone_digits
    
    return None


def extract_name(text: str) -> Optional[str]:
    """
    Enhanced name extraction with multiple patterns and validation.
    """
    # Clean the text - remove common filler words
    cleaned_text = re.sub(r'\b(um|uh|like|you know|well)\b', '', text, flags=re.IGNORECASE)
    
    name_patterns = [
        # Direct statements
        r"(?:my name is|i am|this is|i'm|im)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        # Possessive forms
        r"(?:my name's|name's)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        # Application context
        r"(?:applied as|application for|under the name)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        # General capitalized names (be careful with this one)
        r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b"
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            potential_name = match.group(1).strip()
            
            # Validate the extracted name
            if _is_valid_name(potential_name):
                return potential_name
    
    return None


def _is_valid_name(name: str) -> bool:
    """
    Validate if extracted text is likely a real name.
    """
    # Basic checks
    if not name or len(name.split()) > 4:  # Too many words
        return False
    
    # Common words that aren't names
    non_names = {
        'help', 'please', 'thank', 'thanks', 'hello', 'hi', 'yes', 'no',
        'okay', 'ok', 'sure', 'application', 'status', 'job', 'position',
        'phone', 'number', 'email', 'address', 'today', 'yesterday',
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
    }
    
    name_words = name.lower().split()
    if any(word in non_names for word in name_words):
        return False
    
    # Should have at least 2 characters per word
    if any(len(word) < 2 for word in name_words):
        return False
    
    return True


def extract_application_context(text: str) -> dict:
    """
    Extract additional context that might be relevant for job applications.
    """
    context = {
        'position_mentioned': None,
        'urgency_indicators': [],
        'timeframe_mentioned': None,
        'contact_preference': None
    }
    
    # Position/job titles
    position_patterns = [
        r"(?:applied for|position|job|role)\s+([a-zA-Z\s]+?)(?:\s|$|\.)",
        r"(?:the\s+)?(nurse|doctor|assistant|manager|supervisor|coordinator|technician|aide)",
    ]
    
    for pattern in position_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            context['position_mentioned'] = match.group(1).strip()
            break
    
    # Urgency indicators
    urgency_words = ['urgent', 'asap', 'immediately', 'soon', 'quickly', 'emergency']
    context['urgency_indicators'] = [word for word in urgency_words if word in text.lower()]
    
    # Timeframe mentions
    timeframe_patterns = [
        r"(yesterday|today|tomorrow|this week|last week|next week)",
        r"(\d+\s+(?:days?|weeks?|months?)\s+ago)",
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    ]
    
    for pattern in timeframe_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            context['timeframe_mentioned'] = match.group(1)
            break
    
    # Contact preference
    if re.search(r'\b(?:call|phone|text)\b', text, re.IGNORECASE):
        context['contact_preference'] = 'phone'
    elif re.search(r'\b(?:email|mail)\b', text, re.IGNORECASE):
        context['contact_preference'] = 'email'
    
    return context


def smart_extract_info(text: str) -> dict:
    """
    Smart extraction that combines all methods and provides confidence scores.
    """
    return {
        'phone': extract_phone(text),
        'name': extract_name(text),
        'context': extract_application_context(text),
        'original_text': text.strip(),
        'confidence': _calculate_confidence(text)
    }


def _calculate_confidence(text: str) -> dict:
    """
    Calculate confidence scores for different types of information.
    """
    confidence = {
        'has_phone': 0.0,
        'has_name': 0.0,
        'is_job_inquiry': 0.0
    }
    
    # Phone confidence
    if re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', text):
        confidence['has_phone'] = 0.9
    elif re.search(r'\d{10}', text):
        confidence['has_phone'] = 0.8
    elif any(char.isdigit() for char in text):
        confidence['has_phone'] = 0.3
    
    # Name confidence
    name_indicators = ['my name is', 'i am', 'this is', 'i\'m']
    if any(indicator in text.lower() for indicator in name_indicators):
        confidence['has_name'] = 0.8
    elif re.search(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b', text):
        confidence['has_name'] = 0.6
    
    # Job inquiry confidence
    job_keywords = ['application', 'applied', 'job', 'position', 'status', 'interview', 'hiring']
    keyword_count = sum(1 for keyword in job_keywords if keyword in text.lower())
    confidence['is_job_inquiry'] = min(keyword_count * 0.3, 1.0)
    
    return confidence