import asyncio
import mimetypes
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pyrogram import Client
from pyrogram.types import User

from .._utils import get_logger
from ._base import BaseCrawler, ProfilePictureInfo
from ._utils import phone_number_to_string

if TYPE_CHECKING:
    from io import BytesIO

_LOGGER = get_logger(Path(__file__), "TelegramCrawler")


class TelegramCrawler(BaseCrawler):
    """Crawler for Telegram contacts and their profile pictures.
    Uses the MTProto API via the `pyrogram`/`kurigram` library.
    """

    def __init__(self, api_id: int, api_hash: str, session_name: str):
        self._client = Client(session_name, api_id, api_hash)

    async def acquire_resources(self) -> None:
        _LOGGER.debug("Acquiring Telegram client resources")
        await self._client.__aenter__()

    async def release_resources(self) -> None:
        _LOGGER.debug("Releasing Telegram client resources")
        await self._client.__aexit__(None, None, None)

    async def crawl(self) -> AsyncGenerator[ProfilePictureInfo]:  # type: ignore[override]
        contacts = await self._client.get_contacts()
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self._process_contact(contact)) for contact in contacts]
            async for task in asyncio.as_completed(tasks):
                if (result := await task) is not None:
                    yield result

    async def _process_contact(self, contact: User) -> ProfilePictureInfo | None:
        if not (phone_number := contact.phone_number) or not (photo := contact.photo):
            _LOGGER.debug(
                "Skipping contact %s (%s), no phone number or no profile photo.",
                contact.first_name,
                contact.id,
            )
            return None

        download_photo = await self._client.download_media(photo.big_file_id, in_memory=True)
        if download_photo is None:
            _LOGGER.warning(
                "Failed to download profile picture for contact %s (%s).",
                contact.first_name,
                contact.id,
            )
            return None

        download_photo = cast("BytesIO", download_photo)
        _LOGGER.debug(
            "Retrieved profile picture for contact %s (%s).", contact.first_name, contact.id
        )
        return ProfilePictureInfo(
            phone_number=phone_number_to_string(f"+{phone_number}"),
            name=download_photo.name,
            photo=bytes(download_photo.getbuffer()),
            mime_type=mimetypes.guess_type(download_photo.name)[0] or "application/octet-stream",
        )
