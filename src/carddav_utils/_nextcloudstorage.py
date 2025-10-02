import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self

from aiorem import AbstractResourceManager
from nextcloud_async.exceptions import NextCloudNotFound

from ._nextcloudclient import NextCloudClient, NextCloudClientConfig
from ._profilepictureinfo import ProfilePictureInfo
from ._storageobjects import (
    AdditionalVCardInfoCollection,
    StoredProfilePictureInfo,
    StoredProfilePictureInfoCollection,
)
from ._utils import ParsedPhoneNumber, get_logger, phone_number_to_string

_LOGGER = get_logger(Path(__file__), "ProfilePictureExporter")


class NextCloudStorageConfig(NextCloudClientConfig):
    target_path: Path

    def to_nextcloud_client_config(self) -> NextCloudClientConfig:
        data = self.model_dump()
        data.pop("target_path")
        return NextCloudClientConfig.model_validate(data)


class NextCloudStorage(AbstractResourceManager):
    """Interface for storing and loading profile pictures in a NextCloud instance.

    Args:
        target_path (Path): The target path in the NextCloud instance where profile pictures
            should be uploaded. This path must already exist as well as a subdirectory "photos".
        nextcloud_client (NextCloudClient): An instance of NextCloudClient to interact with
            the NextCloud server.
    """

    def __init__(self, target_path: Path | str, nextcloud_client: NextCloudClient) -> None:
        self._target_path = Path(target_path)
        self._nc_client = nextcloud_client

        self.__current_state: StoredProfilePictureInfoCollection | None = None
        self.__index_lock = asyncio.Lock()

    async def acquire_resources(self) -> None:
        await self._nc_client.acquire_resources()

    async def release_resources(self) -> None:
        await self._nc_client.release_resources()

    @classmethod
    def from_config(cls, config: NextCloudStorageConfig) -> Self:
        nc_client = NextCloudClient.from_config(config.to_nextcloud_client_config())
        return cls(target_path=config.target_path, nextcloud_client=nc_client)

    @property
    def _current_state(self) -> StoredProfilePictureInfoCollection:
        if self.__current_state is None:
            raise RuntimeError("Current state not loaded. Call initialize() first.")
        return self.__current_state

    async def get_current_profile_pictures(self) -> StoredProfilePictureInfoCollection:
        """Get the current status of profile pictures in the target NextCloud directory.

        Returns:
            StoredProfilePictureInfoCollection: A collection of StoredProfilePictureInfo
                representing the current profile pictures in the target directory.
        """
        toml_path = self._target_path / "profile_pictures.toml"
        try:
            toml_data = await self._nc_client.download_file_to_memory(toml_path)
        except NextCloudNotFound:
            _LOGGER.info(
                "No existing profile_pictures.toml found at %s. Starting fresh.", toml_path
            )
            return StoredProfilePictureInfoCollection(profile_pictures=[])

        try:
            return StoredProfilePictureInfoCollection.from_toml(toml_data.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to parse existing profile_pictures.toml: {e}") from e

    async def get_current_additional_vcard_info(self) -> AdditionalVCardInfoCollection:
        """Get the current status of additional vCard info in the target NextCloud directory.

        Returns:
            AdditionalVCardInfoCollection: A collection of AdditionalVCardInfo
                representing the current additional vCard info in the target directory.
        """
        toml_path = self._target_path / "additional_vcard_info.toml"
        try:
            toml_data = await self._nc_client.download_file_to_memory(toml_path)
        except NextCloudNotFound:
            _LOGGER.info(
                "No existing additional_vcard_info.toml found at %s. Starting fresh.", toml_path
            )
            return AdditionalVCardInfoCollection(entries=[])

        try:
            return AdditionalVCardInfoCollection.from_toml(toml_data.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to parse existing additional_vcard_info.toml: {e}") from e

    async def initialize(self) -> None:
        """Initialize the exporter by loading the current state."""
        self.__current_state = await self.get_current_profile_pictures()

    async def download_picture(
        self, reference: StoredProfilePictureInfo | ParsedPhoneNumber
    ) -> ProfilePictureInfo:
        sppi = (
            reference
            if isinstance(reference, StoredProfilePictureInfo)
            else self._current_state.get_by_phone_number(reference)
        )
        if sppi is None:
            raise ValueError(f"No profile picture found for phone number {reference}")
        photo_data = await self._nc_client.download_file_to_memory(
            self._target_path / sppi.file_path
        )
        return ProfilePictureInfo(
            phone_number=sppi.phone_number, mime_type=sppi.mime_type, photo=photo_data
        )

    async def update_profile_picture(self, profile_picture_info: ProfilePictureInfo) -> None:
        """Update or add a profile picture in the NextCloud storage.

        Args:
            profile_picture_info (ProfilePictureInfo): The profile picture information to add
                or update.
        """
        await self._update_profile_picture(profile_picture_info, upload_index=True)

    async def _upload_index(self) -> None:
        async with self.__index_lock:
            toml_data = self._current_state.to_toml()
            await self._nc_client.upload_file(
                toml_data.encode("utf-8"), self._target_path / "profile_pictures.toml"
            )
            _LOGGER.info("Uploaded updated profile_pictures.toml to %s", self._target_path)

    async def _update_profile_picture(
        self, profile_picture_info: ProfilePictureInfo, upload_index: bool
    ) -> None:
        # No need to delete old picture, as the file name is derived from the phone number
        # and will be overwritten.
        new_entry = self._current_state.update(profile_picture_info)
        if new_entry is None:
            _LOGGER.debug(
                "Profile picture for %s is up-to-date. No update needed.",
                phone_number_to_string(profile_picture_info.phone_number),
            )
            return

        await self._nc_client.upload_file(
            profile_picture_info.photo, self._target_path / new_entry.file_path
        )
        _LOGGER.debug("Uploaded/Updated profile picture for %s", profile_picture_info.phone_number)

        if upload_index:
            await self._upload_index()

    async def update_from_iterator(self, generator: AsyncIterator[ProfilePictureInfo]) -> None:
        """Update profile pictures from the given generator."""
        processed_numbers: set[ParsedPhoneNumber] = set()
        async with asyncio.TaskGroup() as tg:
            async for ppi in generator:
                if ppi.phone_number in processed_numbers:
                    _LOGGER.debug(
                        "Skipping duplicate profile picture for %s",
                        phone_number_to_string(ppi.phone_number),
                    )
                    continue
                processed_numbers.add(ppi.phone_number)
                tg.create_task(self._update_profile_picture(ppi, upload_index=False))

        # Update index only once after all uploads are done
        await self._upload_index()
