import os

import dotenv
import httpx
from custom_routes import custom_router
from dependencies.authorization import AuthDependency
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from middlewares.login import LoginMiddleware

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


async def handle_passthrough(method: str, path: str, request: Request):
    # construct the real server's URL
    real_url = f"{rest_server}/{path}"

    if request.query_params:
        # if the original call had query parameters, append them to the URL
        real_url += f"?{request.query_params}"

    try:
        # extract body and headers
        body = await request.body()
        headers = dict(request.headers)

        # make the HTTP request asynchronously
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.request(
                method, real_url, data=body, headers=headers
            )

        # return the json response
        return JSONResponse(content=response.json(), status_code=response.status_code)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@passthrough_router.get("/{path:path}")
async def get_passthrough(path: str, request: Request):
    return await handle_passthrough("GET", path, request)


@passthrough_router.post("/{path:path}", dependencies=[Depends(auth_dependency)])
async def post_passthrough(path: str, request: Request):
    return await handle_passthrough("POST", path, request)


@passthrough_router.put("/{path:path}", dependencies=[Depends(auth_dependency)])
async def put_passthrough(path: str, request: Request):
    return await handle_passthrough("PUT", path, request)


@passthrough_router.delete("/{path:path}", dependencies=[Depends(auth_dependency)])
async def delete_passthrough(path: str, request: Request):
    return await handle_passthrough("DELETE", path, request)


@passthrough_router.patch("/{path:path}", dependencies=[Depends(auth_dependency)])
async def patch_passthrough(path: str, request: Request):
    return await handle_passthrough("PATCH", path, request)


# custom router takes precedence and is tried first
app.include_router(custom_router)

# this passthrough router will handle all requests that are not caught by the other routers
app.include_router(passthrough_router)
