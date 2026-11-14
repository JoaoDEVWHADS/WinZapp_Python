"""File > WhatsApp settings > Profile: what the page sends, decided without wx.

The calls to the local server live in main_window/whatsapp_profile.py and the
page itself in ui/dialogs/whatsapp_profile_panel.py. Everything that is a
decision (which fields go, which photo is acceptable, which failures to list)
is here, so it is tested without opening a window.

A field left empty means "keep it as it is": the page never clears the name,
the About text or the photo, only replaces them. The page opens showing what is
set (``CurrentProfile``), and a text field still equal to it counts as empty.
"""

import os
from dataclasses import dataclass, replace

#: Photo types WPPConnect Server's ``set-profile-pic`` takes, by extension, with
#: the content type the upload declares. Anything else is refused before it is
#: sent, so a wrong pick is explained instead of failing on the server.
PHOTO_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

#: The order the page applies and reports its three fields in.
FIELDS = ("name", "status", "photo")


@dataclass(frozen=True)
class ProfileChanges:
    """What the Profile page will send. An empty value means "keep as is"."""

    name: str = ""
    status: str = ""
    photo: str = ""

    @property
    def empty(self) -> bool:
        return not (self.name or self.status or self.photo)

    def fields(self) -> list:
        """(field, value) for what is actually sent, in the page's order."""
        return [(field, getattr(self, field)) for field in FIELDS if getattr(self, field)]


@dataclass(frozen=True)
class CurrentProfile:
    """What the account has on WhatsApp right now, as the page shows it.

    ``photo`` is True/False when the server could tell, None when it could not
    (a failed lookup is not proof that there is no photo).
    """

    name: str = ""
    status: str = ""
    photo: "bool | None" = None


def parse_current_profile(answer) -> "CurrentProfile | None":
    """The server's ``{name, status, photo}`` answer as a CurrentProfile, or
    None when it is not an answer at all or holds nothing readable.

    Each part is optional: one the server could not read arrives as null and
    stays empty here, so the page still shows the parts that did come through.
    """
    if not isinstance(answer, dict):
        return None
    name, status, photo = answer.get("name"), answer.get("status"), answer.get("photo")
    name = name.strip() if isinstance(name, str) else None
    status = status.strip() if isinstance(status, str) else None
    photo = photo if isinstance(photo, bool) else None
    if name is None and status is None and photo is None:
        return None
    return CurrentProfile(name=name or "", status=status or "", photo=photo)


def profile_changes(name, status, photo, current: "CurrentProfile | None" = None) -> ProfileChanges:
    """The changes to send from the raw values of the page's controls.

    Text is stripped, so a field holding only spaces counts as left empty
    instead of asking WhatsApp for a blank name. When the page opened already
    showing what is set (*current*), a text field still equal to it is not a
    change and is not sent again.
    """
    name = (name or "").strip()
    status = (status or "").strip()
    if current is not None:
        if name == current.name:
            name = ""
        if status == current.status:
            status = ""
    return ProfileChanges(name=name, status=status, photo=photo or "")


def current_after_save(current: "CurrentProfile | None", changes: ProfileChanges,
                       errors: dict) -> CurrentProfile:
    """What the account holds once *changes* went through, except for the
    fields listed in *errors*: the page's new baseline, so the next Save only
    sends what was edited after this one."""
    result = current or CurrentProfile()
    if changes.name and "name" not in errors:
        result = replace(result, name=changes.name)
    if changes.status and "status" not in errors:
        result = replace(result, status=changes.status)
    if changes.photo and "photo" not in errors:
        result = replace(result, photo=True)
    return result


def photo_content_type(path: str) -> str:
    """The content type to upload *path* as, or "" when it is not a photo the
    server takes (judged by extension, case-insensitively)."""
    return PHOTO_TYPES.get(os.path.splitext(path or "")[1].lower(), "")


def failure_lines(errors: dict, labels: dict) -> list:
    """One "Label: reason" line per field that failed, in the page's order.

    *errors* maps a field to the reason the server gave, *labels* a field to
    the text the page shows for it. A field with no label is named by its key,
    so a failure is never dropped for want of a translation.
    """
    return [
        f"{labels.get(field, field)}: {errors[field]}"
        for field in FIELDS
        if field in errors
    ]
