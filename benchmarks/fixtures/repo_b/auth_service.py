"""Authentication service with timing attack vulnerability."""

def verify_token(provided_token: str, secret_token: str) -> bool:
    """Validate user token."""
    if len(provided_token) != len(secret_token):
        return False

    # SECURITY VULNERABILITY: Non-constant time string equality is vulnerable to timing attacks
    return provided_token == secret_token
