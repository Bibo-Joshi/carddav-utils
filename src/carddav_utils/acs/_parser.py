import contextlib
import datetime as dtm
import re
import string
from pathlib import Path
from typing import Literal

import vobject.base

from carddav_utils._utils import get_logger

_LOGGER = get_logger(Path(__file__), "ContactParser")

_TRIGGER_PATTERN = re.compile(r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def _trigger_to_timedelta(trigger: str) -> dtm.timedelta:
    """Convert a trigger string to a timedelta object."""
    match = _TRIGGER_PATTERN.match(trigger)
    if not match:
        raise ValueError(f"Invalid trigger format: {trigger}")

    weeks, days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return dtm.timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


class EventBuilder:
    def __init__(self, uuid: str, name: str) -> None:
        self._name = name
        self._uuid = uuid

    def build_event(
        self,
        event_type: str,
        date: dtm.date,
        summary: string.Template,
        description: string.Template,
        reminders: list[str] | None = None,
    ) -> tuple[str, vobject.base.Component]:
        """Builds an event dictionary with the provided keyword arguments."""
        original_year = date.year
        current_year = dtm.datetime.now(tz=dtm.UTC).year
        count = current_year - original_year

        cal = vobject.iCalendar()
        cal.add("prodid").value = "-//carddav-utils//DE"
        cal.add("version").value = "2.0"

        event = cal.add("vevent")
        uid = f"{self._uuid}-{event_type}"
        event.add("uid").value = uid
        event.add("summary").value = summary.safe_substitute(
            name=self._name, originalYear=original_year, currentYear=current_year, count=count
        )
        event.add("description").value = description.safe_substitute(
            name=self._name,
            date=date.strftime("%d.%m.%Y"),
            originalYear=original_year,
            currentYear=current_year,
            count=count,
        )
        event.add("rrule").value = "FREQ=YEARLY"
        event.add("dtstart").value = date
        event.add("x-carddav-utils-generated").value = "true"

        for trigger in reminders or []:
            alarm = event.add("valarm")
            alarm.add("action").value = "DISPLAY"
            alarm.add("trigger").value = -_trigger_to_timedelta(trigger)
            alarm.add("description").value = f"Reminder for {self._name}'s {event_type}"

        return uid, cal


class ContactParser:
    """Parser for extracting anniversary calendar information from a CardDAV contact.

    Args:
        vcard (vobject.base.Component): The vCard component to parse.
        category_identifier (str): The following categories will be extracted as reminders:
            ``X-(B|D|A)R-<category_identifier>-P<trigger>``
            Where ``<category_identifier>`` is the provided category identifier and ``<trigger>``
            is a duration in the format ``P[nW][nD][T[nH][nM][nS]]``. ``B```, ``D``, and ``A``
            stand for birthday, death date, and anniversary, respectively.

    """

    def __init__(self, vcard: vobject.base.Component, category_identifier: str) -> None:
        self._vcard = vcard
        self._category_identifier = category_identifier

    def __get_date(self, field_name: str) -> dtm.date | None:
        """Extracts a date from the vCard for the given field name, if present."""
        field = self._vcard.contents.get(field_name)
        if not field:
            return None
        field_value = field[0].value
        if isinstance(field_value, dtm.date):
            return field_value
        if isinstance(field_value, str):
            formats = ["%Y-%m-%d", "%Y%m%d"]
            for fmt in formats:
                with contextlib.suppress(ValueError):
                    return dtm.datetime.strptime(field_value, fmt).replace(tzinfo=dtm.UTC).date()

            _LOGGER.warning("Invalid %s format in vCard: %s", field_name, field_value)
            return None
        _LOGGER.warning("Unexpected %s type in vCard: %s", field_name, type(field_value))
        return None

    def _get_birthday(self) -> dtm.date | None:
        """Extracts the birthday from the vCard, if present."""
        return self.__get_date("bday")

    def _get_death_date(self) -> dtm.date | None:
        """Extracts the death date from the vCard, if present."""
        return self.__get_date("deathdate")

    def _get_anniversary(self) -> dtm.date | None:
        """Extracts the anniversary from the vCard, if present."""
        return self.__get_date("anniversary")

    def _extract_reminders(self, anniversary_type: Literal["B", "D", "A"]) -> list[str]:
        """Extracts reminders from the vCard categories based on the specified prefix."""
        pattern = re.compile(rf"^X-{anniversary_type}R-{self._category_identifier}-(P.*)$")
        categories = self._vcard.contents.get("categories", [])
        reminders: list[str] = []
        for category in categories:
            reminders.extend(
                match.group(1) for cat in category.value if (match := pattern.match(cat))
            )
        return reminders

    def _get_uuid(self) -> str:
        """Extracts the UUID from the vCard, if present."""
        uid_field = self._vcard.contents.get("uid")
        if not uid_field:
            raise ValueError("UUID not found in vCard.")
        return uid_field[0].value

    def _get_full_name(self) -> str:
        """Extracts the full name from the vCard, if present."""
        # format if nickname is present: Nickname (First Name) Lastname
        # format if nickname is not present: First Name Lastname
        full_name = self._vcard.contents.get("fn")[0].value

        if detailed_name_field := self._vcard.contents.get("n"):
            first_name: str | None = detailed_name_field[0].value.given
            last_name: str | None = detailed_name_field[0].value.family
        else:
            first_name = None
            last_name = None

        if (nickname_field := self._vcard.contents.get("nickname")) and (
            nickname := nickname_field[0].value
        ):
            if first_name and last_name:
                return f"{nickname} ({first_name}) {last_name}"
            return f"{nickname} ({full_name})"

        if first_name and last_name:
            return f"{first_name} {last_name}"
        return full_name

    def events(self) -> dict[str, vobject.base.Component]:
        """Iterates over the events extracted from the vCard."""
        uuid = self._get_uuid()
        name = self._get_full_name()
        event_builder = EventBuilder(uuid=uuid, name=name)
        events = {}

        birthday = self._get_birthday()
        birthday_reminders = self._extract_reminders("B")
        if birthday and birthday_reminders:
            uid, evnet = event_builder.build_event(
                date=birthday,
                summary=string.Template("🎂 ${name} (${originalYear})"),
                description=string.Template(
                    """Geburtstag von ${name}

Geboren am: ${date}
Wird ${currentYear} frische ${count} Jahre alt."""
                ),
                reminders=birthday_reminders,
                event_type="birthday",
            )
            events[uid] = evnet

        death_date = self._get_death_date()
        if death_date:
            uid, event = event_builder.build_event(
                date=death_date,
                summary=string.Template("🪦 ${name} (${originalYear})"),
                description=string.Template(
                    """Todestag von ${name}

Gestorben am: ${date}
Jährt sich ${currentYear} zum ${count}. Mal."""
                ),
                event_type="death",
                reminders=self._extract_reminders("D"),
            )
            events[uid] = event

        anniversary = self._get_anniversary()
        if anniversary:
            uid, event = event_builder.build_event(
                date=anniversary,
                summary=string.Template("💒 ${name} (${originalYear})"),
                description=string.Template(
                    """Hochzeitstag von ${name}

Geheiratet am: ${date}
Jährt sich ${currentYear} zum ${count}. Mal."""
                ),
                event_type="anniversary",
                reminders=self._extract_reminders("A"),
            )
            events[uid] = event

        return events
