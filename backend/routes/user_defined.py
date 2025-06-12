"""
All custom route logic must go here.
"""

import json
import os
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import Annotated, List

import dotenv
import httpx
from aiolimiter import AsyncLimiter
from fastapi import APIRouter, HTTPException, Query, Request
from routes.models import (
    EnableDependenciesModel,
    InstanceRunResponse,
    JobLogsList,
    MirrorJobDefinitionsBatchRequest,
    MirrorJobDefinitionsBatchResponse,
    MirrorJobDefinitionsItemRequest,
    MirrorJobDefinitionsItemResponse,
)
from utils.passthrough import Passthrough

router = APIRouter()

dotenv.load_dotenv()
rest_server = os.getenv("ACTIVEBATCH_REST_SERVER")
passthrough = Passthrough(rest_server=rest_server)


# implement a rate-limited gateway API manager
limiter = AsyncLimiter(max_rate=10, time_period=1)  # 10 requests per second


# 1. given a json with path and enable status, match each path's enabled/disabled status to V14 and turn it on
@router.post("/mirror")
async def mirror_job_status(
    objects: MirrorJobDefinitionsBatchRequest, request: Request
):
    """
    Mirror the job status to V14.
    """
    # rebuild the request
    headers = {
        "content-type": "application/json",
        "authorization": request.headers.get("authorization"),
    }
    all_responses = []
    for obj in objects.definitions:
        # ensure path ends with '$' as per ActiveBatch requirement
        # see Introduction section of https://fcvmpdactbapp01.hpsj.com/activebatch/api/help/index#section/Introduction
        path = obj.path if obj.path.endswith("$") else f"{obj.path}$"

        # create a dynamic request body based on `path` and `status` per ActiveBatch API
        # see https://fcvmpdactbapp01.hpsj.com/activebatch/api/help/index#operation/Objects_SetStatus
        status = "enabled" if obj.enabled else "disabled"
        body = {
            "value": status,
            "auditFields": objects.auditFields,
        }

        # custom receive function to provide the dynamic body
        async def custom_receive():
            return {"type": "http.request", "body": json.dumps(body).encode()}

        # build new request
        dynamic_request = Request(
            scope={
                **request.scope,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            },
            receive=custom_receive,
        )

        # pass the rebuilt request to the passthrough handler
        response = await passthrough.handle_passthrough(
            method="PUT", path=f"objects/{path}/status", request=dynamic_request
        )

        # append each response detail to the list
        all_responses.append(
            MirrorJobDefinitionsItemResponse(
                request=MirrorJobDefinitionsItemRequest(
                    path=obj.path, enabled=obj.enabled
                ),
                response=json.loads(
                    # extract response and convert to a JSON-serializable object
                    response.body.decode("utf-8")
                ),
                succeeded=response.status_code == 200,
            )
        )

    # construct a batch response object
    batch_response = MirrorJobDefinitionsBatchResponse(results=all_responses)

    # write the batch response to a log file using the precalculated batch id
    # TODO(@agenovia) this is a placeholder; use proper logging library
    with open(rf"..\logs\{batch_response.batch_id}.json", "w") as f:
        f.write(batch_response.model_dump_json(indent=4))

    return batch_response


# 2. given an ID or a path, get the logs of that job's instances
@router.get("/logs")
async def get_logs(query: Annotated[JobLogsList, Query()], request: Request):
    """
    Get logs for a job or job instance.

    Parameters:
        - key: The job ID or path.
        - from_datetime: The start datetime in ISO format.
        - to_datetime: The end datetime in ISO format.
        - limit: Optional number of logs to fetch.
    """

    response = await passthrough.handle_passthrough(
        method="GET", path=f"instances", request=request, params=query.model_dump()
    )

    if response.status_code != 200:
        return response

    instances = json.loads(response.body.decode("utf-8"))

    # for each instance, get the logs and attach to the instance object
    for instance in instances:
        instance["log"] = (
            await passthrough.handle_passthrough(
                method="GET",
                path=f"instances/{instance['key']['id']}/log",
                request=request,
            )
        ).body.decode("utf-8")
    return instances


@router.get("/plans/{templateId}/logs")
async def get_plan_logs(templateId: int, request: Request):
    """
    Get logs for a plan.

    Parameters:
        - key: The plan ID or path.
        - from_datetime: The start datetime in ISO format.
        - to_datetime: The end datetime in ISO format.
        - limit: Optional number of logs to fetch.
    """
    # first we look up the info of the object and ensure it is a plan
    info = await passthrough.handle_passthrough(
        method="GET", path=f"objects/{templateId}/info", request=request
    )

    if info.status_code != 200:
        return info

    try:
        json_info = json.loads(info.body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Error decoding JSON response from ActiveBatch.",
        )

    object_type = json_info.get("type")
    if not object_type == "plan":
        raise HTTPException(
            status_code=400,
            detail=f"The provided ID is of type '{object_type}'. Expected type 'plan'.",
        )

    # if is_plan, then we need to:
    # 1. get the plan instances
    # 2. for each instance, get the batch: https://fcvmpdactbapp01.hpsj.com/activebatch/api/v1/batches/{instanceId}?templateId={templateId}&level=children
    # 3. for each batch, get the logs

    return info


# 3. given a job ID or path, enable all of the dependencies of that job
@router.post("/enable_dependencies")
async def enable_dependencies(key: List[EnableDependenciesModel]):
    """
    Enable all dependencies for a job.

    Parameters:
        - key: The job ID or path.
    """
    return {"message": f"Enabling dependencies for {key}."}


@router.get("/last_run")
async def get_last_run(
    templateId: Annotated[
        str, Query(description="Job ID or path to check for next run.")
    ],
):
    """
    Grabs details from the last run times of a job.

    Algorithm:

    1. Make a call to `/objects/{templateId}` to get the object's status and type.
    2. Make a call to `/instances?templateId={templateId}&startDate={startDate}&endDate={endDate}` to get past and future instances.
        - Use a default start date of "2025-01-01T00:00:00Z" to ensure we get all instances.
        - Set endDate to 45 days in the future to ensure we capture future runs.
    3. If the instance exists, retrieve its details including start and end times, status, and log.

    Parameters:
        - key: The job ID or path.
    """
    _default_startdate = "2025-01-01T00:00:00Z"

    async with httpx.AsyncClient() as client:
        instances = await client.get(
            "http://localhost:42000/instances",
            params={
                "templateId": templateId,
                "startDate": _default_startdate,
            },
        )

    # 204 means no instances found, but the object is valid
    if instances.status_code == 204:
        return InstanceRunResponse(
            startTime=None,
            endTime=None,
            status=f"Not run since {_default_startdate}",
            instanceId=None,
            log=None,
            templateId=templateId,
        )

    # 404 means the object does not exist
    if instances.status_code == 404:
        return instances.json()

    ret = instances.json()[0]

    try:
        async with httpx.AsyncClient() as client:
            log = await client.get(
                f"http://localhost:42000/instances/{ret['key']['id']}/log",
            )
        return InstanceRunResponse(
            startTime=ret["beginExecutionTime"],
            endTime=ret["endExecutionTime"],
            status=ret["state"],
            instanceId=ret["key"]["id"],
            log=log.json()["content"],
            templateId=templateId,
        )
    except (JSONDecodeError, IndexError, KeyError):
        return InstanceRunResponse(
            startTime=ret["beginExecutionTime"],
            endTime=ret["endExecutionTime"],
            status=ret["state"],
            instanceId=ret["key"]["id"],
            log=None,
            templateId=templateId,
        )


@router.get("/next_run")
async def get_next_run(
    templateId: Annotated[
        str, Query(description="Job ID or path to check for next run.")
    ],
):
    """
    Grabs details from the last run times of a job.

    Algorithm:

    1. Make a call to `/objects/{templateId}` to get the object's status and type.
    2. Make a call to `/instances?templateId={templateId}&startDate={startDate}&endDate={endDate}` to get past and future instances.
        - Use a default start date of "2025-01-01T00:00:00Z" to ensure we get all instances.
        - Set endDate to 45 days in the future to ensure we capture future runs.
    3. If the instance exists, retrieve its details including start and end times, status, and log.

    Parameters:
        - key: The job ID or path.
    """
    _default_enddate = (datetime.now() + timedelta(days=45)).isoformat()
    print(_default_enddate)

    async with httpx.AsyncClient() as client:
        instances = await client.get(
            "http://localhost:42000/instances",
            params={
                "templateId": templateId,
                "endDate": _default_enddate,
                "states": "notRun",
                "pageSize": 1000,
                "oldestFirst": True,  # to get the next run first
            },
        )

    # 204 means no instances found, but the object is valid
    if instances.status_code == 204:
        return InstanceRunResponse(
            startTime=None,
            endTime=None,
            status=f"No planned runs from now til {_default_enddate}",
            instanceId=None,
            log=None,
            templateId=templateId,
        )

    # 404 means the object does not exist
    if instances.status_code == 404:
        return instances.json()

    return InstanceRunResponse(
        startTime=instances.json()[0]["beginExecutionTime"],
        endTime=instances.json()[0]["endExecutionTime"],
        status=instances.json()[0]["state"],
        instanceId=instances.json()[0]["key"]["id"],
        log=None,
        templateId=templateId,
    )


@router.get("/get_triggers")
async def get_triggers(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job ID or path to check for next run.")
    ],
):
    """
    Get all triggers.
    """
    templateId = templateId.strip()
    if templateId.isdigit():
        # if templateId is a number, we assume it's an ID
        path = f"objects/{templateId}/eventTriggers"
    else:
        # if templateId is a path, we assume it's a path
        path = f"objects/{templateId}$/eventTriggers"

    response = await passthrough.handle_passthrough(
        method="GET", path=path, request=request
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Error fetching triggers: {response.body.decode('utf-8')}",
        )

    return json.loads(response.body.decode("utf-8"))
