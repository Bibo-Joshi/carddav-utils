import asyncio
import re
from collections.abc import Collection, Mapping
from pathlib import Path

import vobject
from aiorem import AbstractResourceManager, AbstractResourceManagerCollection

from .._carddavclient import CardDavClient
from .._utils import get_logger
from ._enricher import VCardEnricher

_LOGGER = get_logger(Path(__file__), "AddressBookMerger")

_REV_PATTERN = re.compile(r"(^REV;.*$)", flags=re.MULTILINE)
_CATEGORIES_PATTERN = re.compile(r"(^CATEGORIES:.*$)", flags=re.MULTILINE)


def _get_categories(vcard: vobject.base.Component) -> set[str]:
    categories = vcard.contents.get("categories", [])
    if not categories:
        return set()

    value = categories[0].value

    if isinstance(value, str):
        value = value.split(",")

    return {c.strip() for c in value if c and c.strip()}


def _merge_categories(
    primary: vobject.base.Component, other: vobject.base.Component
) -> vobject.base.Component:
    primary_cats = _get_categories(primary)
    other_cats = _get_categories(other)

    merged = sorted(primary_cats | other_cats, key=lambda x: x.lower())

    if merged:
        if hasattr(primary, "categories") and primary.contents.get("categories"):
            primary.categories.value = merged
        else:
            categories = primary.add("categories")
            categories.value = merged


class AddressBookMerger(AbstractResourceManagerCollection):
    """Merges multiple CardDAV address books into a single target address book.

    Args:
        targets (Mapping[str, CardDavClient]): A mapping of target IDs (just some identifiers) to
            CardDAV clients to which the merged address book will be stored.
        sources (Mapping[str, CardDavClient]): A mapping of source IDs (just some indentifiers) to
            CardDAV clients from which the address books will be merged.
        enricher (VCardEnricher | None): An optional VCardEnricher to enrich vCards before merging.
    """

    def __init__(
        self,
        targets: Mapping[str, CardDavClient],
        sources: Mapping[str, CardDavClient],
        enricher: VCardEnricher | None = None,
    ) -> None:
        self._targets = targets
        self._sources = sources
        self._enricher = enricher

        self.__target_vcards: dict[str, dict[str, vobject.base.Component]] | None = None
        self.__source_vcards: dict[str, dict[str, vobject.base.Component]] | None = None

    @property
    def _resource_managers(self) -> Collection[AbstractResourceManager]:
        return [
            *self._targets.values(),
            *self._sources.values(),
            *([self._enricher] if self._enricher else []),
        ]

    def _target_vcards(self, target_id: str) -> dict[str, vobject.base.Component]:
        """Get the current state of the target address book by its ID."""
        if self.__target_vcards is None:
            raise RuntimeError("Target states not loaded. Call initialize() first.")
        if target_id not in self.__target_vcards:
            raise ValueError(f"Target ID '{target_id}' not found in targets.")
        return self.__target_vcards[target_id]

    def _source_vcards(self, source_id: str) -> dict[str, vobject.base.Component]:
        """Get the current state of a source address book by its ID."""
        if self.__source_vcards is None:
            raise RuntimeError("Source states not loaded. Call initialize() first.")
        if source_id not in self.__source_vcards:
            raise ValueError(f"Source ID '{source_id}' not found in source states.")
        return self.__source_vcards[source_id]

    async def initialize(self) -> None:
        """Initialize the merger by loading the current states of the target and sources."""
        async with asyncio.TaskGroup() as tg:
            target_tasks = {
                target_id: tg.create_task(target.download_address_book_to_memory())
                for target_id, target in self._targets.items()
            }
            source_tasks = {
                source_id: tg.create_task(source.download_address_book_to_memory())
                for source_id, source in self._sources.items()
            }

        self.__target_vcards = {
            target_id: target_task.result() for target_id, target_task in target_tasks.items()
        }
        self.__source_vcards = {
            source_id: source_task.result() for source_id, source_task in source_tasks.items()
        }

    async def _handle_vcard(self, source_id: str, uid: str, vcard: vobject.base.Component) -> None:
        """Handle a single vCard from a source address book."""
        source_vcard_content: str = vcard.serialize()
        if self._enricher:
            source_vcard_content = (await self._enricher.enrich_vcard(vcard)).serialize()

        source_vcard_content_sanitized = _CATEGORIES_PATTERN.sub(
            "", _REV_PATTERN.sub("", source_vcard_content)
        )
        source_categories = _get_categories(vcard)

        for target_id in self._targets:
            if (target_vcard := self._target_vcards(target_id).get(uid)) is not None:
                target_vcard_content = target_vcard.serialize()
                target_vcard_content_sanitized = _CATEGORIES_PATTERN.sub(
                    "", _REV_PATTERN.sub("", target_vcard_content)
                )
                target_categories = _get_categories(target_vcard)

                if (source_vcard_content_sanitized == target_vcard_content_sanitized) and (
                    target_categories >= source_categories
                ):
                    # If the content is the same, skip this vCard.
                    _LOGGER.debug(
                        (
                            "Skipping vCard %s from source %s, content on target %s is identical "
                            "to target."
                        ),
                        uid,
                        source_id,
                        target_id,
                    )
                    continue

                _merge_categories(vcard, target_vcard)
                source_vcard_content = vcard.serialize()
                print(source_vcard_content)

            _LOGGER.info(
                "Uploading vCard %s from source %s to target %s.", uid, source_id, target_id
            )
            await self._targets[target_id].upload_vcard(uid, source_vcard_content)

    async def merge_source(self, source_id: str) -> None:
        """Merge a single source address book into the target address book."""
        _LOGGER.info("Merging source address book '%s' into target.", source_id)
        source_state = self._source_vcards(source_id)

        async with asyncio.TaskGroup() as tg:
            for uid, vcard in source_state.items():
                tg.create_task(self._handle_vcard(source_id, uid, vcard))

    async def merge_all_sources(self) -> None:
        """Merge all source address books into the target address book."""
        _LOGGER.info("Starting merge of all source address books into target.")
        async with asyncio.TaskGroup() as tg:
            for source_id in self._sources:
                tg.create_task(self.merge_source(source_id))

        # After merging, we can clear the states to allow re-initialization if needed.
        self.__target_vcards = None
        self.__source_vcards = None

    async def do_merge(self) -> None:
        """Perform the merge operation."""
        await self.initialize()
        await self.merge_all_sources()
