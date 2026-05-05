from notification_service import NotificationService
from unittest.mock import Mock
from database import CaseDeadline
from datetime import datetime, timezone, timedelta

service = NotificationService()
deadline = Mock(spec=CaseDeadline)
deadline.case_title = "Case <script>alert('XSS')</script> & More"
deadline.deadline_type = "appeal"
deadline.deadline_date = datetime.now(timezone.utc) + timedelta(days=3)
deadline.case_id = "CASE-001"
deadline.description = "<b>Bold</b>"

subject, html_content = service.build_email_message(deadline, 3)

print("Subject:", subject)
print("\nHas unescaped script?:", "<script>" in html_content)
print("Has escaped script?:", "&lt;script&gt;" in html_content)
print("\nLooking for case title in HTML...")
print("Line with 'Case:':")
for line in html_content.split('\n'):
    if 'Case:' in line or 'case-title' in line:
        print(line)
