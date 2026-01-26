import re
import logging

logger = logging.getLogger(__name__)

def sanitize_email_text(text: str) -> str:
    """
    Sanitizes email draft text by removing pesky markdown artifacts
    and citation brackets common in LLM outputs.
    
    1. Removes markdown emphasis (**bold**, __bold__, *italic*, _italic_)
    2. Removes bracket citations like [1], [12], [1][2]
    3. Removes placeholder tokens like [proof], [source]
    4. Normalizes whitespace
    """
    if not text:
        return ""

    # 1. Remove Markdown Emphasis Wrappers
    # Convert **text** -> text
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    # Convert __text__ -> text
    text = re.sub(r'__(.*?)__', r'\1', text)
    # Convert *text* -> text (paired only, avoid bullet points)
    # This regex looks for * not at start of line (to avoid list bullets)
    # or ensures it's wrapped around content.
    # Simplest safe approach: replace *content* but not * at start of line
    text = re.sub(r'(?<!^)(?<!\n)\*(.*?)\*', r'\1', text)
    # Convert _text_ -> text
    text = re.sub(r'_(.*?)_', r'\1', text)

    # 2. Remove Bracket Citations
    # Remove [1], [12], [1][2]
    # Regex: \[ \d+ \]
    text = re.sub(r'\[\d+\]', '', text)
    
    # 3. Remove Placeholder Tokens
    # [proof], [source], [citation], [TODO] - case insensitive
    placeholders = r'\[(proof|source|citation|todo)\]'
    text = re.sub(placeholders, '', text, flags=re.IGNORECASE)

    # 4. Normalize Whitespace
    # Strip trailing spaces on lines
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    # Collapse 3+ newlines to 2 (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def validate_send_safe(text: str) -> tuple[bool, list[str]]:
    """
    Validates if the text is safe to send (no artifacts remaining).
    Returns (is_safe, reasons_list).
    """
    reasons = []
    if not text:
        return False, ["empty_text"]

    # Check for Markdown emphasis artifacts
    if re.search(r'\*\*.*?\*\*', text) or re.search(r'__.*?__', text):
        reasons.append("contains_markdown_emphasis")
        
    # Check for bracket citations
    if re.search(r'\[\d+\]', text):
        reasons.append("contains_bracket_citations")
        
    # Check for placeholder tokens
    if re.search(r'\[(proof|source|citation|todo)\]', text, flags=re.IGNORECASE):
        reasons.append("contains_placeholders")
    
    if reasons:
        # Log failure
        logger.warning(f"Email Validation Failed: {reasons} | Snippet: {text[:200]}")
        return False, reasons
        
    return True, []
