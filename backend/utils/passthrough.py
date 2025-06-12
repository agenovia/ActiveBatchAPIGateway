import json
import logging
from json import JSONDecodeError

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class Passthrough:
    def __init__(self, rest_server: str):
        self.rest_server = rest_server

    async def handle_passthrough(
        self, method: str, path: str, request: Request, params=None
    ):
        # construct the real server's URL
        real_url = f"{self.rest_server}/{path}"

        if request.query_params:
            logger.debug("Query parameters: %s", request.query_params)
            # if the original call had query parameters, append them to the URL
            real_url += f"?{request.query_params}"

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
                    method, real_url, json=body, headers=headers, params=params
                )

            try:
                # Try to parse the response as JSON
                response_content = response.json()
            except (ValueError, JSONDecodeError):
                # If parsing fails, fallback to raw response text or None
                response_content = response.text or None

            if response.status_code != 204:
                return JSONResponse(
                    content=response_content, status_code=response.status_code
                )
            else:
                # For 204 No Content, return an empty Response
                return Response(status_code=204)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
