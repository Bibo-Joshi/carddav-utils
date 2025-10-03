import asyncio
import datetime as dtm
from collections.abc import AsyncGenerator, Collection, Mapping, Sequence
from enum import StrEnum, auto
from pathlib import Path
from typing import cast

import aiostream
import vobject
from aiorem import AbstractResourceManager, AbstractResourceManagerCollection

from .._carddavclient import CardDavClient
from .._profilepictureinfo import ProfilePictureInfo
from .._utils import ParsedPhoneNumber, get_logger, phone_number_to_string
from ._base import BaseCrawler

_LOGGER = get_logger(Path(__file__), "ProfilePictureInjector")


class InjectionMethod(StrEnum):
    ALWAYS_OVERRIDE = auto()
    """Always override existing profile pictures in contacts."""
    COMPARE_CONTENT = auto()
    """Only override if the new profile picture is different from the existing one."""


class _InjectionResult(StrEnum):
    UNCHANGED = auto()
    UPDATED = auto()
    ADDED = auto()


class ProfilePictureInjector(AbstractResourceManagerCollection):
    """Injects profile pictures into contacts based on phone numbers.

    Args:
        crawlers (Sequence[BaseCrawler]): A collection of crawlers that extract phone numbers
            and corresponding profile pictures.

            Important:
                Order matters! Crawlers earlier in the sequence have higher priority.
                If multiple crawlers provide a profile picture for the same phone number, the one
                from the crawler that appears first in the sequence will be used.
        targets (Mapping[str, CardDavClient]): A mapping of target IDs (just some identifiers) to
            CardDAV clients into which the profile pictures will be injected.
    """

    def __init__(
        self, crawlers: Sequence[BaseCrawler], targets: Mapping[str, CardDavClient]
    ) -> None:
        self._crawlers = crawlers
        self._targets = targets

        # Let's limit the number of concurrent requests to avoid overwhelming the servers in case
        # some of the targets are on the same server.
        self.__semaphore = asyncio.BoundedSemaphore(50)
        self.__target_vcards: dict[str, dict[str, vobject.base.Component]] | None = None

    @property
    def _resource_managers(self) -> Collection[AbstractResourceManager]:
        return [*self._crawlers, *self._targets.values()]

    def _target_vcards(self, target_id: str) -> dict[str, vobject.base.Component]:
        """Get the current vCards of the target address book by its ID."""
        if self.__target_vcards is None:
            raise RuntimeError("Target vCards not loaded. Call download_target_contacts() first.")
        if target_id not in self.__target_vcards:
            raise ValueError(f"Target ID '{target_id}' not found in targets.")
        return self.__target_vcards[target_id]

    async def download_target_contacts(self) -> None:
        """Download all contacts from the target address books."""
        async with asyncio.TaskGroup() as tg:
            target_tasks = {
                target_id: tg.create_task(target.download_address_book_to_memory())
                for target_id, target in self._targets.items()
            }

        self.__target_vcards = {
            target_id: task.result() for target_id, task in target_tasks.items()
        }

    async def _inject_into_vcard(
        self,
        target_id: str,
        uid: str,
        vcard: vobject.base.Component,
        profile_picture: ProfilePictureInfo,
        injection_method: InjectionMethod,
    ) -> _InjectionResult:
        """Inject a profile picture into a single vCard and upload it if necessary."""
        photo = vcard.contents.get("photo")
        name = vcard.contents.get("fn", [None])[0]
        log_id = name.value if name else uid
        should_upload = False
        result: _InjectionResult = _InjectionResult.UNCHANGED

        if photo:
            existing_photo_data = photo[0].value
            if injection_method == InjectionMethod.ALWAYS_OVERRIDE or (
                injection_method == InjectionMethod.COMPARE_CONTENT
                and existing_photo_data != profile_picture.photo
            ):
                root = Path(__file__).parent / "out"
                (root / f"{log_id}-existing.jpg").write_bytes(existing_photo_data)
                (root / f"{log_id}-new.jpg").write_bytes(profile_picture.photo)
                (root / f"{log_id}-diff.txt").write_text(
                    f"Existing photo size: {len(existing_photo_data)} bytes\n"
                    f"New photo size: {len(profile_picture.photo)} bytes\n"
                    f"Same content: {existing_photo_data == profile_picture.photo}\n"
                )
                should_upload = True
                result = _InjectionResult.UPDATED
        else:
            should_upload = True
            result = _InjectionResult.ADDED

        if should_upload:
            if "photo" in vcard.contents:
                _LOGGER.debug(
                    "Overriding existing profile picture for contact '%s' in target '%s'.",
                    log_id,
                    target_id,
                )
                del vcard.contents["photo"]

            _LOGGER.info(
                "Injecting profile picture for contact '%s' in target '%s'.", log_id, target_id
            )
            photo = vcard.add("PHOTO")
            photo.value = profile_picture.photo
            photo.encoding_param = "B"
            photo.type_param = profile_picture.mime_type.split("/")[-1].upper()

            if "rev" in vcard.contents:
                del vcard.contents["rev"]
            rev = vcard.add("REV")
            rev.value = dtm.datetime.now(tz=dtm.UTC).strftime("%Y%m%dT%H%M%SZ")

            async with self.__semaphore:
                await self._targets[target_id].upload_vcard(uid, vcard.serialize())
        else:
            _LOGGER.debug(
                "Skipping injection for contact '%s' in target '%s'; no changes needed.",
                log_id,
                target_id,
            )

        return result

    async def inject_profile_picture_into_target(
        self,
        target_id: str,
        profile_picture: ProfilePictureInfo,
        injection_method: InjectionMethod,
    ) -> Sequence[_InjectionResult]:
        """Inject a single profile picture into the target address books."""
        tasks = []
        async with asyncio.TaskGroup() as tg:
            for uid, vcard in self._target_vcards(target_id).items():
                phone_numbers = [
                    phone_number_to_string(tel.value) for tel in vcard.contents.get("tel", [])
                ]
                if profile_picture.phone_number in phone_numbers:
                    tasks.append(
                        tg.create_task(
                            self._inject_into_vcard(
                                target_id, uid, vcard, profile_picture, injection_method
                            )
                        )
                    )
        return await asyncio.gather(*tasks)

    async def inject_profile_picture_into_all_targets(
        self, profile_picture: ProfilePictureInfo, injection_method: InjectionMethod
    ) -> dict[str, Sequence[_InjectionResult]]:
        """Inject a single profile picture into the target address books."""
        async with asyncio.TaskGroup() as tg:
            tasks = {
                target_id: tg.create_task(
                    self.inject_profile_picture_into_target(
                        target_id, profile_picture, injection_method
                    )
                )
                for target_id in self._targets
            }

        return {target_id: task.result() for target_id, task in tasks.items()}

    async def inject_from_all_crawlers(self, injection_method: InjectionMethod) -> None:
        """Inject profile pictures from all crawlers into the target address books."""
        _LOGGER.info("Starting crawling and injection of profile pictures.")
        parsed_phone_numbers: set[ParsedPhoneNumber] = set()
        tasks = set()
        async with (
            asyncio.TaskGroup() as tg,
            aiostream.streamcontext(
                aiostream.stream.merge(
                    *(
                        cast("AsyncGenerator[ProfilePictureInfo]", crawler.crawl())
                        for crawler in self._crawlers
                    )
                )
            ) as merged_stream,
        ):
            async for profile_picture in merged_stream:
                if profile_picture.phone_number in parsed_phone_numbers:
                    _LOGGER.debug(
                        "Skipping profile picture for phone number '%s' as it was "
                        "already processed.",
                        profile_picture.phone_number,
                    )
                    continue
                tasks.add(
                    tg.create_task(
                        self.inject_profile_picture_into_all_targets(
                            profile_picture, injection_method
                        )
                    )
                )
                parsed_phone_numbers.add(profile_picture.phone_number)

        results: dict[str, list[_InjectionResult]] = {target_id: [] for target_id in self._targets}
        for task in tasks:
            injection_results = task.result()
            for target_id, result in injection_results.items():
                results[target_id].extend(result)

        for target_id, result in results.items():
            added = sum(1 for r in result if r == _InjectionResult.ADDED)
            updated = sum(1 for r in result if r == _InjectionResult.UPDATED)
            unchanged = sum(1 for r in result if r == _InjectionResult.UNCHANGED)
            total = len(result)
            _LOGGER.info(
                (
                    "Injection summary for target '%s': %d contacts processed, "
                    "%d added, %d updated, %d unchanged."
                ),
                target_id,
                total,
                added,
                updated,
                unchanged,
            )

        # After merging, we can clear the states to allow re-initialization if needed.
        self.__target_vcards = None

    async def do_injection(self, injection_method: InjectionMethod) -> None:
        """Perform the injection operation."""
        await self.download_target_contacts()
        await self.inject_from_all_crawlers(injection_method)
