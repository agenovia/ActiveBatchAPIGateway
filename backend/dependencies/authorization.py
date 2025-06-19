from fastapi import HTTPException, Request


class AuthDependency:
    def __init__(self, superuser_key: str):
        self.superuser_key = superuser_key

    async def __call__(self, request: Request):
        # our login middleware mutates the request header and the superuser_key is stored in the request state
        # if the superuser_key is not set, we raise an HTTPException
        token = request.state.superuser_key

        # Validate the token
        if not token:
            raise HTTPException(status_code=401, detail="[Gateway] API key required")
        elif token != self.superuser_key.strip():
            raise HTTPException(status_code=401, detail="[Gateway] Mismatched API key")
