import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import pytz
from pydantic import BaseModel, ConfigDict, Field


class BaseConfig(BaseModel):
    # disallow extra fields in the model
    model_config = ConfigDict(extra="forbid")


class Keyed(BaseConfig):
    """
    Model for any method requiring a key (path or id) attribute.
    """

    templateId: Union[str, int]


class Unkeyed(BaseConfig):
    """
    Unkeyed objects are not expected to have a key attribute.
    """

    ...


class EnableDependenciesModel(Keyed):
    """
    Model for enabling dependencies.
    """

    ...


class JobLogsList(Keyed):
    """
    Model for job logs.
    """

    # WARNING: ActiveBatch V14 date parsing starts at 2020 for whatever reason
    # what this means is that you cannot choose a date starting before 2020-01-01
    startDate: Optional[str] = Field(
        default_factory=lambda: datetime(year=2020, month=1, day=1).isoformat()
    )
    endDate: Optional[str] = Field(default_factory=lambda: datetime.now().isoformat())
    pageSize: Optional[int] = 10
    pageIndex: Optional[int] = 1
    oldestFirst: bool = False

    def model_post_init(self, context: Any):
        # this could also be done with `default_factory`:
        startDate = datetime.fromisoformat(self.startDate)
        endDate = datetime.fromisoformat(self.endDate)

        assert startDate < datetime.now(), "startDate cannot be in the future"

        assert startDate < endDate, "startDate must be before endDate"

        assert self.pageSize > 0, "pageSize must be greater than 0"

        assert self.pageIndex > 0, "pageIndex must be greater than 0"

        assert self.pageSize <= 100, "pageSize cannot be greater than 100"

        self.templateId = self.templateId


class MirrorJobDefinitionsItemRequest(BaseConfig):
    path: str
    enabled: bool


class MirrorJobDefinitionsBatchRequest(BaseConfig):
    """
    Model for mirroring job status.
    """

    # when performing mirror operations, we cannot use IDs so we must pass the paths
    definitions: List[MirrorJobDefinitionsItemRequest]
    auditFields: Optional[List[Dict[str, str]]]


# Model for individual response data
class MirrorJobDefinitionsItemResponse(BaseConfig):
    request: MirrorJobDefinitionsItemRequest
    response: Union[None, Dict[str, Any]]  # holds the actual response content or data
    succeeded: bool = True


# Model for the final aggregated response
class MirrorJobDefinitionsBatchResponse(BaseConfig):
    timestamp: datetime = Field(default=None)
    batch_id: str = Field(default=None)
    message: str = Field(default=None)
    count: int = Field(default=0)
    results: List[MirrorJobDefinitionsItemResponse]
    _timestamp = datetime.now()

    def model_post_init(self, __context):
        self.timestamp = self._timestamp
        self.batch_id = self._timestamp.strftime(r"%Y%m%d%H%M%S%f")
        self.count = len(self.results)
        self.message = f"Mirroring completed with {self.error_count()} error(s)"

    def error_count(self) -> int:
        """
        Returns the number of errors in the batch response.
        """
        count = 0
        for i in self.results:
            if not i.succeeded:
                count += 1
        return count


class InstanceRunResponse(BaseConfig):
    """
    Model for the last run response.
    """

    templateId: Union[str, int]
    instanceId: Optional[int] = None
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    status: Optional[str] = None
    log: Optional[str] = None
    log_contains_triggerwords: bool = Field(
        default=False, description="True when log matches any triggerword", init=False
    )
    anomalous: bool = Field(
        default=False, description="Anomalous status of the job run", init=False
    )

    def convert_to_local(self, dt: str) -> str:
        """
        Converts a datetime string to a local datetime string.
        """
        try:
            _dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S.%f")
            _dt = _dt.replace(tzinfo=pytz.utc)

            # Convert to local timezone (e.g., Pacific Time)
            local_tz = pytz.timezone("America/Los_Angeles")
            local_dt = _dt.astimezone(local_tz)

            return local_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OverflowError):
            # If the datetime string is invalid, return None
            return None

    def _log_contain_triggerwords(self) -> bool:
        """
        Checks if the log contains the set of triggerwords.
        """
        __triggerwords = {"error", "failed", "exception"}
        reg = re.compile("|".join([s.strip() for s in __triggerwords]), re.IGNORECASE)
        if len(reg.findall(self.log or "")) > 0:
            return True
        return False

    def _is_anomalous(self) -> bool:
        """
        Determines if the job run is anomalous based on its status.
        """
        if self.status in ["succeeded"] and self.log_contains_triggerwords:
            return True
        return False

    def model_post_init(self, __context):
        if self.startTime:
            self.startTime = self.convert_to_local(self.startTime)
        if self.endTime:
            self.endTime = self.convert_to_local(self.endTime)
        if self.log:
            self.log_contains_triggerwords = self._log_contain_triggerwords()
            self.anomalous = self._is_anomalous()
