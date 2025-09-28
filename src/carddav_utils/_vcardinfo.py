import datetime as dtm

from pydantic import BaseModel, ConfigDict


class VCardInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str
    etag: str
    content_type: str
    content_length: int
    last_modified: dtm.datetime
