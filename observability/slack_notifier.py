"""
Slack alert notifier - sends structured alerts to Slack channels
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import requests
from enum import Enum

log = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels matching Prometheus"""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(Enum):
    """Alert status"""
    FIRING = "firing"
    RESOLVED = "resolved"


@dataclass
class Alert:
    """Alert data structure"""
    name: str
    severity: AlertSeverity
    status: AlertStatus
    summary: str
    description: str
    service: str
    instance: str
    timestamp: datetime


class SlackNotifier:
    """Send structured alerts to Slack with rich formatting"""
    
    def __init__(self, webhook_critical: str, webhook_warning: str):
        self.webhook_critical = webhook_critical
        self.webhook_warning = webhook_warning
        self.session = requests.Session()
    
    def send_alert(self, alert: Alert) -> bool:
        """Send formatted alert to Slack"""
        try:
            webhook = (
                self.webhook_critical 
                if alert.severity == AlertSeverity.CRITICAL 
                else self.webhook_warning
            )
            
            payload = self._build_payload(alert)
            response = self.session.post(webhook, json=payload, timeout=10)
            
            if response.status_code == 200:
                log.info(f"Alert sent to Slack: {alert.name}")
                return True
            else:
                log.error(f"Slack alert failed: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            log.error(f"Error sending Slack alert: {e}")
            return False
    
    def _build_payload(self, alert: Alert) -> Dict[str, Any]:
        """Build Slack message payload with rich formatting"""
        color_map = {
            AlertSeverity.CRITICAL: "#FF0000",
            AlertSeverity.WARNING: "#FFA500",
            AlertSeverity.INFO: "#0099FF",
        }
        
        status_emoji = "🔴" if alert.status == AlertStatus.FIRING else "✅"
        severity_emoji = {
            AlertSeverity.CRITICAL: "⚠️ CRITICAL",
            AlertSeverity.WARNING: "⚠️ WARNING",
            AlertSeverity.INFO: "ℹ️ INFO",
        }
        
        return {
            "attachments": [
                {
                    "color": color_map[alert.severity],
                    "title": f"{status_emoji} {severity_emoji[alert.severity]}",
                    "title_link": f"https://grafana.example.com/d/alerting",
                    "text": alert.summary,
                    "fields": [
                        {
                            "title": "Alert",
                            "value": alert.name,
                            "short": True
                        },
                        {
                            "title": "Service",
                            "value": alert.service,
                            "short": True
                        },
                        {
                            "title": "Instance",
                            "value": alert.instance,
                            "short": True
                        },
                        {
                            "title": "Status",
                            "value": alert.status.value.upper(),
                            "short": True
                        },
                        {
                            "title": "Description",
                            "value": alert.description,
                            "short": False
                        }
                    ],
                    "ts": int(alert.timestamp.timestamp()),
                    "footer": "Legalassist-AI Monitoring",
                    "footer_icon": "https://example.com/icon.png"
                }
            ]
        }
    
    def send_batch_alerts(self, alerts: List[Alert]) -> int:
        """Send multiple alerts and return count of successful sends"""
        success_count = 0
        for alert in alerts:
            if self.send_alert(alert):
                success_count += 1
        
        log.info(f"Sent {success_count}/{len(alerts)} alerts to Slack")
        return success_count


# Global notifier instance
_notifier: Optional[SlackNotifier] = None


def initialize_slack_notifier():
    """Initialize Slack notifier with webhook URLs from environment"""
    global _notifier
    
    webhook_critical = os.getenv("SLACK_WEBHOOK_CRITICAL")
    webhook_warning = os.getenv("SLACK_WEBHOOK_WARNING")
    
    if not webhook_critical or not webhook_warning:
        log.warning("Slack webhooks not configured - alerts will not be sent")
        return
    
    _notifier = SlackNotifier(webhook_critical, webhook_warning)
    log.info("Slack notifier initialized")


def send_alert(alert: Alert) -> bool:
    """Send alert through global notifier"""
    if _notifier is None:
        log.warning(f"Alert not sent - notifier not initialized: {alert.name}")
        return False
    
    return _notifier.send_alert(alert)


def send_batch_alerts(alerts: List[Alert]) -> int:
    """Send batch of alerts"""
    if _notifier is None:
        log.warning(f"Alerts not sent - notifier not initialized")
        return 0
    
    return _notifier.send_batch_alerts(alerts)


# Example usage for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test alert
    test_alert = Alert(
        name="HighErrorRate",
        severity=AlertSeverity.CRITICAL,
        status=AlertStatus.FIRING,
        summary="High error rate detected in production",
        description="Error rate is 15% (threshold: 5%)",
        service="legalassist-api",
        instance="pod-12345",
        timestamp=datetime.now()
    )
    
    initialize_slack_notifier()
    send_alert(test_alert)
