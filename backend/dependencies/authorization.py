from fastapi import HTTPException, Request


class AuthDependency:
    def __init__(self, superuser_key: str):
        self.superuser_key = superuser_key

    async def __call__(self, request: Request):
        # Extract the token from the Authorization header
        # token = request.headers.get("Authorization").split(" ")[1].strip()
        token = request.state.superuser_key

        # Validate the token
        if not token or token != self.superuser_key.strip():
            raise HTTPException(status_code=401, detail="Invalid API key")
