"""Password hashing for email/password accounts (routers/auth.py's
/auth/register, /auth/login). bcrypt directly, no hand-rolled crypto --
same "don't build security primitives in-house" posture as backend/app/
auth.py's use of python-jose for JWT verification.
"""
import bcrypt

# bcrypt's own hard limit -- it silently truncates anything past 72 bytes
# rather than hashing the full input, which would make two different long
# passwords sharing a 72-byte prefix collide. Rejected explicitly at
# validation time (schemas.py) rather than truncated silently.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    """Returns a bcrypt hash (its own salt embedded, per bcrypt's format) as
    a str for storage in User.password_hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """True if `password` matches the given bcrypt hash. Never raises on a
    malformed/corrupt hash -- treated as a mismatch, not a 500, since a
    verification failure here must always look identical to the caller
    whether the cause is a wrong password or a data problem."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
