"""
Mailgun integration for sending outreach emails.
Supports multiple sender addresses: bent@freeboard-advisory.com and bent@christiansen-advisory.com
"""
import logging
import requests
import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY')
MAILGUN_DOMAIN = os.getenv('MAILGUN_DOMAIN', 'mg.freeboard-advisory.com')  # Default fallback
MAILGUN_DOMAIN_FREEBOARD = os.getenv('MAILGUN_DOMAIN_FREEBOARD', MAILGUN_DOMAIN)
MAILGUN_DOMAIN_CHRISTIANSEN = os.getenv('MAILGUN_DOMAIN_CHRISTIANSEN', MAILGUN_DOMAIN)

# Sender addresses and domains
SENDER_ADDRESSES = {
    'freeboard': 'bent@freeboard-advisory.com',
    'christiansen': 'bent@christiansen-advisory.com'
}
SENDER_DOMAINS = {
    'freeboard': MAILGUN_DOMAIN_FREEBOARD,
    'christiansen': MAILGUN_DOMAIN_CHRISTIANSEN
}

def send_email_via_mailgun(
    to_email: str,
    subject: str,
    body: str,
    sender_key: str = 'freeboard',
    reply_to: Optional[str] = None,
    tags: Optional[list] = None
) -> Dict[str, Any]:
    """
    Send an email via Mailgun API.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        body: Email body (plain text or HTML)
        sender_key: Which sender address to use ('freeboard' or 'christiansen')
        reply_to: Optional reply-to address
        tags: Optional list of tags for tracking
    
    Returns:
        Dict with 'success' (bool) and 'message_id' or 'error'
    """
    if not MAILGUN_API_KEY:
        logger.error("MAILGUN_API_KEY not configured")
        return {"success": False, "error": "Mailgun API key not configured"}
    
    sender_email = SENDER_ADDRESSES.get(sender_key, SENDER_ADDRESSES['freeboard'])
    sender_domain = SENDER_DOMAINS.get(sender_key, MAILGUN_DOMAIN)
    if not sender_domain:
        return {"success": False, "error": "Mailgun domain not configured for sender"}
    
    data = {
        "from": f"Bent Christiansen <{sender_email}>",
        "to": to_email,
        "subject": subject,
        "text": body,
        "html": body.replace('\n', '<br>')  # Simple HTML conversion
    }
    
    if reply_to:
        data["h:Reply-To"] = reply_to
    
    if tags:
        data["o:tag"] = tags
    
    try:
        base_url = f"https://api.mailgun.net/v3/{sender_domain}"
        response = requests.post(
            f"{base_url}/messages",
            auth=("api", MAILGUN_API_KEY),
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('id', 'unknown')
            logger.info(f"✅ Email sent successfully via Mailgun: {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "sender": sender_email
            }
        else:
            error_msg = f"Mailgun API error: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
    except Exception as e:
        error_msg = f"Failed to send email via Mailgun: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

def choose_sender_address(company_name: str, contact_name: str) -> str:
    """
    Intelligently choose which sender address to use based on context.
    Can be enhanced with rules like:
    - Use freeboard for healthcare/payer companies
    - Use christiansen for fintech/general SaaS
    - Rotate based on volume
    """
    # Simple rotation for now - can be enhanced
    # For now, default to freeboard
    return 'freeboard'
