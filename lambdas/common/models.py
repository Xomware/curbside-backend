from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # The IdPs map no name or email (curbside-infrastructure cognito_idps.tf),
    # so the client asks for one during onboarding.
    display_name: str = Field(min_length=1, max_length=80)
