"""
Observability instrumentation for Legalassist-AI
Includes Prometheus metrics, structured logging, and distributed tracing
"""

import json
import logging
import time
import os
from functools import wraps
from typing import Callable, Any
from datetime import datetime
from contextlib import contextmanager
import uuid

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, multiprocess, generate_latest
from prometheus_client import start_http_server
import structlog
from jaeger_client import Config
from opentelemetry import trace, metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

# ==================== Prometheus Metrics ====================
registry = CollectorRegistry()

# HTTP Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=registry
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
    registry=registry
)

http_requests_queued = Gauge(
    'http_requests_queued',
    'Number of queued HTTP requests',
    registry=registry
)

# LLM Metrics
llm_tokens_used_total = Counter(
    'llm_tokens_used_total',
    'Total tokens used in LLM calls',
    ['model', 'type'],  # type: prompt, completion
    registry=registry
)

llm_api_calls_total = Counter(
    'llm_api_calls_total',
    'Total LLM API calls',
    ['model', 'status'],
    registry=registry
)

llm_api_call_duration_seconds = Histogram(
    'llm_api_call_duration_seconds',
    'LLM API call duration in seconds',
    ['model'],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    registry=registry
)

llm_api_costs_total = Gauge(
    'llm_api_costs_total',
    'Total cumulative API costs in dollars',
    ['model'],
    registry=registry
)

# Document Processing Metrics
document_processing_total = Counter(
    'document_processing_total',
    'Total documents processed',
    ['document_type', 'status'],
    registry=registry
)

document_processing_duration_seconds = Histogram(
    'document_processing_duration_seconds',
    'Document processing duration in seconds',
    ['document_type'],
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0),
    registry=registry
)

document_processing_failures_total = Counter(
    'document_processing_failures_total',
    'Failed document processing attempts',
    ['document_type', 'reason'],
    registry=registry
)

# PDF Export Metrics
pdf_export_total = Counter(
    'pdf_export_total',
    'Total PDF exports',
    ['status'],
    registry=registry
)

pdf_export_duration_seconds = Histogram(
    'pdf_export_duration_seconds',
    'PDF export duration in seconds',
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0),
    registry=registry
)

pdf_export_failures_total = Counter(
    'pdf_export_failures_total',
    'Failed PDF exports',
    ['reason'],
    registry=registry
)

# Authentication Metrics
auth_attempts_total = Counter(
    'auth_attempts_total',
    'Total authentication attempts',
    ['status'],
    registry=registry
)

auth_failures_total = Counter(
    'auth_failures_total',
    'Failed authentication attempts',
    ['reason'],
    registry=registry
)

# Database Metrics
db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation', 'table'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0),
    registry=registry
)

db_connection_pool_size = Gauge(
    'db_connection_pool_size',
    'Database connection pool size',
    registry=registry
)

db_active_connections = Gauge(
    'db_active_connections',
    'Number of active database connections',
    registry=registry
)

# Cache Metrics
cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['cache_type'],
    registry=registry
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses',
    ['cache_type'],
    registry=registry
)

cache_operation_duration_seconds = Histogram(
    'cache_operation_duration_seconds',
    'Cache operation duration in seconds',
    ['operation', 'cache_type'],
    buckets=(0.001, 0.01, 0.05, 0.1),
    registry=registry
)

# Business Metrics
active_cases = Gauge(
    'active_cases_total',
    'Total active cases',
    registry=registry
)

pending_deadlines = Gauge(
    'pending_deadlines_total',
    'Total pending deadlines',
    registry=registry
)

user_sessions_active = Gauge(
    'user_sessions_active',
    'Currently active user sessions',
    registry=registry
)


# ==================== Structured Logging ====================
def setup_structured_logging():
    """Configure structlog for JSON-formatted logging with correlation IDs"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=None,
        level=logging.INFO,
    )


# Get structlog logger
log = structlog.get_logger()


# ==================== Distributed Tracing ====================
def setup_jaeger_tracing(service_name: str = "legalassist-ai"):
    """Initialize Jaeger distributed tracing"""
    jaeger_exporter = JaegerExporter(
        agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
        agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
    )
    
    resource = Resource.create({SERVICE_NAME: service_name})
    jaeger_provider = TracerProvider(resource=resource)
    jaeger_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
    trace.set_tracer_provider(jaeger_provider)
    
    return trace.get_tracer(__name__)


# Get tracer instance
tracer = setup_jaeger_tracing()


# ==================== Context Management ====================
class CorrelationContext:
    """Thread-local correlation context for request tracing"""
    def __init__(self):
        self.correlation_id = None
        self.user_id = None
        self.session_id = None
    
    def set(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def get(self):
        return {
            'correlation_id': self.correlation_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
        }


correlation_context = CorrelationContext()


def generate_correlation_id() -> str:
    """Generate unique correlation ID for request tracing"""
    return str(uuid.uuid4())


@contextmanager
def traced_operation(operation_name: str, attributes: dict = None):
    """Context manager for distributed tracing of operations"""
    with tracer.start_as_current_span(operation_name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(e))
            raise


# ==================== Decorators ====================
def track_http_request(endpoint: str = None):
    """Decorator to track HTTP request metrics"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            ep = endpoint or func.__name__
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                http_requests_total.labels(
                    method="POST",
                    endpoint=ep,
                    status="success"
                ).inc()
                return result
            except Exception as e:
                http_requests_total.labels(
                    method="POST",
                    endpoint=ep,
                    status="error"
                ).inc()
                log.error(
                    "http_request_failed",
                    endpoint=ep,
                    error=str(e),
                    correlation_id=correlation_context.correlation_id
                )
                raise
            finally:
                duration = time.time() - start_time
                http_request_duration_seconds.labels(
                    method="POST",
                    endpoint=ep
                ).observe(duration)
        
        return wrapper
    return decorator


def track_llm_call(model: str):
    """Decorator to track LLM API calls and token usage"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            
            with traced_operation(f"llm_call_{model}", {"model": model}):
                try:
                    result = func(*args, **kwargs)
                    
                    # Extract token usage if available in result
                    if isinstance(result, dict) and 'usage' in result:
                        usage = result['usage']
                        llm_tokens_used_total.labels(
                            model=model,
                            type="prompt"
                        ).inc(usage.get('prompt_tokens', 0))
                        llm_tokens_used_total.labels(
                            model=model,
                            type="completion"
                        ).inc(usage.get('completion_tokens', 0))
                    
                    llm_api_calls_total.labels(
                        model=model,
                        status="success"
                    ).inc()
                    
                    return result
                except Exception as e:
                    llm_api_calls_total.labels(
                        model=model,
                        status="error"
                    ).inc()
                    log.error(
                        "llm_call_failed",
                        model=model,
                        error=str(e),
                        correlation_id=correlation_context.correlation_id
                    )
                    raise
                finally:
                    duration = time.time() - start_time
                    llm_api_call_duration_seconds.labels(model=model).observe(duration)
        
        return wrapper
    return decorator


def track_document_processing(doc_type: str):
    """Decorator to track document processing metrics"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            
            with traced_operation(f"document_processing_{doc_type}", {"document_type": doc_type}):
                try:
                    result = func(*args, **kwargs)
                    document_processing_total.labels(
                        document_type=doc_type,
                        status="success"
                    ).inc()
                    return result
                except Exception as e:
                    reason = type(e).__name__
                    document_processing_failures_total.labels(
                        document_type=doc_type,
                        reason=reason
                    ).inc()
                    log.error(
                        "document_processing_failed",
                        document_type=doc_type,
                        error=str(e),
                        correlation_id=correlation_context.correlation_id
                    )
                    raise
                finally:
                    duration = time.time() - start_time
                    document_processing_duration_seconds.labels(
                        document_type=doc_type
                    ).observe(duration)
        
        return wrapper
    return decorator


def track_database_operation(operation: str, table: str):
    """Decorator to track database operation metrics"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                db_query_duration_seconds.labels(
                    operation=operation,
                    table=table
                ).observe(duration)
        
        return wrapper
    return decorator


# ==================== Metrics Endpoint ====================
def get_metrics():
    """Get Prometheus metrics in text format"""
    # Handle multiprocess mode if in use
    if os.environ.get('prometheus_multiproc_dir'):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(registry)


# ==================== Initialization ====================
def initialize_observability():
    """Initialize all observability components"""
    # Setup structured logging
    setup_structured_logging()
    
    # Setup distributed tracing
    global tracer
    tracer = setup_jaeger_tracing()
    
    # Start Prometheus metrics server
    metrics_port = int(os.getenv("PROMETHEUS_METRICS_PORT", "9090"))
    try:
        start_http_server(metrics_port)
        log.info("prometheus_metrics_started", port=metrics_port)
    except OSError as e:
        log.warning("prometheus_metrics_already_running", error=str(e))
    
    log.info("observability_initialized")
