import json
import logging
from json import JSONDecodeError
from typing import Optional

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class Passthrough:
    """
    The Passthrough class acts as a gateway for forwarding HTTP requests to another REST server.
    It helps centralize error handling, logging, and request forwarding, so you don't have to repeat
    this logic in every route.

    Main Features:
    - Forwards HTTP requests (GET, POST, etc.) to the configured REST server.
    - Handles errors and logs important information for debugging.
    - Manages authorization headers for security.
    - Handles both JSON and non-JSON responses.

    How to Use:
    ```python
    from backend.utils.passthrough import Passthrough

    passthrough = Passthrough(rest_server="http://real-server.com/api")
    response = await passthrough.handle_passthrough(
        method="GET",
        path="endpoint",
        request=request,
        params={"param1": "value1"}
    )
    ```

    The response is a FastAPI `Response` object, so you can return it directly from your route.

    Typical Use Cases:
    1. Creating server-side utility functions (UDFs) that need to call the REST API multiple times.
    2. Filtering or processing data from intermediate API calls.
    3. Providing a consistent API interface for clients or other systems.

    Example: Filtering a Response
    ```python
    from backend.utils.passthrough import Passthrough

    passthrough = Passthrough(rest_server="http://real-server.com/api")
    response = await passthrough.handle_passthrough(
        method="GET",
        path="endpoint",
        request=request,
        params={"param1": "value1"}
    )

    if response.status_code != 200:
        return response

    response_content = json.loads(response.body.decode("utf-8"))

    # Example: filter only items of type "schedule"
    filtered_schedules = [
        item for item in response_content if item.get("type") == "schedule"
    ]
    ```
    """

    def __init__(self, rest_server: str):
        self.rest_server = rest_server

    async def handle_passthrough(
        self, method: str, path: str, request: Request, params: Optional[dict] = None
    ):
        # construct the real server's URL
        real_url = f"{self.rest_server}/{path}"

        all_params = {**dict(request.query_params), **(params or {})}

        logger.debug("Real URL: %s", real_url)

        try:
            # extract body and headers
            try:
                # if the request has a body, decode it
                body = json.loads((await request.body()).decode("utf-8"))
                logger.debug("Request body: %s", body)
            except JSONDecodeError as e:
                body = None
                logger.debug("No body found in request: %s", e)

            auth = request.headers.get("authorization")
            headers = {"content-type": "application/json", "authorization": auth}
            logger.debug("Request headers: %s", headers)

            # make the HTTP request asynchronously
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.request(
                    method, real_url, json=body, headers=headers, params=all_params
                )

            try:
                # Try to parse the response as JSON
                response_content = response.json()
            except (ValueError, JSONDecodeError):
                # If parsing fails, fallback to raw response text or None
                response_content = response.text or None

            if response.status_code != 204:
                return JSONResponse(
                    content=response_content,
                    status_code=response.status_code,
                )
            else:
                # For 204 No Content, return an empty Response
                return Response(status_code=204)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
