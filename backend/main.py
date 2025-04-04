import os

import dotenv
from dependencies.authorization import AuthDependency
from fastapi import APIRouter, Depends, FastAPI, Request
from middlewares.login import LoginMiddleware
from routes.user_defined import router as user_defined_router
from utils.passthrough import Passthrough

app = FastAPI()

# load our environment variables
dotenv.load_dotenv()
# get the environment variables
rest_server, jss_server, username, password, superuser_key = (
    os.getenv("ACTIVEBATCH_REST_SERVER"),
    os.getenv("ACTIVEBATCH_JSS_SERVER"),
    os.getenv("SERVICE_ACCOUNT_USERNAME"),
    os.getenv("SERVICE_ACCOUNT_PASSWORD"),
    os.getenv("SUPERUSER_KEY"),
)

# login middleware handles the auth flow to the ActiveBatch REST API
# and updates the request headers with the token for subsequent calls
app.add_middleware(
    LoginMiddleware,
    rest_server=rest_server,
    jss_server=jss_server,
    username=username,
    password=password,
)

# instantiate our AuthDependency by passing the superuser_key
# this same key must be present in the Authorization header of the request
# to allow access to certain calls on the gateway
auth_dependency = AuthDependency(superuser_key=superuser_key)

# setup our routers here; all custom routes must go in the /routes directory
passthrough_router = APIRouter()
passthrough = Passthrough(rest_server=rest_server)


@passthrough_router.get("/{path:path}")
async def get_passthrough(path: str, request: Request):
    return await passthrough.handle_passthrough("GET", path, request)


@passthrough_router.post("/{path:path}", dependencies=[Depends(auth_dependency)])
async def post_passthrough(path: str, request: Request):
    return await passthrough.handle_passthrough("POST", path, request)


@passthrough_router.put("/{path:path}", dependencies=[Depends(auth_dependency)])
async def put_passthrough(path: str, request: Request):
    return await passthrough.handle_passthrough("PUT", path, request)


@passthrough_router.delete("/{path:path}", dependencies=[Depends(auth_dependency)])
async def delete_passthrough(path: str, request: Request):
    return await passthrough.handle_passthrough("DELETE", path, request)


@passthrough_router.patch("/{path:path}", dependencies=[Depends(auth_dependency)])
async def patch_passthrough(path: str, request: Request):
    return await passthrough.handle_passthrough("PATCH", path, request)


# takes precedence and is tried first
app.include_router(user_defined_router)

# this passthrough router will handle all requests that are not caught by the other routers
app.include_router(passthrough_router)
