from __future__ import annotations

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# extra="forbid": a body can't set fields the server owns, like `published`.
_STRICT = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # The IdPs map no name or email (curbside-infrastructure cognito_idps.tf),
    # so the client asks for one during onboarding.
    display_name: str = Field(min_length=1, max_length=80)


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
