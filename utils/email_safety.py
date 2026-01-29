import re
import logging
import os

logger = logging.getLogger(__name__)

# Configuration
ENABLE_AI_CONTENT_DETECTION = os.getenv('ENABLE_AI_CONTENT_DETECTION', 'true').lower() == 'true'
AUTO_SANITIZE_CONTRAST = os.getenv('AUTO_SANITIZE_CONTRAST', 'true').lower() == 'true'
HARD_REJECT_OUTREACH = os.getenv('HARD_REJECT_OUTREACH', 'false').lower() == 'true'

def strip_unresolved_placeholders(text: str, allowlist: set[str] | None = None) -> str:
    """
    Removes unresolved template placeholders before LLM generation.
    Example: [job], [company], {role}, {{title}}
    """
    if not text:
        return ""

    allowlist = {token.lower() for token in (allowlist or set())}

    def _strip_if_not_allowed(match: re.Match) -> str:
        token = match.group(1).lower()
        return match.group(0) if token in allowlist else ''

    # Common placeholder formats: [token], {token}, {{token}}
    # Allow spaces inside tokens like [sender profile]
    text = re.sub(r'\[([A-Za-z_][A-Za-z0-9_ ]*[A-Za-z0-9_])\]', _strip_if_not_allowed, text)
    text = re.sub(r'\{([A-Za-z_][A-Za-z0-9_ ]*[A-Za-z0-9_])\}', _strip_if_not_allowed, text)
    text = re.sub(r'\{\{([A-Za-z_][A-Za-z0-9_ ]*[A-Za-z0-9_])\}\}', _strip_if_not_allowed, text)
    return text

def sanitize_email_text(text: str) -> str:
    """
    Sanitizes email draft text by removing pesky markdown artifacts,
    citation brackets, and AI-generated content markers common in LLM outputs.
    
    1. Removes markdown emphasis (**bold**, __bold__, *italic*, _italic_)
    2. Removes bracket citations like [1], [12], [1][2]
    3. Removes placeholder tokens like [proof], [source]
    4. Removes AI-generated content markers (em dashes, etc.)
    5. Normalizes whitespace
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

    # 3b. Remove unresolved template placeholders if any slipped through
    # Allow [Name] to survive so salutation patching can still work.
    text = strip_unresolved_placeholders(text, allowlist={"name"})
    # Remove bracketed artifacts with spaces or known placeholder keywords
    placeholder_keywords = r'(sender|profile|job|role|company|title|contact|email|linkedin|template)'
    text = re.sub(r'\[[^\]]*\s+[^\]]*\]', '', text)
    text = re.sub(rf'\[[^\]]*{placeholder_keywords}[^\]]*\]', '', text, flags=re.IGNORECASE)

    # 4. Remove AI-Generated Content Markers (if enabled)
    if ENABLE_AI_CONTENT_DETECTION:
        text = _remove_ai_content_markers(text)
        if AUTO_SANITIZE_CONTRAST:
            text = _rewrite_contrastive_framing(text)

    # 5. Normalize Whitespace
    # Strip trailing spaces on lines
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    # Collapse 3+ newlines to 2 (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def _remove_ai_content_markers(text: str) -> str:
    """
    Removes common AI-generated content markers that make emails sound artificial.
    
    Focus areas:
    1. Em dashes (—) - replace with regular hyphens or remove
    2. En dashes (–) - replace with regular hyphens  
    3. Other AI-typical punctuation patterns
    4. Overly formal transitions
    """
    if not text:
        return text
    
    # 1. Replace em dashes (—) with regular hyphens or contextually appropriate alternatives
    # Pattern: "word—word" -> "word - word" (with spaces)
    text = re.sub(r'(\w)—(\w)', r'\1 - \2', text)
    
    # Pattern: "phrase—and" -> "phrase, and" (common AI pattern)
    text = re.sub(r'—(and|but|or|so|yet)', r', \1', text)
    
    # Pattern: "Company—congrats" -> "Company - congrats" 
    text = re.sub(r'([A-Z][a-z]+)—([a-z])', r'\1 - \2', text)
    
    # Pattern: remaining standalone em dashes -> regular dash with spaces
    text = re.sub(r'—', ' - ', text)
    
    # 2. Replace en dashes (–) with regular hyphens
    text = re.sub(r'–', '-', text)
    
    # 3. Remove other AI-typical markers
    # Double spaces that might result from replacements
    text = re.sub(r'  +', ' ', text)
    
    # AI-typical formal transitions (optional - be careful not to over-sanitize)
    ai_transitions = [
        r'\bI trust this finds you well\b',
        r'\bI hope this message finds you well\b', 
        r'\bI hope this email finds you in good health\b',
        r'\bI trust you are doing well\b'
    ]
    
    for pattern in ai_transitions:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    return text

def _rewrite_contrastive_framing(text: str) -> str:
    """
    Minimal rewrite to remove contrastive framing.
    Prefer dropping the negated clause and keeping the "Y" clause.
    """
    if not text:
        return text

    patterns = [
        # "not X but Y" -> "Y"
        (r'\bnot\b[^.?!]*\bbut\b\s+([^.!?]+)', r'\1'),
        # "less ... more Y" -> "Y"
        (r'\bless\b[^.?!]*\bmore\b\s+([^.!?]+)', r'\1'),
        # "wasn't X it/that Y" -> "Y"
        (r"\bwasn[’']t\b[^.?!]*\b(?:it|that)\b\s+([^.!?]+)", r'\1'),
        # "not X - it/that Y" -> "Y"
        (r'\bnot\b[^.?!]*[—–-]\s*\b(?:it|that)\b\s+([^.!?]+)', r'\1'),
    ]

    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text

def detect_ai_content_markers(text: str) -> list[str]:
    """
    Detects potential AI-generated content markers in email text.
    Returns list of detected issues for logging/debugging.
    """
    markers = []
    if not text:
        return markers
    
    # Check for em dashes
    if '—' in text:
        markers.append("contains_em_dash")
        
    # Check for en dashes  
    if '–' in text:
        markers.append("contains_en_dash")
        
    # Check for AI-typical formal openings
    formal_patterns = [
        r'\bI trust this finds you well\b',
        r'\bI hope this message finds you well\b',
        r'\bI hope this email finds you in good health\b'
    ]
    
    for pattern in formal_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            markers.append("contains_formal_ai_opening")
            break
    
    # Check for excessive use of em dashes (more than 2 is very suspicious)
    em_dash_count = text.count('—')
    if em_dash_count > 2:
        markers.append(f"excessive_em_dashes_{em_dash_count}")
    
    # Check for AI-typical sentence structures
    if re.search(r'\w+—\w+', text):
        markers.append("em_dash_word_connector")

    # Check for unresolved bracket artifacts (placeholders leaked)
    if re.search(r'\[[^\]]*\s+[^\]]*\]', text):
        markers.append("unresolved_placeholder")
    if re.search(r'\[[^\]]*(sender|profile|job|role|company|title|contact|email|linkedin|template)[^\]]*\]', text, flags=re.IGNORECASE):
        markers.append("unresolved_placeholder")

    # Check for contrastive framing
    contrast_patterns = [
        r'\bnot\b.+\bbut\b',
        r'\bless\b.+\bmore\b',
        r"\bwasn[’']t\b.+\b(it|that)\b",
        r'\bnot\b.+[—–-]\s*\b(it|that)\b',
    ]
    if any(re.search(p, text, flags=re.IGNORECASE) for p in contrast_patterns):
        markers.append("contrastive_framing")

    # Check for job-posting references (role-framing error)
    job_posting_patterns = [
        r'\bjob posting\b',
        r'\bjob description\b',
        r'\brole description\b',
        r'\bthe job mentions\b',
        r'\bthe posting\b',
        r'\bhiring (for|to)\b',
        r'\bopen role\b'
    ]
    if any(re.search(p, text, flags=re.IGNORECASE) for p in job_posting_patterns):
        markers.append("job_posting_reference")

    # Cap question count to preserve authority (exactly 1 strategic question)
    question_marks = text.count('?')
    if question_marks != 1:
        markers.append(f"question_count_{question_marks}")

    # Enforce question placement (first third) and hypothesis-check wording
    if question_marks >= 1:
        q_idx = text.find('?')
        if len(text) > 0 and q_idx / max(len(text), 1) > 0.33:
            markers.append("question_too_late")
        hypothesis_patterns = [
            r'\bam I reading this (right|correctly)\b',
            r'\bsound right\?\b',
            r'\bis that right\?\b',
            r'\bdoes that sound right\?\b',
            r'\bam I off base\?\b',
        ]
        if not any(re.search(p, text, flags=re.IGNORECASE) for p in hypothesis_patterns):
            markers.append("missing_hypothesis_question")
        if re.search(r'\bdoes this resonate\?\b', text, flags=re.IGNORECASE):
            markers.append("avoid_resonate_closer")
    
    # Check for overly authoritative tone
    authoritative_markers = detect_authoritative_tone(text)
    markers.extend(authoritative_markers)
        
    return markers

def detect_authoritative_tone(text: str) -> list[str]:
    """
    Detects overly authoritative language that sounds presumptuous or lecturing.
    Senior consultative sellers use questions, not assertions about client strategy.
    """
    markers = []
    if not text:
        return markers
    
    # Authoritative phrases that sound presumptuous
    authoritative_patterns = [
        (r'\bwill be (key|critical|essential|important|crucial) (to|for)', "prescriptive_will_be"),
        (r'\bmust (focus|prioritize|address|build|create)', "prescriptive_must"),
        (r'\bneeds? to (focus|prioritize|address|build|create)', "prescriptive_needs"),
        (r'\bshould (focus|prioritize|address|build|create)', "prescriptive_should"),
        (r'\bis critical (to|for)', "prescriptive_is_critical"),
        (r'\brequires (building|creating|focusing|addressing)', "prescriptive_requires"),
        (r'\bthe challenge is\b', "assertive_challenge"),
        (r'\bsuccess requires\b', "prescriptive_success"),
    ]
    
    # Check each pattern, but consider context
    for pattern, marker_name in authoritative_patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        for match in matches:
            # Get context around the match (100 chars after)
            start_pos = match.start()
            end_pos = min(match.end() + 100, len(text))
            context = text[start_pos:end_pos]
            
            # If there's a question mark nearby (within 100 chars), it's likely consultative
            if '?' not in context:
                # Only flag if NOT followed by a question
                markers.append(marker_name)
                break  # Only flag once per pattern type
    
    # Check for lack of questions (authoritative emails often don't ask questions)
    question_marks = text.count('?')
    sentences = len(re.findall(r'[.!?]+', text))
    
    # If email has 3+ sentences but no questions, that's suspicious
    if sentences >= 3 and question_marks == 0:
        markers.append("no_questions_consultative_miss")
    
    # Check for consultative/curious markers (good things - absence is bad)
    consultative_patterns = [
        r'\bam I reading this (right|correctly)',
        r'\bdoes (that|this) resonate',
        r'\bis that (the challenge|something you\'re)',
        r'\bseeing that\?',
        r'\bsound right\?',
        r'\bcurious (if|whether|how)',
        r'\bI\'m wondering',
        r'\bmy sense is',
        r'\bseems like',
        r'\bit seems (like|that)',
        r'\bcould be wrong',
        r'\bmight not be relevant'
    ]
    
    has_consultative = any(re.search(p, text, flags=re.IGNORECASE) for p in consultative_patterns)
    
    # If authoritative language present but no consultative markers, flag it
    if markers and not has_consultative:
        markers.append("authoritative_without_curiosity")
    
    return markers

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
    
    # Check for AI content markers (warning level - not blocking, if enabled)
    if ENABLE_AI_CONTENT_DETECTION:
        ai_markers = detect_ai_content_markers(text)
        if ai_markers:
            reasons.extend([f"ai_marker_{marker}" for marker in ai_markers])
            # Log AI markers as warnings but don't block sending
            logger.warning(f"AI Content Markers Detected: {ai_markers} | Snippet: {text[:200]}")

        # Optional hard reject for outreach hygiene
        if HARD_REJECT_OUTREACH and ai_markers:
            block_markers = {
                "contains_em_dash",
                "contains_en_dash",
                "contrastive_framing",
                "job_posting_reference",
                "unresolved_placeholder",
                "question_count_0",
                "question_count_2",
                "question_count_3",
                "question_too_late",
                "missing_hypothesis_question",
            }
            if any(m in block_markers or m.startswith("question_count_") for m in ai_markers):
                logger.warning(f"Hard-reject triggered: {ai_markers}")
                return False, [f"hard_reject_{m}" for m in ai_markers]
    
    # Only block on critical issues (not AI markers)
    critical_reasons = [r for r in reasons if not r.startswith("ai_marker_")]
    
    if critical_reasons:
        # Log failure
        logger.warning(f"Email Validation Failed: {critical_reasons} | Snippet: {text[:200]}")
        return False, critical_reasons
        
    return True, reasons  # Return all reasons including AI markers for logging
