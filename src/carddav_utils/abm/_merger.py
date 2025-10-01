import asyncio
from collections.abc import Collection, Mapping
from enum import StrEnum, auto
from pathlib import Path

from aiorem import AbstractResourceManager, AbstractResourceManagerCollection

from .._carddavclient import CardDavClient
from .._utils import get_logger
from .._vcardinfo import VCardInfo

_LOGGER = get_logger(Path(__file__), "AddressBookMerger")


class ComparisonMethod(StrEnum):
    EDIT_DATE = auto()
    """Compare vCards based on their last modified date. Saves a bit of network traffic by not
    downloading the target vCard. Might be less reliable in some edge cases, e.g. when a
    contact was changed on the target but the source contact remains unchanged.
    """
    CONTENT = auto()
    """Compare vCards based on their content. Downloads the target vCard to compare it with the
    source vCard. More reliable but requires more network traffic."""


class AddressBookMerger(AbstractResourceManagerCollection):
    """Merges multiple CardDAV address books into a single target address book.

    Args:
        targets (Mapping[str, CardDavClient]): A mapping of target IDs (just some identifiers) to
            CardDAV clients to which the merged address book will be stored.
        sources (Mapping[str, CardDavClient]): A mapping of source IDs (just some indentifiers) to
            CardDAV clients from which the address books will be merged.

    """

    def __init__(
        self, targets: Mapping[str, CardDavClient], sources: Mapping[str, CardDavClient]
    ) -> None:
        self._targets = targets
        self._sources = sources

        self.__target_states: dict[str, dict[str, VCardInfo]] | None = None
        self.__source_states: dict[str, dict[str, VCardInfo]] | None = None

    @property
    def _resource_managers(self) -> Collection[AbstractResourceManager]:
        return [*self._targets.values(), *self._sources.values()]

    def _target_state(self, target_id: str) -> dict[str, VCardInfo]:
        """Get the current state of the target address book by its ID."""
        if self.__target_states is None:
            raise RuntimeError("Target states not loaded. Call initialize() first.")
        if target_id not in self.__target_states:
            raise ValueError(f"Target ID '{target_id}' not found in targets.")
        return self.__target_states[target_id]

    def _source_state(self, source_id: str) -> dict[str, VCardInfo]:
        """Get the current state of a source address book by its ID."""
        if self.__source_states is None:
            raise RuntimeError("Source states not loaded. Call initialize() first.")
        if source_id not in self.__source_states:
            raise ValueError(f"Source ID '{source_id}' not found in source states.")
        return self.__source_states[source_id]

    async def initialize(self) -> None:
        """Initialize the merger by loading the current states of the target and sources."""
        async with asyncio.TaskGroup() as tg:
            target_tasks = {
                target_id: tg.create_task(target.get_vcard_infos())
                for target_id, target in self._targets.items()
            }
            source_tasks = {
                source_id: tg.create_task(source.get_vcard_infos())
                for source_id, source in self._sources.items()
            }

        self.__target_states = {
            target_id: target_task.result() for target_id, target_task in target_tasks.items()
        }
        self.__source_states = {
            source_id: source_task.result() for source_id, source_task in source_tasks.items()
        }

    async def _handle_vcard(
        self, source_id: str, uid: str, vcard_info: VCardInfo, comparison_method: ComparisonMethod
    ) -> None:
        """Handle a single vCard from a source address book."""
        vcard_content: bytes | None = None

        for target_id in self._targets:
            if (target_vcard_info := self._target_state(target_id).get(uid)) is not None:
                if comparison_method is ComparisonMethod.EDIT_DATE and (
                    target_vcard_info.last_modified >= vcard_info.last_modified
                ):
                    # If the target already has a newer version, skip this vCard.
                    _LOGGER.debug(
                        (
                            "Skipping vCard %s from source %s, edit date on target %s "
                            "is fresh enough."
                        ),
                        uid,
                        source_id,
                        target_id,
                    )
                    continue

                async with asyncio.TaskGroup() as tg:
                    source_task = tg.create_task(
                        self._sources[source_id].download_vcard_to_memory(uid)
                    )
                    target_task = tg.create_task(
                        self._targets[target_id].download_vcard_to_memory(uid)
                    )

                source_vcard_content = await source_task
                target_vcard_content = await target_task
                if source_vcard_content == target_vcard_content:
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

            _LOGGER.info(
                "Uploading vCard %s from source %s to target %s.", uid, source_id, target_id
            )
            client = self._sources[source_id]

            if vcard_content is None:
                vcard_content = await client.download_vcard_to_memory(uid)
            await self._targets[target_id].upload_vcard(uid, vcard_content)

    async def merge_source(self, source_id: str, comparison_method: ComparisonMethod) -> None:
        """Merge a single source address book into the target address book."""
        _LOGGER.info("Merging source address book '%s' into target.", source_id)
        source_state = self._source_state(source_id)

        async with asyncio.TaskGroup() as tg:
            for uid, vcard_info in source_state.items():
                tg.create_task(self._handle_vcard(source_id, uid, vcard_info, comparison_method))

    async def merge_all_sources(self, comparison_method: ComparisonMethod) -> None:
        """Merge all source address books into the target address book."""
        _LOGGER.info("Starting merge of all source address books into target.")
        async with asyncio.TaskGroup() as tg:
            for source_id in self._sources:
                tg.create_task(self.merge_source(source_id, comparison_method))

        # After merging, we can clear the states to allow re-initialization if needed.
        self.__target_states = None
        self.__source_states = None

    async def do_merge(self, comparison_method: ComparisonMethod) -> None:
        """Perform the merge operation."""
        await self.initialize()
        await self.merge_all_sources(comparison_method)
