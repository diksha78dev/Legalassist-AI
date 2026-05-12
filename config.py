import os
import logging
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Initialize logging for config phase
logger = logging.getLogger(__name__)

# Load .env file
PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"

if PROJECT_ENV_PATH.exists():
    load_dotenv(dotenv_path=PROJECT_ENV_PATH)
else:
    load_dotenv()

def _get_val(key, default=None):
    # Try Streamlit secrets first (if in a Streamlit context)
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except (ImportError, RuntimeError, AttributeError, FileNotFoundError):
        pass
    
    # Fallback to environment variables
    return os.getenv(key, default)

def _get_bool_env(key, default=False):
    val = str(_get_val(key, str(default))).lower()
    return val in ("1", "true", "yes", "on")

def _get_int_env(key, default):
    try:
        return int(_get_val(key, str(default)))
    except (ValueError, TypeError):
        return default

class Config:
    # --- App Identity ---
    APP_NAME = _get_val("APP_NAME", "LegalEase AI")
    APP_ENV = _get_val("APP_ENV", _get_val("ENVIRONMENT", "development")).lower()
    DEBUG = _get_bool_env("DEBUG", APP_ENV in ("dev", "development", "local"))
    TESTING = _get_bool_env("TESTING", False)
    
    # --- Logging ---
    LOG_LEVEL = _get_val("LOG_LEVEL", "INFO")
    
    # --- Model Settings (LLM) ---
    # Default model for summary and remedies
    DEFAULT_MODEL = _get_val("DEFAULT_MODEL", "meta-llama/llama-3.1-8b-instruct")
    OPENROUTER_BASE_URL = _get_val("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_API_KEY = _get_val("OPENROUTER_API_KEY", "")
    
    # LLM Hyperparameters
    SUMMARY_MAX_TOKENS = _get_int_env("SUMMARY_MAX_TOKENS", 280)
    REMEDIES_MAX_TOKENS = _get_int_env("REMEDIES_MAX_TOKENS", 900)
    LLM_TEMPERATURE = float(_get_val("LLM_TEMPERATURE", "0.05"))
    LLM_TIMEOUT = float(_get_val("LLM_TIMEOUT", "60.0"))
    
    # --- OCR Settings ---
    OCR_ENABLED = _get_bool_env("OCR_ENABLED", False)
    OCR_LANGUAGES = _get_val("OCR_LANGUAGES", "eng+hin")
    OCR_DPI = _get_int_env("OCR_DPI", 300)
    
    # --- File Processing ---
    MAX_FILE_SIZE_MB = _get_int_env("MAX_FILE_SIZE_MB", 25)
    WARN_FILE_SIZE_MB = _get_int_env("WARN_FILE_SIZE_MB", 10)
    TEXT_COMPRESSION_LIMIT = _get_int_env("TEXT_COMPRESSION_LIMIT", 6000)
    
    # --- Database Settings ---
    DATABASE_URL = _get_val("DATABASE_URL", "sqlite:///./legalassist.db")
    
    # --- Authentication (JWT & OTP) ---
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRY_HOURS = _get_int_env("JWT_EXPIRY_HOURS", 7 * 24)
    OTP_EXPIRY_MINUTES = _get_int_env("OTP_EXPIRY_MINUTES", 10)
    OTP_MAX_ATTEMPTS = _get_int_env("OTP_MAX_ATTEMPTS", 3)
    
    @classmethod
    def get_jwt_secret(cls):
        """
        Resolve JWT secret securely.
        
        Order of precedence:
        1. Environment variable or Streamlit secret 'JWT_SECRET'
        2. File-based secret in '.jwt_secret' (legacy/local development)
        
        NOTE: Automatic generation and writing of .jwt_secret has been disabled 
        for security in all environments.
        """
        secret = str(_get_val("JWT_SECRET", "")).strip()
        if secret:
            return secret
            
        secret_file = PROJECT_ROOT / ".jwt_secret"
        if secret_file.exists():
            try:
                file_secret = secret_file.read_text(encoding="utf-8").strip()
                if file_secret:
                    return file_secret
            except Exception as e:
                logger.warning(f"Failed to read .jwt_secret file: {e}")
        
        # We no longer auto-generate secrets to prevent insecure fallback.
        # This forces explicit configuration which is a security best practice.
        env_name = cls.APP_ENV.upper()
        raise RuntimeError(
            f"JWT_SECRET is not configured for the {env_name} environment. "
            "For security, secrets must be explicitly provided via the 'JWT_SECRET' "
            "environment variable or a manually created '.jwt_secret' file in the root."
        )

    # --- Notification Settings (SMS) ---
    TWILIO_ACCOUNT_SID = _get_val("TWILIO_ACCOUNT_SID", "")
    TWILIO_FROM_NUMBER = _get_val("TWILIO_FROM_NUMBER", "")

    @classmethod
    def get_twilio_auth_token(cls) -> str:
        """Return the Twilio auth token, retrieved on demand to limit exposure."""
        return str(_get_val("TWILIO_AUTH_TOKEN", "") or "")

    # --- Notification Settings (Email) ---
    SENDGRID_FROM_EMAIL = _get_val("SENDGRID_FROM_EMAIL", "noreply@legalassist.ai")

    @classmethod
    def get_sendgrid_api_key(cls) -> str:
        """Return the SendGrid API key, retrieved on demand to limit exposure."""
        return str(_get_val("SENDGRID_API_KEY", "") or "")

    # --- Application URLs ---
    BASE_URL = _get_val("BASE_URL", "https://legalassist.ai")

    @classmethod
    def is_development(cls):
        return cls.APP_ENV in ("dev", "development", "local") or cls.DEBUG or cls.TESTING
