import asyncio
from pathlib import Path
from typing import Self

from aiorem import AbstractResourceManager
from caldav import aio as caldav_aio
from pydantic import BaseModel, ConfigDict

from ._utils import USER_AGENT, get_logger

_LOGGER = get_logger(Path(__file__), "CalDavClient")


class CalDavClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    calendar_url: str


class CalDavClient(AbstractResourceManager):
    def __init__(self, username: str, password: str, calendar_url: str) -> None:
        self._caldav_client: caldav_aio.AsyncDAVClient | None = None
        self._username: str = username
        self._password: str = password
        self._calendar_url: str = calendar_url
        self._principal: caldav_aio.Principal | None = None
        self._calendar: caldav_aio.Calendar | None = None

        # Let's limit the number of concurrent requests to avoid overwhelming the server.
        self.__semaphore = asyncio.BoundedSemaphore(50)

    @classmethod
    def from_config(cls, config: CalDavClientConfig) -> Self:
        return cls(
            username=config.username, password=config.password, calendar_url=config.calendar_url
        )

    async def acquire_resources(self) -> None:
        _LOGGER.debug(
            "Acquiring resources for CalDAV client with calendar URL: %s", self._calendar_url
        )
        self._calendar = await caldav_aio.get_calendar(
            url=self._calendar_url,
            username=self._username,
            password=self._password,
            headers={"User-Agent": USER_AGENT},
        )
        await self._calendar.__aenter__()  # type: ignore[union-attr]

    async def release_resources(self) -> None:
        if self._calendar is not None:
            await self._calendar.__aexit__(None, None, None)  # type: ignore[attr-defined]
        _LOGGER.debug(
            "Released resources for CalDAV client with calendar URL: %s", self._calendar_url
        )

    def __get_calendar(self) -> caldav_aio.Calendar:
        if self._calendar is not None:
            return self._calendar
        raise ValueError(
            "Calendar '%s' not found in cache. Call download_calendar_events_to_memory first.",
            self._calendar_url,
        )

    async def download_calendar_events_to_memory(self) -> dict[str, caldav_aio.Event]:
        """Downloads the entire calendar and returns a dictionary mapping UIDs to vCal event
        components."""
        async with self.__semaphore:
            calendar = self.__get_calendar()
            _LOGGER.debug("Downloading events from calendar: %s", self._calendar_url)
            events = await calendar.events()  # type: ignore[misc]
            return {event.id: event for event in events}

    async def add_event_to_calendar(self, event: caldav_aio.Event | str) -> None:
        """Adds a new event to the specified calendar."""
        async with self.__semaphore:
            calendar = self.__get_calendar()
            await calendar.add_event(event)  # type: ignore[misc]

    async def update_event_in_calendar(self, event: caldav_aio.Event | str) -> None:
        """Updates an existing event in the specified calendar."""
        async with self.__semaphore:
            calendar = self.__get_calendar()
            await calendar.add_event(event)  # type: ignore[misc]

    async def delete_event_from_calendar(self, event: caldav_aio.Event) -> None:
        """Deletes an event from the specified calendar."""
        async with self.__semaphore:
            await event.delete()  # type: ignore[misc]
