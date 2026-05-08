"""
REST API Integration module for Flask/Streamlit applications
"""
from functools import wraps
from celery_app import celery_app
import structlog

logger = structlog.get_logger(__name__)


class StreamlitAPIAdapter:
    """Adapter for Streamlit application to use async API tasks"""
    
    @staticmethod
    def queue_document_analysis(text: str, document_type: str = "unknown"):
        """Queue document analysis and return job ID"""
        from celery_app import analyze_document_task
        
        task = analyze_document_task.delay(
            user_id="streamlit-user",
            document_id="doc_" + __import__('uuid').uuid4().hex[:8],
            text=text,
            document_type=document_type
        )
        
        return task.id
    
    @staticmethod
    def get_task_progress(task_id: str):
        """Get task progress for WebSocket streaming"""
        from celery_app import TaskStatus
        
        return TaskStatus.get_task_status(task_id)
    
    @staticmethod
    def get_task_result(task_id: str):
        """Get task result"""
        from celery_app import TaskStatus
        
        status = TaskStatus.get_task_status(task_id)
        if status["status"] == "completed":
            return status["info"]
        return None


class FlaskAPIAdapter:
    """Adapter for Flask application"""
    
    @staticmethod
    def create_flask_blueprint():
        """Create Flask blueprint for API"""
        from flask import Blueprint
        
        bp = Blueprint("api", __name__, url_prefix="/api-bridge")
        
        @bp.route("/task/<task_id>/status")
        def get_task_status(task_id):
            from celery_app import TaskStatus
            
            status = TaskStatus.get_task_status(task_id)
            return status
        
        return bp


# Integration with existing core.py
def integrate_api_with_core():
    """Integrate API with core functions"""
    
    logger.info("Integrating REST API with core application")
    
    # Import core functions
    try:
        from core import analyze_document_core
        
        @celery_app.task(name="core_analyze_document")
        def analyze_document_task_integrated(user_id, document_id, text, document_type):
            """Use existing core.py analyze_document function"""
            result = analyze_document_core(text, document_type)
            return result
    
    except ImportError:
        logger.warning("Could not import core.py - using mock implementation")


if __name__ == "__main__":
    integrate_api_with_core()
