"""
Mailgun integration for sending outreach emails.
Supports multiple sender addresses: bent@freeboard-advisory.com and bent@christiansen-advisory.com
"""
import logging
import json
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

# Default BCC for auditing
DEFAULT_BCC_EMAIL = 'bent@freeboard-advisory.com'

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
    tags: Optional[list] = None,
    extra_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Send an email via Mailgun API using Batch Sending.
    Recipients (including audit logs) are explicit in 'to' but isolated via 'recipient-variables'.
    """
    # Force reload config to pick up .env changes without server restart
    load_dotenv(override=True)
    import config  # Local import to avoid circular dependency
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN', 'mg.freeboard-advisory.com')
    
    # Resolve domain based on sender key
    if sender_key == 'freeboard':
        domain = os.getenv('MAILGUN_DOMAIN_FREEBOARD', domain)
    elif sender_key == 'christiansen':
        domain = os.getenv('MAILGUN_DOMAIN_CHRISTIANSEN', domain)
        
    sender_addresses = {
        'freeboard': 'bent@freeboard-advisory.com',
        'christiansen': 'bent@christiansen-advisory.com'
    }
    
    if not api_key:
        logger.error("MAILGUN_API_KEY not configured")
        return {"success": False, "error": "Mailgun API key not configured"}
    
    sender_email = sender_addresses.get(sender_key, sender_addresses['freeboard'])
    
    if not domain:
        return {"success": False, "error": "Mailgun domain not configured for sender"}

    # Prepare detailed recipient list (Primary + Audit)
    recipients = [to_email]
    if hasattr(config, 'DEFAULT_BCC_EMAIL') and config.DEFAULT_BCC_EMAIL:
        # User requested explicit "To" sending for audit logs
        # Using Batch Sending to keep them invisible to each other
        if config.DEFAULT_BCC_EMAIL != to_email:
            recipients.append(config.DEFAULT_BCC_EMAIL)

    # Magic: recipient-variables triggers Batch Sending (individual emails)
    # This ensures "to_email" doesn't see "audit_email" etc.
    # Use empty dict as per "world-class" recommendation
    recipient_vars = {r: {} for r in recipients}

    data = {
        "from": f"Bent Christiansen <{sender_email}>",
        "to": recipients, # Requests handles list by sending multiple 'to' params
        "subject": subject,
        "text": body,
        "html": body.replace('\n', '<br>'),
        "recipient-variables": json.dumps(recipient_vars)
    }
    
    if reply_to:
        data["h:Reply-To"] = reply_to
    
    if tags:
        data["o:tag"] = tags
        
    if extra_headers:
        for k, v in extra_headers.items():
            if k.startswith("X-") or k.startswith("h:"):
                key = k if k.startswith("h:") else f"h:{k}"
                data[key] = v
    
    try:
        base_url = f"https://api.mailgun.net/v3/{domain}"
        response = requests.post(
            f"{base_url}/messages",
            auth=("api", MAILGUN_API_KEY),
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('id', 'unknown')
            logger.info(f"✅ Email sent successfully via Mailgun (Batch): {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "sender": sender_email,
                "sent_to": recipients  # Return exact list for audit logging
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
def send_mailgun_test_email() -> Dict[str, Any]:
    """
    Sends a smoke test email using the production domain configuration.
    """
    load_dotenv(override=True)
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN_SALES', os.getenv('MAILGUN_DOMAIN'))
    from_addr = os.getenv('MAILGUN_FROM_BENT', f"bent@{domain}")
    to_addr = os.getenv('MAILGUN_TEST_RECIPIENT', from_addr)
    
    if not api_key:
        return {"success": False, "error": "Missing MAILGUN_API_KEY"}
    
    try:
        url = f"https://api.mailgun.net/v3/{domain}/messages"
        response = requests.post(
            url,
            auth=("api", api_key),
            data={
                "from": from_addr,
                "to": [to_addr],
                "subject": "🚀 Mailgun smoke test from Cockpit",
                "text": f"If you see this, Mailgun for {domain} is wired correctly.\n\nTimestamp: {os.popen('date').read().strip()}",
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return {"success": True, "data": response.json()}
        else:
            return {"success": False, "error": f"{response.status_code}: {response.text}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}
