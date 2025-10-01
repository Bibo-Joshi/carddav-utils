from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

import aiostream
from aiorem import AbstractResourceManager, AbstractResourceManagerCollection

from .._nextcloudstorage import NextCloudStorage
from ._base import BaseCrawler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from .._profilepictureinfo import ProfilePictureInfo


class ProfilePictureUploader(AbstractResourceManagerCollection):
    """Uploads profile pictures to NextCloudStorage from crawlers.

    Args:
        crawlers (Sequence[BaseCrawler]): A collection of crawlers that extract phone numbers
            and corresponding profile pictures.

            Important:
                Order matters! Crawlers earlier in the sequence have higher priority.
                If multiple crawlers provide a profile picture for the same phone number, the one
                from the crawler that appears first in the sequence will be used.
        nextcloud_storage (NextCloudStorage): The NextCloudStorage instance where
            profile pictures will be uploaded.
    """

    def __init__(
        self, crawlers: Sequence[BaseCrawler], nextcloud_storage: NextCloudStorage
    ) -> None:
        self._crawlers = crawlers
        self._nextcloud_storage = nextcloud_storage

    @property
    def _resource_managers(self) -> Sequence[AbstractResourceManager]:
        return [self._nextcloud_storage, *self._crawlers]

    async def do_upload(self) -> None:
        """Uploads profile pictures to NextCloudStorage from crawlers."""
        await self._nextcloud_storage.initialize()
        async with aiostream.streamcontext(
            aiostream.stream.merge(
                *(
                    cast("AsyncGenerator[ProfilePictureInfo]", crawler.crawl())
                    for crawler in self._crawlers
                )
            )
        ) as merged_stream:
            await self._nextcloud_storage.update_from_iterator(merged_stream)
