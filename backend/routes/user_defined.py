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
from dependencies.authorization import AuthDependency
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from routes.models import (
    EnableDependenciesModel,
    InstanceRunResponse,
    MirrorJobDefinitionsBatchRequest,
    MirrorJobDefinitionsBatchResponse,
    MirrorJobDefinitionsItemRequest,
    MirrorJobDefinitionsItemResponse,
)
from utils.passthrough import Passthrough

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

# instantiate our AuthDependency by passing the superuser_key
# this same key must be present in the Authorization header of the request
# to allow access to certain calls on the gateway
auth_dependency = AuthDependency(superuser_key=superuser_key)


router = APIRouter()

dotenv.load_dotenv()
rest_server = os.getenv("ACTIVEBATCH_REST_SERVER")

# The passthrough object is our gateway to the ActiveBatch REST API.
# It handles all intermediary requests to the ActiveBatch REST API.
# And handles the request and response cycle.
passthrough = Passthrough(rest_server=rest_server)


# 1. given a json with path and enable status, match each path's enabled/disabled status to V14 and turn it on
@router.post("/mirror", dependencies=[Depends(auth_dependency)])
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


# # 2. given an ID or a path, get the logs of that job's instances
# @router.get("/logs")
# async def get_logs(query: Annotated[JobLogsList, Query()], request: Request):
#     """
#     Get logs for a job or job instance.

#     Parameters:
#         - key: The job ID or path.
#         - from_datetime: The start datetime in ISO format.
#         - to_datetime: The end datetime in ISO format.
#         - limit: Optional number of logs to fetch.
#     """

#     response = await passthrough.handle_passthrough(
#         method="GET", path=f"instances", request=request, params=query.model_dump()
#     )

#     if response.status_code != 200:
#         return response

#     instances = json.loads(response.body.decode("utf-8"))

#     # for each instance, get the logs and attach to the instance object
#     for instance in instances:
#         instance["log"] = (
#             await passthrough.handle_passthrough(
#                 method="GET",
#                 path=f"instances/{instance['key']['id']}/log",
#                 request=request,
#             )
#         ).body.decode("utf-8")
#     return instances


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
@router.post("/enable_dependencies", dependencies=[Depends(auth_dependency)])
async def enable_dependencies(key: List[EnableDependenciesModel]):
    """
    Enable all dependencies for a job.

    Parameters:
        - key: The job ID or path.
    """
    return {"message": f"Enabling dependencies for {key}."}


@router.get("/last_run")
async def get_last_run(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job/Plan ID or Full Path to retrieve last run details.")
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

    params = {
        "templateId": templateId,
        "startDate": _default_startdate,
    }

    response = await passthrough.handle_passthrough(
        method="GET", path="instances", request=request, params=params
    )

    # 404 means the object does not exist
    if response.status_code == 404:
        return response

    # 204 means no instances found, but the object is valid
    if response.status_code == 204:
        return InstanceRunResponse(
            startTime=None,
            endTime=None,
            status=f"Not run since {_default_startdate}",
            instanceId=None,
            log=None,
            templateId=templateId,
        )

    response_parsed = json.loads(response.body.decode("utf-8"))
    ret = response_parsed[0]

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


@router.get("/logs")
async def get_logs(request: Request, instance_id: str):
    """
    Helper function to get logs for a specific instance.
    """

    response = await passthrough.handle_passthrough(
        method="GET",
        path=f"instances/{instance_id}/log",
        request=request,
    )
    return response


@router.get("/next_run")
async def get_next_run(
    request: Request,
    templateId: Annotated[
        str,
        Query(
            description="Job/Plan ID or Full Path to retrieve next scheduled run details"
        ),
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

    params = {
        "templateId": templateId,
        "endDate": _default_enddate,
        "states": "notRun",
        "pageSize": 1000,
        "oldestFirst": True,  # to get the next run first
    }

    response = await passthrough.handle_passthrough(
        method="GET", path="instances", request=request, params=params
    )

    # 404 means the object does not exist
    if response.status_code == 404:
        return response

    # 204 means no instances found, but the object is valid
    if response.status_code == 204:
        return InstanceRunResponse(
            startTime=None,
            endTime=None,
            status=f"No planned runs from now until {_default_enddate}",
            instanceId=None,
            log=None,
            templateId=templateId,
        )

    response_json = json.loads(response.body.decode("utf-8"))

    return InstanceRunResponse(
        startTime=response_json[0]["beginExecutionTime"],
        endTime=response_json[0]["endExecutionTime"],
        status=response_json[0]["state"],
        instanceId=response_json[0]["key"]["id"],
        log=None,
        templateId=templateId,
    )


@router.get("/triggers")
async def get_triggers(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job/Plan ID or Full Path to check for event triggers.")
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
        return response

    return json.loads(response.body.decode("utf-8"))


@router.get("/file_triggers")
async def get_file_triggers(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job/Plan ID or Full Path to check for file triggers.")
    ],
):
    """
    Get all file triggers.
    """

    response = await get_triggers(request, templateId)

    try:
        if response.status_code != 200:
            return response
    except AttributeError:
        pass

    # Filter out only file triggers
    file_triggers = [trigger for trigger in response if trigger.get("$type") == "File"]

    return file_triggers if file_triggers else Response(status_code=204)


@router.get("/object_lite")
async def get_object_lite(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job/Plan ID or Full Path to check for status.")
    ],
):
    """
    Get the status of a job or plan.

    Parameters:
        - templateId (str): Job/Plan ID or full path to check for status.

    Returns:
        - 200: Status of the specified job or plan.
        - 404: If the object does not exist.
    """
    templateId = templateId.strip()
    if templateId.isdigit():
        # if templateId is a number, we assume it's an ID
        path = f"objects/{templateId}"
    else:
        # if templateId is a path, we assume it's a path
        path = f"objects/{templateId}$"

    response = await passthrough.handle_passthrough(
        method="GET", path=path, request=request
    )

    if response.status_code != 200:
        return response

    response_asdict = json.loads(response.body.decode("utf-8"))

    return response_asdict


@router.get("/schedules")
async def get_schedules(
    request: Request,
    templateId: Annotated[
        str, Query(description="Job/Plan ID or Full Path to check for schedules.")
    ],
):
    """
    Retrieve all schedules associated with a given job or plan.

    Parameters:

    - templateId (str): Job/Plan ID or full path to check for schedules.

    Returns:

    - 200: List of schedule objects associated with the specified job or plan.
    - 204: No schedules found for the given template.
    - Other: Forwards any non-200 response from the ActiveBatch API as-is.

    Notes:

    - The ActiveBatch API returns a 204 No Content status for non-existent objects instead of 404 Not Found.
    - This endpoint explicitly handles and forwards such cases for accurate troubleshooting.

    **responses**:

    200: OK
    """
    templateId = templateId.strip()
    if templateId.isdigit():
        # if templateId is a number, we assume it's an ID
        path = f"objects/{templateId}/associations"
    else:
        # if templateId is a path, we assume it's a path
        path = f"objects/{templateId}$/associations"

    # BIG WARNING: ActiveBatch API returns a 204 No Content for objects that do not exist (i.e. deleted or otherwise nonexistent on the scheduler)
    # ActiveBatch API can be enhanced by returning 404 Not Found instead
    # so we need to handle this case explicitly
    response = await passthrough.handle_passthrough(
        method="GET", path=path, request=request
    )

    # if the response is not 200, we return it as is to preserve all error details for troubleshooting
    if response.status_code != 200:
        return response

    # load response body as JSON
    response_asdict = json.loads(response.body.decode("utf-8"))

    # filter out only schedules
    schedules = [r for r in response_asdict if r["type"] == "schedule"]

    # we need to enrich each schedule with the object details
    # this is done by making a call to /objects/{id} for each schedule
    # object details makes the previous list redundant, so we just replace it with better information
    enriched_schedules = []
    for schedule in schedules:
        object_details = await passthrough.handle_passthrough(
            method="GET",
            path=f"objects/{schedule['id']}/full",
            request=request,
        )
        if object_details.status_code == 200:
            # enrich the schedule with the object details
            enriched_schedules.append(json.loads(object_details.body.decode("utf-8")))
        else:
            enriched_schedules.append(
                {
                    **schedule,
                    "object": f"Failed to retrieve object details: {object_details.status_code}",
                }
            )

    # if no schedules found, return a 204 No Content response
    fallback = Response(status_code=204)

    return enriched_schedules if enriched_schedules else fallback
