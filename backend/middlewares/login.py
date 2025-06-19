import time

import httpx
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


class LoginMiddleware(BaseHTTPMiddleware):
    """Authenticates to the ActiveBatch REST API and updates the request headers with the token."""

    def __init__(
        self, app, rest_server: str, username: str, password: str, jss_server: str
    ):
        super().__init__(app)
        self.rest_server = rest_server
        self.username = username
        self.password = password
        self.jss_server = jss_server
        self._token = None
        self._token_expiry = 0

    async def _get_token(self):
        async with httpx.AsyncClient(verify=False) as client:
            login_response = await client.post(
                f"{self.rest_server}/login",
                json={
                    "username": self.username,
                    "password": self.password,
                    "jobScheduler": self.jss_server,
                },
            )
        if login_response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Proxy server credentials are invalid. (@agenovia)",
            )
        token = login_response.json().get("token")
        self._token = token
        self._token_expiry = time.time() + (59 * 60)  # 59 minutes from now

    async def dispatch(self, request: Request, call_next):
        # Refresh token if expired or not set
        if not self._token or time.time() > self._token_expiry:
            await self._get_token()

        # if a token was previously provided, we use this as our superuser_key and is used only to authenticate internally within the gateway
        if old_token := request.headers.get("Authorization"):
            request.state.superuser_key = old_token.split(" ")[1].strip()
        else:
            request.state.superuser_key = None

        # get the existing headers
        headers = dict(request.scope["headers"])
        # update with the auth token
        headers[b"authorization"] = f"Bearer {self._token}".encode("utf-8")
        headers[b"content-type"] = b"application/json"

        # update the scope
        request.scope["headers"] = [(k, v) for k, v in headers.items()]

        # call next with updated headers
        response = await call_next(request)
        return response
