from abc import abstractmethod
from collections.abc import AsyncGenerator

from aiorem import AbstractResourceManager
from pydantic import BaseModel

from ._utils import ParsedPhoneNumber


class ProfilePictureInfo(BaseModel):
    """Information about a profile picture associated with a phone number."""

    phone_number: ParsedPhoneNumber
    name: str
    photo: bytes
    mime_type: str


class BaseCrawler(AbstractResourceManager):
    """Base class for crawlers that extract phone numbers corresponding profile pictures."""

    @abstractmethod
    async def crawl(self) -> AsyncGenerator[ProfilePictureInfo]:
        """Crawl the data source and yield tuples of phone number and a tuple of
        (name, photo bytes, mime type)."""

    # async def export_to_json(self, file_path: Path | str) -> None:
    #     path = Path(file_path)
    #     path.parent.mkdir(parents=True, exist_ok=True)
    #     data = {
    #         phone_number: {
    #             "name": name,
    #             "photo": photo_bytes.decode("latin1"),
    #             "mime_type": mime_type,
    #         }
    #         async for phone_number, (name, photo_bytes, mime_type) in self.crawl()
    #     }
    #     path.write_text(json.dumps(data, indent=2))
    #
    # async def export_to_directory(self, directory_path: Path | str) -> None:
    #     directory = Path(directory_path)
    #     directory.mkdir(parents=True, exist_ok=True)
    #     async for phone_number, (_, photo_bytes, mime_type) in self.crawl():
    #         ext = mime_type.split("/")[-1]
    #         file_path = directory / f"{phone_number}.{ext}"
    #         file_path.write_bytes(photo_bytes)
