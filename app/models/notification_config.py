from pydantic import BaseModel
from typing import List


class SmtpSettings(BaseModel):
    enabled: bool = False
    host: str = "smtp.gmail.com"
    port: int = 465
    username: str = ""
    password: str = ""
    from_name: str = "Clause CLM"
    encryption: str = "ssl"  # ssl | starttls | none


class SmsSettings(BaseModel):
    enabled: bool = False
    provider: str = "twilio"  # twilio | vonage | aws_sns
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""


class TriggerSettings(BaseModel):
    expiry_days: List[int] = [90, 30, 7]
    on_approval_request: bool = True
    on_workflow_update: bool = True
    on_contract_created: bool = False
    on_contract_terminated: bool = True
    on_high_risk: bool = False


class RecipientSettings(BaseModel):
    notify_owner: bool = True
    notify_admins: bool = False
    notify_managers: bool = False
    additional_emails: List[str] = []


class NotificationSettingsDoc(BaseModel):
    email: SmtpSettings = SmtpSettings()
    sms: SmsSettings = SmsSettings()
    triggers: TriggerSettings = TriggerSettings()
    recipients: RecipientSettings = RecipientSettings()
