"""Explicit, password-protected public demo mode; local mode stays on loopback."""
import base64
from collections import deque
from dataclasses import dataclass, field
import hmac
import os
import re
import threading
import time
from urllib.parse import urlsplit


@dataclass(frozen=True)
class WebAccess:
    public: bool = False
    origin: str = ''
    username: str = 'team'
    password: str = field(default='', repr=False)
    anonymous: bool = False

    @classmethod
    def from_env(cls):
        if os.getenv('PUBLIC_DEMO', 'false').lower() not in {'true', '1', 'yes'}:
            return cls()
        origin = (os.getenv('PUBLIC_ORIGIN') or os.getenv('RENDER_EXTERNAL_URL') or '').rstrip('/')
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '*' in origin
                or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)
                or any(char.isspace() for char in origin)):
            raise ValueError('公网演示需要完整且固定的 HTTPS PUBLIC_ORIGIN 或 RENDER_EXTERNAL_URL。')
        if os.getenv('PUBLIC_DEMO_ANONYMOUS', 'false').lower() in {'true', '1', 'yes'}:
            return cls(public=True, origin=origin, anonymous=True)
        username = os.getenv('DEMO_USERNAME', 'team')
        password = os.getenv('DEMO_PASSWORD', '')
        if (not username or ':' in username or len(password) < 16
                or any(ord(char) < 32 for char in username + password)):
            raise ValueError('公网演示需要用户名和至少16个字符的 DEMO_PASSWORD。')
        return cls(public=True, origin=origin, username=username, password=password)

    @property
    def allowed_hosts(self):
        local = ['127.0.0.1', 'localhost', '[::1]', 'testserver']
        return [*local, urlsplit(self.origin).hostname] if self.public else local

    def authorized(self, header):
        try:
            scheme, token = (header or '').split(' ', 1)
            if scheme.lower() != 'basic':
                return False
            username, password = base64.b64decode(token, validate=True).decode('utf-8').split(':', 1)
            user_ok = hmac.compare_digest(username.encode(), self.username.encode())
            password_ok = hmac.compare_digest(password.encode(), self.password.encode())
            return user_ok and password_ok
        except (ValueError, UnicodeError):
            return False


class DemoRateLimit:
    """One shared group's expensive requests, for a single-process demo service."""
    def __init__(self, limit=12, window=60):
        self.limit, self.window = limit, window
        self.events = deque()
        self.lock = threading.Lock()

    def allow(self):
        now = time.monotonic()
        with self.lock:
            while self.events and now-self.events[0] >= self.window:
                self.events.popleft()
            if len(self.events) >= self.limit:
                return False
            self.events.append(now)
            return True


EXPENSIVE_PATHS = {'/api/chat', '/api/ask', '/api/plan', '/api/agent',
                   '/api/places/search', '/api/places/resolve', '/api/amap/search', '/api/amap/route', '/api/walking-map'}
