"""
Input validation and request size enforcement utilities

This module provides comprehensive validation for:
- Request body sizes
- File uploads (size, type, extension)
- JSON payload validation
- Form data validation
"""

import os
from typing import Optional, Set
from pathlib import Path
from fastapi import HTTPException, status, UploadFile

import structlog

logger = structlog.get_logger(__name__)


class ValidationConfig:
    """Configuration for input validation limits"""
    
    # File upload limits
    MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024  # 500 MB
    MAX_UPLOAD_SIZE_JSON: int = 50 * 1024 * 1024  # 50 MB for JSON payloads
    MAX_TEXT_LENGTH: int = 10 * 1024 * 1024  # 10 MB for raw text
    
    # Allowed file types
    ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".doc", ".docx", ".txt", ".html", ".rtf"}
    ALLOWED_MIME_TYPES: Set[str] = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/html",
        "application/rtf",
    }
    
    # Analytics/batch upload
    MAX_BATCH_SIZE: int = 100  # max items per batch request
    MAX_ANALYTICS_PAYLOAD: int = 100 * 1024 * 1024  # 100 MB for analytics ingestion
    
    # JSON body size (general)
    MAX_JSON_BODY: int = 10 * 1024 * 1024  # 10 MB general JSON requests
    
    @classmethod
    def from_settings(cls, settings):
        """Initialize from API settings object"""
        cls.MAX_UPLOAD_SIZE = getattr(settings, "UPLOAD_MAX_SIZE", 25 * 1024 * 1024)
        cls.ALLOWED_EXTENSIONS = set(getattr(settings, "UPLOAD_EXTENSIONS", [".pdf", ".doc", ".docx", ".txt", ".html"]))
        return cls


class ValidationError(HTTPException):
    """Base validation error for HTTP responses"""
    
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


class PayloadTooLargeError(HTTPException):
    """413 Payload Too Large error"""
    
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=detail
        )


def validate_file_upload(
    file: UploadFile,
    max_size: Optional[int] = None,
    allowed_extensions: Optional[Set[str]] = None,
    allowed_mime_types: Optional[Set[str]] = None,
) -> None:
    """
    Validate uploaded file meets size, extension, and MIME type requirements.
    
    Raises:
        PayloadTooLargeError: File exceeds max_size
        ValidationError: File extension or MIME type not allowed
    """
    max_size = max_size or ValidationConfig.MAX_UPLOAD_SIZE
    allowed_extensions = allowed_extensions or ValidationConfig.ALLOWED_EXTENSIONS
    allowed_mime_types = allowed_mime_types or ValidationConfig.ALLOWED_MIME_TYPES
    
    # Check MIME type
    if file.content_type not in allowed_mime_types:
        logger.warning(
            "invalid_upload_mime_type",
            filename=file.filename,
            mime_type=file.content_type,
            allowed_types=list(allowed_mime_types),
        )
        raise ValidationError(
            detail=f"File type '{file.content_type}' not allowed. Allowed types: {', '.join(allowed_mime_types)}"
        )
    
    # Check file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        logger.warning(
            "invalid_upload_extension",
            filename=file.filename,
            extension=file_ext,
            allowed_extensions=list(allowed_extensions),
        )
        raise ValidationError(
            detail=f"File extension '{file_ext}' not allowed. Allowed extensions: {', '.join(allowed_extensions)}"
        )
    
    # Check file size (check content_length header first, then read during upload)
    if file.size and file.size > max_size:
        logger.warning(
            "upload_exceeds_max_size",
            filename=file.filename,
            size_bytes=file.size,
            max_size_bytes=max_size,
            size_mb=round(file.size / 1024 / 1024, 2),
            max_size_mb=round(max_size / 1024 / 1024, 2),
        )
        raise PayloadTooLargeError(
            detail=f"File size ({round(file.size / 1024 / 1024, 2)} MB) exceeds maximum allowed size ({round(max_size / 1024 / 1024, 2)} MB)"
        )


async def validate_file_upload_streaming(
    file: UploadFile,
    max_size: Optional[int] = None,
    chunk_size: int = 1024 * 1024,  # 1 MB chunks
) -> int:
    """
    Validate file size during streaming read to catch oversized uploads early.
    Returns the total bytes read.
    
    Raises:
        PayloadTooLargeError: File exceeds max_size during read
    """
    max_size = max_size or ValidationConfig.MAX_UPLOAD_SIZE
    bytes_read = 0
    
    try:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            
            bytes_read += len(chunk)
            if bytes_read > max_size:
                logger.error(
                    "upload_exceeded_max_size_during_stream",
                    filename=file.filename,
                    bytes_read=bytes_read,
                    max_size_bytes=max_size,
                )
                raise PayloadTooLargeError(
                    detail=f"Upload exceeded maximum size limit of {round(max_size / 1024 / 1024, 2)} MB"
                )
    finally:
        await file.seek(0)  # Reset for actual processing
    
    return bytes_read


def validate_json_payload(payload_size: int, max_size: Optional[int] = None) -> None:
    """
    Validate JSON payload size.
    
    Raises:
        PayloadTooLargeError: Payload exceeds max_size
    """
    max_size = max_size or ValidationConfig.MAX_JSON_BODY
    
    if payload_size > max_size:
        logger.warning(
            "json_payload_exceeds_limit",
            size_bytes=payload_size,
            max_size_bytes=max_size,
            size_mb=round(payload_size / 1024 / 1024, 2),
        )
        raise PayloadTooLargeError(
            detail=f"Request body size ({round(payload_size / 1024 / 1024, 2)} MB) exceeds maximum allowed ({round(max_size / 1024 / 1024, 2)} MB)"
        )


def validate_text_input(text: str, max_length: Optional[int] = None) -> None:
    """
    Validate raw text input length.
    
    Raises:
        PayloadTooLargeError: Text exceeds max_length
    """
    max_length = max_length or ValidationConfig.MAX_TEXT_LENGTH
    text_bytes = len(text.encode("utf-8"))
    
    if text_bytes > max_length:
        logger.warning(
            "text_input_exceeds_limit",
            size_bytes=text_bytes,
            max_size_bytes=max_length,
            size_mb=round(text_bytes / 1024 / 1024, 2),
        )
        raise PayloadTooLargeError(
            detail=f"Text input size ({round(text_bytes / 1024 / 1024, 2)} MB) exceeds maximum allowed ({round(max_length / 1024 / 1024, 2)} MB)"
        )


def validate_batch_size(items: list, max_items: Optional[int] = None) -> None:
    """
    Validate batch request doesn't exceed item limit.
    
    Raises:
        ValidationError: Batch exceeds max_items
    """
    max_items = max_items or ValidationConfig.MAX_BATCH_SIZE
    
    if len(items) > max_items:
        logger.warning(
            "batch_request_exceeds_limit",
            item_count=len(items),
            max_items=max_items,
        )
        raise ValidationError(
            detail=f"Batch size ({len(items)} items) exceeds maximum allowed ({max_items} items)"
        )


def validate_query_string(query_string: str, max_length: int = 2048) -> None:
    """
    Validate query string length to prevent DOS via crafted URLs.
    
    Raises:
        ValidationError: Query string exceeds max_length
    """
    if len(query_string) > max_length:
        logger.warning(
            "query_string_exceeds_limit",
            length=len(query_string),
            max_length=max_length,
        )
        raise ValidationError(
            detail=f"Query string too long ({len(query_string)} chars, max {max_length})"
        )
