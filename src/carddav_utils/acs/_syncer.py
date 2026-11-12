import asyncio
import re
from collections.abc import Collection
from pathlib import Path
from typing import ParamSpec, TypeVar

import vobject
from aiorem import AbstractResourceManager, AbstractResourceManagerCollection
from caldav.aio import Event

from .. import CardDavClient
from .._caldavclient import CalDavClient
from .._utils import get_logger
from ._parser import ContactParser

P = ParamSpec("P")
T = TypeVar("T")


_DT_STAMP_PATTERN = re.compile(r"DTSTAMP:(\d{8}T\d{6}Z)")
_VCAL_PATTERN = re.compile(r"[A-Z-]+[:;]")

_LOGGER = get_logger(Path(__file__), "AnniversaryCalendarSyncer")


def _to_lines(text: str) -> set[str]:
    raw_lines = [
        # For some reason, NextCloud adds a whitespace at the beginning sometimes.
        # We remove it here to avoid unnecessary updates.
        line.removeprefix(" ")
        for line in text.splitlines()
        if line.strip() and not _DT_STAMP_PATTERN.match(line)
    ]
    lines = set()
    # iterate from last line to first. If we find a line that doesn't match the _VCAL_PATTERN,
    # we assume that it's a split line. We gather them until we find a line that matches
    # and join them together. This is to handle the case where a line is split across multiple
    # lines in the vCard/vCalendar format. Note that there could be multiple line splits.
    # Best effort approach, but should work for most cases.
    buffer: list[str] = []
    for line in reversed(raw_lines):
        if _VCAL_PATTERN.match(line):
            if buffer:
                # join the buffer and add to lines
                lines.add("".join([line, *list(reversed(buffer))]))
                buffer = []
            else:
                lines.add(line)
        else:
            buffer.append(line)
    if buffer:
        # join the buffer and add to lines
        lines.add("".join(reversed(buffer)))

    return lines


def _events_equal(a: str, b: str) -> bool:
    """Compare two event strings for equality, ignoring DTSTAMP lines and whitespace."""
    a_lines, b_lines = _to_lines(a), _to_lines(b)
    return a_lines == b_lines
    # Keeping this as is for debugging purposes, but commented out to avoid cluttering the logs.
    # equal = a_lines == b_lines
    # if not equal:
    #     print("============")
    #     print("\n".join(sorted(a_lines)))
    #     print("------------")
    #     print("\n".join(sorted(b_lines)))
    #     print("============")
    # return equal


class AnniversaryCalendarSyncer(AbstractResourceManagerCollection):
    """Syncs anniversary calendars to a CalDAV server.

    Args:
        target (CalDavClient): A mapping of target IDs (just some identifiers) to
            CalDAV clients to which the anniversary calendars will be stored.
        sources (Mapping[str, CardDavClient]): A mapping of source IDs (just some identifiers) to
            CardDAV clients from which the address books will be read to extract anniversary
            information.
        category_identifier (str): The category identifier used to filter and identify
            relevant anniversary information in the source address books. Categories must be in
            the format ``X-(B|D|A)R-<category_identifier>-P<trigger>``.

    """

    def __init__(
        self, target: CalDavClient, sources: dict[str, CardDavClient], category_identifier: str
    ) -> None:
        self._target: CalDavClient = target
        self._sources: dict[str, CardDavClient] = sources
        self._category_identifier: str = category_identifier

        self.__target_events: dict[str, Event] | None = None
        self.__source_vcards: dict[str, dict[str, vobject.base.Component]] | None = None

    @property
    def _resource_managers(self) -> Collection[AbstractResourceManager]:
        return [self._target, *list(self._sources.values())]

    def _target_events(self) -> dict[str, Event]:
        """Get the events for a specific target and calendar by its ID & name."""
        if self.__target_events is None:
            raise RuntimeError("Target events not loaded. Call initialize() first.")
        return self.__target_events

    def _source_vcards(self, source_id: str) -> dict[str, vobject.base.Component]:
        """Get the current state of a source address book by its ID."""
        if self.__source_vcards is None:
            raise RuntimeError("Source states not loaded. Call initialize() first.")
        if source_id not in self.__source_vcards:
            raise ValueError(f"Source ID '{source_id}' not found in source states.")
        return self.__source_vcards[source_id]

    async def initialize(self) -> None:
        """Initialize the creator by loading the current states of the target and sources."""
        async with asyncio.TaskGroup() as tg:
            target_task = tg.create_task(self._target.download_calendar_events_to_memory())
            source_tasks = {
                source_id: tg.create_task(source.download_address_book_to_memory())
                for source_id, source in self._sources.items()
            }

        self.__target_events = target_task.result()
        self.__source_vcards = {
            source_id: source_task.result() for source_id, source_task in source_tasks.items()
        }

    def _compute_events(self, source_id: str) -> dict[str, dict[str, vobject.base.Component]]:
        events = {}
        vcards = self._source_vcards(source_id)
        for uid, vcard in vcards.items():
            parser = ContactParser(vcard, self._category_identifier)
            events[uid] = parser.events()

        return events

    async def _handle_vcard_events(
        self, source_id: str, uid: str, events: dict[str, vobject.base.Component]
    ) -> None:
        """Handle a single event from a source address book."""
        _LOGGER.debug("Handling event for source '%s', vCard '%s':", source_id, uid)
        target_events = self._target_events()
        for event_id, event in events.items():
            # NextCloud likes P0D better than PT0S, but PT0S is hardcoded in icalendar
            # So we replace it here to avoid unnecessary updates.
            new_event_content = event.serialize().replace("PT0S", "P0D")

            if (target_event := target_events.get(event_id)) is not None:
                target_event_content = target_event.get_data()

                if _events_equal(target_event_content, new_event_content):
                    _LOGGER.debug(
                        "Skipping event %s from source %s, content is identical to target.",
                        event_id,
                        source_id,
                    )
                else:
                    _LOGGER.info("Updating event %s from source %s.", event_id, source_id)
                    await self._target.update_event_in_calendar(new_event_content)
                continue

            _LOGGER.info("Adding event %s from source %s.", event_id, source_id)
            await self._target.add_event_to_calendar(new_event_content)

    async def sync_calendars(self) -> None:
        """Syncs the anniversary calendars based on the source address books."""
        _LOGGER.info("Starting to sync anniversary calendars.")
        computed_events = {
            source_id: self._compute_events(source_id) for source_id in self._sources
        }
        async with asyncio.TaskGroup() as tg:
            for source_id, event_groups in computed_events.items():
                for uid, events in event_groups.items():
                    tg.create_task(self._handle_vcard_events(source_id, uid, events))

            # Remove superfluous events from the target calendar that are not present in any source
            target_events = self._target_events()
            flattened_source_event_ids = {
                event_id
                for event_groups in computed_events.values()
                for events in event_groups.values()
                for event_id in events
            }
            for target_event_id, target_event in target_events.items():
                if (
                    target_event.get_icalendar_component().get("x-carddav-utils-generated")
                    != "true"
                ):
                    _LOGGER.debug(
                        "Retaining non-generated event %s in target calendar.", target_event_id
                    )
                    continue
                if target_event_id not in flattened_source_event_ids:
                    _LOGGER.info(
                        "Removing superfluous event %s from target calendar.", target_event_id
                    )
                    await self._target.delete_event_from_calendar(target_event)

        # After syncing, we can clear the cached events and vcards to free up memory if needed.
        self.__target_events = None
        self.__source_vcards = None

    async def do_sync(self) -> None:
        await self.initialize()
        await self.sync_calendars()
        _LOGGER.info("Anniversary calendars synced.")
