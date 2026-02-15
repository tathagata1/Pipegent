import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional


def email_sender(
    smtp_host: str,
    smtp_port: int,
    from_address: str,
    to_addresses: List[str],
    subject: str,
    body: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: bool = True,
    use_ssl: bool = False,
) -> Dict[str, str]:
    if not to_addresses:
        raise ValueError("to_addresses must include at least one recipient.")

    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(to_addresses)
    message["Subject"] = subject
    message.set_content(body)

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, int(smtp_port), timeout=20)
        else:
            server = smtplib.SMTP(smtp_host, int(smtp_port), timeout=20)

        with server:
            if not use_ssl and use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            response = server.send_message(message)
    except smtplib.SMTPException as exc:
        raise ConnectionError(f"SMTP error: {exc}") from exc

    rejected = list(response.keys()) if isinstance(response, dict) else []
    return {
        "status": "sent" if not rejected else "partial",
        "recipients_sent": ", ".join(addr for addr in to_addresses if addr not in rejected),
        "recipients_rejected": ", ".join(rejected),
    }
