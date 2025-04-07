from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

config = ConfigDict(extra="forbid")


class Keyed(BaseModel):
    """
    Model for any method requiring a key (path or id) attribute.
    """

    model_config = config
    templateId: Union[str, int]


class Unkeyed(BaseModel):
    """
    Unkeyed objects are not expected to have a key attribute.
    """

    model_config = config


class MirrorJobStatusModel(BaseModel):
    """
    Model for mirroring job status.
    """

    # when performing mirror operations, we cannot use IDs so we must pass the paths
    model_config = config
    path: str
    enabled: bool


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

        assert startDate < datetime.now(), "from_datetime cannot be in the future"

        assert startDate < endDate, "from_datetime must be before to_datetime"

        assert self.pageSize > 0, "pageSize must be greater than 0"

        assert self.pageIndex > 0, "pageIndex must be greater than 0"

        assert self.pageSize <= 100, "pageSize cannot be greater than 100"

        self.templateId = self.templateId


class MirrorActionRequest(BaseModel):
    path: str
    status: str


# Model for individual response data
class MirrorActionDetailResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    request: MirrorActionRequest
    response: Union[None, Dict[str, Any]]  # holds the actual response content or data

    def model_post_init(self, context: Any):
        # Ensure that the response is either None or a dictionary
        if self.response is None:
            self.response = "Change successful"


# Model for the final aggregated response
class MirrorActionBatchResponse(BaseModel):
    message: str
    results: List[MirrorActionDetailResponse]
