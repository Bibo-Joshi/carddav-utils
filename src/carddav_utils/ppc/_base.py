from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import Self

from aiorem import AbstractResourceManager
from pydantic import BaseModel, ConfigDict

from .._profilepictureinfo import ProfilePictureInfo


class BaseCrawlerConfig(BaseModel):
    """Configuration for a BaseCrawler."""

    model_config = ConfigDict(extra="forbid")


class BaseCrawler[CT: BaseCrawlerConfig](AbstractResourceManager):
    """Base class for crawlers that extract phone numbers corresponding profile pictures."""

    @abstractmethod
    async def crawl(self) -> AsyncGenerator[ProfilePictureInfo]:
        """Crawl the data source and yield tuples of phone number and a tuple of
        (name, photo bytes, mime type)."""

    @classmethod
    @abstractmethod
    def from_config(cls, config: CT) -> Self:
        """Create a crawler instance from the given configuration."""
