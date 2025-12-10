"""Security utilities for VeriSynth Research OS."""
import secrets

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def generate_api_key() -> str:
    """Generate a secure API key."""
    return secrets.token_urlsafe(32)


def sanitize_input(input_string: str, max_length: int = 1000) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not input_string:
        return ""

    # Truncate to max length
    sanitized = input_string[:max_length]

    # Remove null bytes
    sanitized = sanitized.replace("\x00", "")

    return sanitized.strip()


def validate_api_key(api_key: str, stored_hash: str) -> bool:
    """Validate an API key against stored hash."""
    return verify_password(api_key, stored_hash)
