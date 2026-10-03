"""Hashed passwords, expiring opaque sessions, CSRF checks and role enforcement."""
import hashlib
import hmac
import secrets
import time
import uuid
from fastapi import HTTPException, Request

def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + salt.hex() + "$" + digest.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

class Auth:
    def __init__(self, db, config):
        self.db, self.config = db, config
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))
        if not db.one("SELECT id FROM users LIMIT 1"):
            if len(config.admin_password) < 12:
                raise RuntimeError("Set ADMIN_PASSWORD to at least 12 characters before the first start. See README.md.")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (str(uuid.uuid4()), config.admin_user,
                        password_hash(config.admin_password), "admin", time.time()))

    def login(self, username, password):
        user = self.db.one("SELECT * FROM users WHERE username=?", (username,))
        valid = verify_password(password, user["password_hash"] if user else self.dummy_hash)
        if not user or not valid:
            raise HTTPException(401, "Incorrect username or password")
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        self.db.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))
        self.db.execute("INSERT INTO auth_sessions VALUES(?,?,?,?)", (token_hash(token), user["id"], csrf,
                        time.time() + self.config.session_hours * 3600))
        self.db.event("Signed in", actor=user["username"])
        return token, {"id": user["id"], "username": user["username"], "role": user["role"], "csrf": csrf}

    def session(self, token):
        if not token:
            return None
        return self.db.one("SELECT u.id,u.username,u.role,s.csrf FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?",
                           (token_hash(token), time.time()))

def current_user(request: Request):
    user = request.app.state.auth.session(request.cookies.get("mt_session"))
    if not user:
        raise HTTPException(401, "Sign in to continue")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
            raise HTTPException(403, "Session verification failed; refresh and sign in again")
    return user

def require_role(user, *roles):
    if user["role"] not in roles:
        raise HTTPException(403, "Your role cannot perform this action")

