"""
All custom route logic must go here.
"""

import json
import os
from typing import Annotated, List

import dotenv
from fastapi import APIRouter, HTTPException, Query, Request
from routes.models import (
    EnableDependenciesModel,
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
    errors = 0
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

        if response.status_code != 200:
            errors += 1

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
    summary = f"Mirroring completed with {errors} error(s)"
    batch_response = MirrorJobDefinitionsBatchResponse(
        results=all_responses, message=summary
    )

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
        is_plan = json_info.get("type") == "plan"
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Error decoding JSON response from ActiveBatch.",
        )

    if not is_plan:
        raise HTTPException(
            status_code=400,
            detail=f"The provided ID is of type '{json_info.get('type')}'. Expected type 'plan'.",
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
