"""Gmail SMTP email service.

Uses a Gmail address + App Password (set SMTP_EMAIL and SMTP_PASSWORD in .env).
To create an App Password:  Google Account → Security → 2-Step Verification → App passwords
"""

import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import os
from app.config import contracts_collection, notifications_collection
from bson import ObjectId


def _smtp_email() -> str:
    """Read SMTP_EMAIL fresh from the environment every time (never stale)."""
    return os.getenv("SMTP_EMAIL", "")


def _smtp_password() -> str:
    """Read SMTP_PASSWORD fresh from the environment every time (never stale)."""
    return os.getenv("SMTP_PASSWORD", "")


# ── HTML email templates ──────────────────────────────────────────────────────

def _base_template(title: str, body_html: str, footer: str = "") -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 0;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6d28d9,#7c3aed);padding:28px 36px;">
            <p style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:-.5px;">Clause</p>
            <p style="margin:6px 0 0;color:rgba(255,255,255,.75);font-size:13px;">Contract Lifecycle Management</p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px;">
            <h2 style="margin:0 0 20px;font-size:20px;font-weight:700;color:#0f172a;">{title}</h2>
            {body_html}
            {f'<p style="margin:28px 0 0;font-size:13px;color:#94a3b8;">{footer}</p>' if footer else ''}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:20px 36px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">
              This email was sent by <strong>Clause CLM</strong>.
              You are receiving this because you are a member of this workspace.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _contract_expiry_html(contract_title: str, days: int, end_date: str, contract_id: str) -> str:
    urgency_color = "#ef4444" if days <= 7 else ("#f59e0b" if days <= 30 else "#3b82f6")
    urgency_label = "URGENT" if days <= 7 else ("WARNING" if days <= 30 else "REMINDER")
    body = f"""
    <div style="background:#fef2f2;border-left:4px solid {urgency_color};border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;font-size:13px;font-weight:700;color:{urgency_color};text-transform:uppercase;letter-spacing:.5px;">{urgency_label}</p>
      <p style="margin:6px 0 0;font-size:15px;color:#0f172a;font-weight:600;">{contract_title}</p>
    </div>
    <p style="color:#475569;font-size:15px;line-height:1.6;">
      This contract will expire in <strong style="color:{urgency_color};">{days} day{'s' if days != 1 else ''}</strong> on <strong>{end_date}</strong>.
    </p>
    <p style="color:#475569;font-size:14px;line-height:1.6;">
      Please review the contract and take appropriate action — renew, renegotiate, or let it expire.
    </p>
    <a href="http://localhost:5173/contracts/{contract_id}"
       style="display:inline-block;margin-top:20px;background:#6d28d9;color:#fff;text-decoration:none;
              padding:12px 24px;border-radius:10px;font-size:14px;font-weight:600;">
      View Contract →
    </a>"""
    return body


def _approval_request_html(contract_title: str, approval_type: str, contract_id: str) -> str:
    body = f"""
    <div style="background:#eff6ff;border-left:4px solid #3b82f6;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;font-size:13px;font-weight:700;color:#3b82f6;text-transform:uppercase;letter-spacing:.5px;">ACTION REQUIRED</p>
      <p style="margin:6px 0 0;font-size:15px;color:#0f172a;font-weight:600;">{contract_title}</p>
    </div>
    <p style="color:#475569;font-size:15px;line-height:1.6;">
      You have been requested to approve a contract. Approval type: <strong>{approval_type.replace('_', ' ').title()}</strong>.
    </p>
    <a href="http://localhost:5173/contracts/{contract_id}"
       style="display:inline-block;margin-top:20px;background:#6d28d9;color:#fff;text-decoration:none;
              padding:12px 24px;border-radius:10px;font-size:14px;font-weight:600;">
      Review &amp; Vote →
    </a>"""
    return body


def _workflow_update_html(contract_title: str, stage: str, status: str, contract_id: str) -> str:
    body = f"""
    <div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;font-size:13px;font-weight:700;color:#16a34a;text-transform:uppercase;letter-spacing:.5px;">WORKFLOW UPDATE</p>
      <p style="margin:6px 0 0;font-size:15px;color:#0f172a;font-weight:600;">{contract_title}</p>
    </div>
    <p style="color:#475569;font-size:15px;line-height:1.6;">
      The workflow for this contract has been updated.<br>
      <strong>Stage:</strong> {stage.replace('_', ' ').title()}<br>
      <strong>Status:</strong> {status.replace('_', ' ').title()}
    </p>
    <a href="http://localhost:5173/contracts/{contract_id}"
       style="display:inline-block;margin-top:20px;background:#6d28d9;color:#fff;text-decoration:none;
              padding:12px 24px;border-radius:10px;font-size:14px;font-weight:600;">
      View Workflow →
    </a>"""
    return body


# ── Core send function ────────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, html_body: str) -> tuple[bool, str]:
    """Send an HTML email via Gmail SMTP. Returns (success, error_message)."""
    smtp_email    = _smtp_email()
    smtp_password = _smtp_password()

    if not smtp_email or not smtp_password:
        msg = "SMTP_EMAIL or SMTP_PASSWORD is not set in your .env file."
        print(f"[email_service] {msg}")
        return False, msg

    msg_obj = MIMEMultipart("alternative")
    msg_obj["Subject"] = subject
    msg_obj["From"]    = f"Clause CLM <{smtp_email}>"
    msg_obj["To"]      = to_email
    msg_obj.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    last_error = ""

    # Try port 465 (SSL) first — more reliable on restrictive networks
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg_obj.as_string())
        print(f"[email_service] Email sent to {to_email} via port 465")
        return True, ""
    except smtplib.SMTPAuthenticationError:
        error = (
            "Gmail authentication failed (port 465). Your App Password is incorrect or expired. "
            "Go to myaccount.google.com/apppasswords, delete the old password and generate a new one, "
            "then update SMTP_PASSWORD in your .env file."
        )
        print(f"[email_service] {error}")
        return False, error
    except Exception as e:
        last_error = str(e)
        print(f"[email_service] Port 465 failed: {e} — trying port 587...")

    # Fallback: port 587 (STARTTLS)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg_obj.as_string())
        print(f"[email_service] Email sent to {to_email} via port 587")
        return True, ""
    except smtplib.SMTPAuthenticationError:
        error = (
            "Gmail authentication failed (port 587). Your App Password is incorrect or expired. "
            "Go to myaccount.google.com/apppasswords, delete the old password and generate a new one, "
            "then update SMTP_PASSWORD in your .env file."
        )
        print(f"[email_service] {error}")
        return False, error
    except Exception as e:
        error = (
            f"Could not connect to Gmail on port 465 or 587. "
            f"Port 465 error: {last_error} | Port 587 error: {e}. "
            f"Check that your network allows outbound SMTP, or try a different network."
        )
        print(f"[email_service] {error}")
        return False, error


# ── High-level notification senders ──────────────────────────────────────────

def send_expiry_alert(to_email: str, contract_title: str, days: int, end_date: str, contract_id: str) -> bool:
    subject = f"⚠️ Contract Expiring in {days} Day{'s' if days != 1 else ''}: {contract_title}"
    body    = _contract_expiry_html(contract_title, days, end_date, contract_id)
    html    = _base_template(f"Contract Expiry {'Urgent Notice' if days <= 7 else 'Reminder'}", body)
    ok, _   = send_email(to_email, subject, html)
    return ok


def send_approval_request(to_email: str, contract_title: str, approval_type: str, contract_id: str) -> bool:
    subject = f"📋 Approval Required: {contract_title}"
    body    = _approval_request_html(contract_title, approval_type, contract_id)
    html    = _base_template("Approval Request", body)
    ok, _   = send_email(to_email, subject, html)
    return ok


def send_workflow_update(to_email: str, contract_title: str, stage: str, status: str, contract_id: str) -> bool:
    subject = f"🔄 Workflow Updated: {contract_title}"
    body    = _workflow_update_html(contract_title, stage, status, contract_id)
    html    = _base_template("Workflow Update", body)
    ok, _   = send_email(to_email, subject, html)
    return ok


def send_test_email(to_email: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    body = """
    <p style="color:#475569;font-size:15px;line-height:1.6;">
      Your Gmail notifications are correctly configured in <strong>Clause CLM</strong>. 🎉
    </p>
    <p style="color:#475569;font-size:14px;line-height:1.6;">
      You will now receive automated email alerts for:
    </p>
    <ul style="color:#475569;font-size:14px;line-height:2;">
      <li>Contract expiry reminders (90 / 30 / 7 days before)</li>
      <li>Approval requests that need your vote</li>
      <li>Workflow stage updates</li>
    </ul>"""
    html = _base_template("Test Email — Setup Successful", body)
    return send_email(to_email, "✅ Clause CLM — Email Notifications Configured", html)


# ── Bulk expiry scanner (call from a scheduled job or admin trigger) ──────────

def scan_and_send_expiry_alerts(dry_run: bool = False) -> dict:
    """Scan all contracts and send expiry emails for ones hitting 90/30/7-day thresholds.

    Prevents duplicate sends by checking the notifications_collection for already-sent records.
    """
    from app.config import users_collection

    now   = datetime.now(timezone.utc)
    sent  = 0
    skipped = 0
    errors  = 0
    thresholds = [90, 30, 7]

    contracts = list(contracts_collection.find(
        {"end_date": {"$exists": True}, "status": {"$nin": ["terminated", "expired"]}},
        {"_id": 1, "title": 1, "end_date": 1, "created_by": 1}
    ))

    for contract in contracts:
        end_raw = contract.get("end_date")
        if not end_raw:
            continue

        # Normalise to aware datetime
        if isinstance(end_raw, str):
            try:
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            except Exception:
                continue
        elif isinstance(end_raw, datetime):
            end_dt = end_raw if end_raw.tzinfo else end_raw.replace(tzinfo=timezone.utc)
        else:
            continue

        days_remaining = (end_dt - now).days

        for threshold in thresholds:
            # Only fire within ±1 day of the threshold to avoid re-sending
            if abs(days_remaining - threshold) > 1:
                continue

            contract_id = str(contract["_id"])
            dedup_key   = f"expiry_{contract_id}_{threshold}d"

            # Skip if already sent
            if notifications_collection.find_one({"dedup_key": dedup_key}):
                skipped += 1
                continue

            # Get creator's email
            creator_id = contract.get("created_by", "")
            user_record = users_collection.find_one({"clerk_id": creator_id}, {"email": 1})
            to_email    = user_record.get("email", "") if user_record else ""

            if not to_email:
                skipped += 1
                continue

            if dry_run:
                sent += 1
                continue

            ok = send_expiry_alert(
                to_email=to_email,
                contract_title=contract.get("title", "Contract"),
                days=days_remaining,
                end_date=end_dt.strftime("%b %d, %Y"),
                contract_id=contract_id,
            )

            if ok:
                # Record to prevent duplicate sends
                notifications_collection.insert_one({
                    "type":        "expiry_email",
                    "dedup_key":   dedup_key,
                    "contract_id": contract_id,
                    "user_id":     creator_id,
                    "threshold":   threshold,
                    "sent_at":     now,
                    "is_read":     False,
                })
                sent += 1
            else:
                errors += 1

    return {"sent": sent, "skipped": skipped, "errors": errors, "dry_run": dry_run}
