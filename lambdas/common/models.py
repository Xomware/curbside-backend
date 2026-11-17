from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

# extra="forbid": a body can't set fields the server owns, like `published`.
_STRICT = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # The IdPs map no name or email (curbside-infrastructure cognito_idps.tf),
    # so the client asks for one during onboarding.
    display_name: str = Field(min_length=1, max_length=80)


class LinkRequest(BaseModel):
    id_token: str = Field(min_length=1, max_length=8192)


class Patch(BaseModel):
    """PATCH body: `version` plus the fields to change. Null clears a field in `nullable`."""

    model_config = _STRICT
    nullable: ClassVar[frozenset[str]] = frozenset()

    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        changed = self.model_fields_set - {"version"}
        if not changed:
            raise ValueError("no fields to update")
        nulled = sorted(k for k in changed if getattr(self, k) is None and k not in self.nullable)
        if nulled:
            raise ValueError(f"cannot be null: {', '.join(nulled)}")
        return self

    def changes(self) -> dict:
        return self.model_dump(mode="json", exclude_unset=True, exclude={"version"})


class Point(BaseModel):
    model_config = _STRICT

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class MapCreate(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=80)
    center: Point
    radius_m: int = Field(default=300, ge=50, le=1000)


class MapUpdate(Patch):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    center: Point | None = None
    radius_m: int | None = Field(default=None, ge=50, le=1000)


class HouseholdCreate(BaseModel):
    model_config = _STRICT

    label: str = Field(min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    building_id: str | None = Field(default=None, max_length=100)


class HouseholdUpdate(Patch):
    nullable = frozenset({"address", "building_id", "last_talked_at"})

    label: str | None = Field(default=None, min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    building_id: str | None = Field(default=None, max_length=100)
    last_talked_at: AwareDatetime | None = None


_BIRTHDAY = r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"
_YEAR = {"ge": 1900, "le": date.today().year}


class PersonCreate(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=80)
    role: Literal["adult", "kid"]
    birth_year: int | None = Field(default=None, **_YEAR)
    # "About 6" in a capture becomes current year - 6 with this set.
    birth_year_approx: bool = False
    birthday: str | None = Field(default=None, pattern=_BIRTHDAY)
    notes: str | None = Field(default=None, max_length=1000)


class PersonUpdate(Patch):
    nullable = frozenset({"birth_year", "birthday", "notes"})

    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["adult", "kid"] | None = None
    birth_year: int | None = Field(default=None, **_YEAR)
    birth_year_approx: bool | None = None
    birthday: str | None = Field(default=None, pattern=_BIRTHDAY)
    notes: str | None = Field(default=None, max_length=1000)


class PetCreate(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=80)
    species: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)


class PetUpdate(Patch):
    nullable = frozenset({"species", "notes"})

    name: str | None = Field(default=None, min_length=1, max_length=80)
    species: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)


class NoteCreate(BaseModel):
    model_config = _STRICT

    text: str = Field(min_length=1, max_length=2000)
    source: Literal["voice", "text", "manual"] = "manual"


Ulid = Annotated[str, StringConstraints(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]


class CaptureParse(BaseModel):
    model_config = _STRICT

    transcript: str = Field(min_length=1, max_length=2000)
    source: Literal["voice", "text"]
    focus_household_id: Ulid | None = None
    nearby_household_ids: list[Ulid] = Field(default_factory=list, max_length=8)


class HouseholdDraft(BaseModel):
    """A household as a capture names it; the client adds lat/lng before apply."""

    model_config = _STRICT

    label: str = Field(min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
