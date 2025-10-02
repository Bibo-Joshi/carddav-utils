import asyncio
import mimetypes
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Self

from pydantic import ConfigDict

from .._profilepictureinfo import ProfilePictureInfo
from .._utils import get_logger, phone_number_to_string
from . import BaseCrawler, BaseCrawlerConfig

_LOGGER = get_logger(Path(__file__), "DirectoryCrawler")


class DirectoryCrawlerConfig(BaseCrawlerConfig):
    """Configuration for a DirectoryCrawler."""

    model_config = ConfigDict(extra="forbid")
    directory: Path


class DirectoryCrawler(BaseCrawler[DirectoryCrawlerConfig]):
    """Crawles pictures from a local directory."""

    async def acquire_resources(self) -> None:
        pass

    async def release_resources(self) -> None:
        pass

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        if not self._directory.is_dir():
            raise ValueError(f"{self._directory} is not a valid self._directory.")

    async def crawl(self) -> AsyncGenerator[ProfilePictureInfo]:  # type: ignore[override]
        """Crawl the data source and yield tuples of phone number and a tuple of
        (name, photo bytes, mime type)."""

        for file_path in self._directory.iterdir():
            if not file_path.is_file():
                continue
            try:
                phone_number = phone_number_to_string(file_path.stem)
            except ValueError:
                _LOGGER.warning(
                    "Skipping file %s: filename is not a valid phone number.", file_path
                )
                continue
            mime_type = mimetypes.guess_type(file_path.name)[0]
            if not mime_type or not mime_type.startswith("image/"):
                _LOGGER.warning(
                    "Skipping file %s: unsupported file extension %s.", file_path, file_path.suffix
                )
                continue
            photo_data = file_path.read_bytes()
            await asyncio.sleep(0)  # Yield control to the event loop to avoid blocking
            yield ProfilePictureInfo(
                phone_number=phone_number, mime_type=mime_type, photo=photo_data
            )

    @classmethod
    def from_config(cls, config: DirectoryCrawlerConfig) -> Self:
        """Create a crawler instance from the given configuration."""
        return cls(directory=config.directory)
