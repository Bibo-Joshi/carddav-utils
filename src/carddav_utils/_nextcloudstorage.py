import asyncio
import hashlib
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self

import tomlkit
from aiorem import AbstractResourceManager
from nextcloud_async.exceptions import NextCloudNotFound
from pydantic import BaseModel

from ._nextcloudclient import NextCloudClient, NextCloudClientConfig
from ._profilepictureinfo import ProfilePictureInfo
from ._utils import ParsedPhoneNumber, get_logger, phone_number_to_string

_LOGGER = get_logger(Path(__file__), "ProfilePictureExporter")


class StoredProfilePictureInfo(BaseModel):
    phone_number: ParsedPhoneNumber
    mime_type: str
    file_path: Path
    hash: str

    @classmethod
    def from_profile_picture_info(cls, ppi: ProfilePictureInfo, storage_path: Path) -> Self:
        return cls(
            phone_number=ppi.phone_number,
            mime_type=ppi.mime_type,
            file_path=(storage_path / ppi.phone_number).with_suffix(
                f".{ppi.mime_type.split('/')[-1]}"
            ),
            hash=hashlib.sha256(ppi.photo).hexdigest(),
        )


class StoredProfilePictureInfoCollection(BaseModel):
    profile_pictures: list[StoredProfilePictureInfo]

    def update(self, profile_picture_info: ProfilePictureInfo) -> StoredProfilePictureInfo | None:
        """Update or add a profile picture.
        Updates are based on phone number. If a profile picture for the given phone number
        already exists, it will be replaced only if the hash of the new picture differs from
        the existing one.

        Args:
            profile_picture_info (ProfilePictureInfo): The profile picture information to add
                or update.

        Returns:
            StoredProfilePictureInfo | None: The updated or added StoredProfilePictureInfo,
                or None if no update was necessary.
        """
        new_entry = StoredProfilePictureInfo.from_profile_picture_info(
            profile_picture_info, Path("./photos")
        )

        for existing in self.profile_pictures:
            if existing.phone_number == profile_picture_info.phone_number:
                if existing.hash == new_entry.hash:
                    _LOGGER.debug(
                        "Profile picture for %s is up-to-date. No update needed.",
                        phone_number_to_string(profile_picture_info.phone_number),
                    )
                    return None
                self.profile_pictures.remove(existing)

        self.profile_pictures.append(new_entry)
        return new_entry

    def get_by_phone_number(self, phone_number: ParsedPhoneNumber) -> StoredProfilePictureInfo:
        """Get the StoredProfilePictureInfo for the given phone number.

        Args:
            phone_number (ParsedPhoneNumber): The phone number to look for.

        Raises:
            KeyError: If no profile picture is found for the given phone number.
        """
        try:
            return next(pic for pic in self.profile_pictures if pic.phone_number == phone_number)
        except StopIteration as exc:
            raise KeyError(
                f"No profile picture found for phone number {phone_number_to_string(phone_number)}"
            ) from exc

    def to_toml(self) -> str:
        data = self.model_dump()
        for pic in data["profile_pictures"]:
            pic["file_path"] = pic["file_path"].as_posix()
        return tomlkit.dumps(data)

    @classmethod
    def from_toml(cls, toml_str: str) -> Self:
        data = tomllib.loads(toml_str)
        pics = [
            StoredProfilePictureInfo(
                file_path=Path(item["file_path"]),
                phone_number=phone_number_to_string(item["phone_number"]),
                mime_type=item["mime_type"],
                hash=item["hash"],
            )
            for item in data["profile_pictures"]
        ]
        return cls(profile_pictures=pics)


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

    async def get_current_status(self) -> StoredProfilePictureInfoCollection:
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

    async def initialize(self) -> None:
        """Initialize the exporter by loading the current state."""
        self.__current_state = await self.get_current_status()

    async def download_picture(
        self, reference: StoredProfilePictureInfo | ParsedPhoneNumber
    ) -> ProfilePictureInfo:
        sppi = (
            reference
            if isinstance(reference, StoredProfilePictureInfo)
            else self._current_state.get_by_phone_number(reference)
        )
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
            return

        await self._nc_client.upload_file(
            profile_picture_info.photo, self._target_path / new_entry.file_path
        )
        _LOGGER.debug("Uploaded/Updated profile picture for %s", profile_picture_info.phone_number)

        if upload_index:
            await self._upload_index()

    async def update_from_iterator(self, generator: AsyncIterator[ProfilePictureInfo]) -> None:
        """Update profile pictures from the given generator."""
        async with asyncio.TaskGroup() as tg:
            async for ppi in generator:
                tg.create_task(self._update_profile_picture(ppi, upload_index=False))

        # Update index only once after all uploads are done
        await self._upload_index()
