"""
Celery async task queue configuration and tasks
"""
import os
import uuid
from datetime import datetime
from celery import Celery, Task
from celery.result import AsyncResult
import structlog

from api.config import get_settings
from observability.integration import initialize_observability_for_environment
from observability.instrumentation import traced_operation, capture_exception, bind_request_context, clear_request_context


settings = get_settings()
logger = structlog.get_logger(__name__)
initialize_observability_for_environment()


# ============================================================================
# Celery App Configuration
# ============================================================================

class ContextTask(Task):
    """Make celery tasks work with request context"""
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True


celery_app = Celery(
    "legalassist",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    task_cls=ContextTask
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIMEOUT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
)


# ============================================================================
# Task Monitoring
# ============================================================================

class TaskStatus:
    """Task status tracker"""
    
    @staticmethod
    def get_task_status(task_id: str) -> dict:
        """Get status of async task"""
        result = AsyncResult(task_id, app=celery_app)
        
        if result.state == "PENDING":
            status = "pending"
            info = {"status": "Task not yet started"}
        elif result.state == "STARTED":
            status = "processing"
            info = result.info if isinstance(result.info, dict) else {"status": "Processing"}
        elif result.state == "SUCCESS":
            status = "completed"
            info = result.result if result.result else {}
        elif result.state == "FAILURE":
            status = "failed"
            info = {"error": str(result.info)}
        elif result.state == "RETRY":
            status = "retrying"
            info = {"error": str(result.info)}
        else:
            status = result.state.lower()
            info = {}
        
        return {
            "task_id": task_id,
            "status": status,
            "info": info,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def revoke_task(task_id: str) -> bool:
        """Cancel a task"""
        try:
            celery_app.control.revoke(task_id, terminate=True)
            return True
        except Exception as e:
            logger.error("Failed to revoke task", task_id=task_id, error=str(e))
            return False


# ============================================================================
# Async Tasks
# ============================================================================

@celery_app.task(bind=True, name="analyze_document")
def analyze_document_task(
    self,
    user_id: str,
    document_id: str,
    text: str,
    document_type: str = "unknown",
    request_id: str | None = None,
) -> dict:
    """Async task to analyze document"""
    try:
        bind_request_context(request_id=request_id or self.request.id, user_id=user_id)
        with traced_operation(
            "celery.analyze_document",
            {
                "task.id": self.request.id,
                "user.id": user_id,
                "document.id": document_id,
                "document.type": document_type,
                "request.id": request_id or self.request.id,
            },
        ):
            self.update_state(
                state="PROGRESS",
                meta={
                    "status": "Extracting text",
                    "progress": 25
                }
            )

            logger.info(
                "Starting document analysis",
                task_id=self.request.id,
                user_id=user_id,
                document_id=document_id
            )

            # Simulate processing steps
            self.update_state(state="PROGRESS", meta={"status": "Analyzing content", "progress": 50})
            self.update_state(state="PROGRESS", meta={"status": "Extracting remedies", "progress": 75})
            self.update_state(state="PROGRESS", meta={"status": "Finalizing results", "progress": 90})

            # In production, call actual analysis engine
            result = {
                "document_id": document_id,
                "summary": "Document analysis completed successfully",
                "remedies": [],
                "deadlines": [],
                "obligations": [],
                "confidence_score": 0.85,
                "analysis_time_seconds": 10.5
            }

            logger.info(
                "Document analysis completed",
                task_id=self.request.id,
                document_id=document_id
            )

            return result

    except Exception as e:
        capture_exception(e, task_id=self.request.id, user_id=user_id, document_id=document_id)
        logger.error(
            "Document analysis failed",
            task_id=self.request.id,
            error=str(e)
        )
        raise
    finally:
        clear_request_context()


@celery_app.task(bind=True, name="generate_report")
def generate_report_task(
    self,
    user_id: str,
    case_id: str,
    report_type: str = "comprehensive",
    format: str = "pdf"
) -> dict:
    """Async task to generate report"""
    try:
        self.update_state(state="PROGRESS", meta={"status": "Compiling data", "progress": 20})
        
        logger.info(
            "Starting report generation",
            task_id=self.request.id,
            user_id=user_id,
            case_id=case_id
        )
        
        self.update_state(state="PROGRESS", meta={"status": "Formatting document", "progress": 50})
        self.update_state(state="PROGRESS", meta={"status": "Rendering output", "progress": 80})
        self.update_state(state="PROGRESS", meta={"status": "Finalizing report", "progress": 95})
        
        # Phase 1: call local report generator
        from report_service import generate_report

        report_id = str(uuid.uuid4())
        generated = generate_report(
            user_id=user_id,
            case_id=case_id,
            report_type=report_type,
            include_remedies=True,
            include_timeline=True,
            format=format,
            style="formal",
            report_id=report_id,
        )

        result = {
            "report_id": report_id,
            "format": generated.format,
            "file_path": str(generated.file_path),
            "file_name": generated.file_name,
            "mime_type": generated.mime_type,
            "file_size_bytes": generated.file_size_bytes,
        }

        
        logger.info(
            "Report generation completed",
            task_id=self.request.id,
            case_id=case_id
        )
        
        return result
    
    except Exception as e:
        logger.error(
            "Report generation failed",
            task_id=self.request.id,
            error=str(e)
        )
        raise


@celery_app.task(bind=True, name="export_data")
def export_data_task(
    self,
    user_id: str,
    format: str = "csv"
) -> dict:
    """Async task to export user data"""
    try:
        self.update_state(state="PROGRESS", meta={"status": "Gathering data", "progress": 30})
        
        self.update_state(state="PROGRESS", meta={"status": "Formatting export", "progress": 60})
        self.update_state(state="PROGRESS", meta={"status": "Compressing file", "progress": 90})
        
        result = {
            "export_id": str(uuid.uuid4()),
            "file_url": f"https://storage.example.com/exports/{user_id}.{format}",
            "file_size_bytes": 2048000,
            "expires_in_hours": 24
        }
        
        return result
    
    except Exception as e:
        logger.error("Export failed", user_id=user_id, error=str(e))
        raise


@celery_app.task(bind=True, name="send_notification")
def send_notification_task(
    self,
    user_id: str,
    message: str,
    notification_type: str = "email"
) -> dict:
    """Async task to send notifications"""
    try:
        logger.info(
            "Sending notification",
            user_id=user_id,
            notification_type=notification_type
        )
        
        # In production, send actual notification
        result = {
            "notification_id": str(uuid.uuid4()),
            "user_id": user_id,
            "type": notification_type,
            "sent_at": datetime.utcnow().isoformat()
        }
        
        return result
    
    except Exception as e:
        logger.error("Notification failed", user_id=user_id, error=str(e))
        raise


# ============================================================================
# Scheduled Tasks (Beat)
# ============================================================================

@celery_app.task(name="cleanup_old_tasks")
def cleanup_old_tasks():
    """Clean up old completed tasks"""
    logger.info("Running cleanup_old_tasks")
    # Implement cleanup logic
    return {"status": "completed"}


@celery_app.task(name="send_deadline_reminders")
def send_deadline_reminders():
    """Send reminders for upcoming deadlines"""
    logger.info("Running send_deadline_reminders")
    # Implementation would fetch deadlines and send notifications
    return {"reminders_sent": 0}
