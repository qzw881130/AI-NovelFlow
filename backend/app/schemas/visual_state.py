"""P0 visual intent and observation contracts; no application dependencies."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator


CAPABILITY_POLICY_VERSION = "coarse_v1"


Predicate = Literal[
    "character_present", "prop_present", "character_location", "character_state",
    "facing_direction", "prop_owner", "contact_relation", "environment_relation", "surface_state",
]
Presence = Literal["PRESENT", "ABSENT", "OCCLUDED", "UNKNOWN"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class RecommendedNextAction(str, Enum):
    EDIT_IMAGE = "EDIT_IMAGE"
    REGENERATE_KEYFRAME = "REGENERATE_KEYFRAME"
    REPLAN_KEYFRAME = "REPLAN_KEYFRAME"
    REPLAN_CLIP = "REPLAN_CLIP"


class _Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, revalidate_instances="always")


class ObservationQuestion(_Contract):
    """Only the fact to inspect, never its desired state or a repair instruction.

    Locations name semantic regions; only the policy's coarse allowlist has
    automatic authority. Fine/legacy values remain parseable. Relation values
    name targets (optionally qualified, e.g. connected_to:river_main).
    """

    predicate: Predicate
    subject: NonBlank
    value: Annotated[str, StringConstraints(strip_whitespace=True, max_length=128)] = ""

    @model_validator(mode="after")
    def validate_value(self):
        if self.predicate in ("character_present", "prop_present"):
            if self.value:
                raise ValueError("Presence predicates have no value")
        elif not self.value:
            raise ValueError("Non-presence predicates require a named value")
        allowed = {
            "character_state": ("standing", "seated", "crouched", "airborne", "lying", "walking"),
            "surface_state": ("wet", "dry"),
            "facing_direction": ("left", "right", "front", "back", "three_quarter_left", "three_quarter_right"),
        }
        if self.predicate in allowed and self.value not in allowed[self.predicate]:
            raise ValueError("Value is outside the supported gross visual states")
        return self


class StateRequirement(ObservationQuestion):
    expected: Literal["PRESENT", "ABSENT"] = "PRESENT"
    critical: StrictBool = True
    protected: StrictBool = False
    known_unknown: StrictBool = Field(
        default=False, description="Caller-declared prior uncertainty for this field/source; prevents fact confirmation")
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] = Field(
        description="Approved intent provenance, not proof of image content")

    @model_validator(mode="after")
    def validate_protection(self):
        if self.protected and (not self.critical or self.expected != "PRESENT"
                               or self.predicate not in ("prop_present", "prop_owner")):
            raise ValueError("Only critical PRESENT prop presence/ownership requirements can be protected")
        return self


class AnchorState(_Contract):
    clip_index: int = Field(ge=1)
    reference_index: int = Field(ge=0, description="0 is primary; extras retain their actual selected order")
    requirements: list[StateRequirement] = Field(default_factory=list, max_length=64)


class VisualStateValidation(_Contract):
    enabled: StrictBool = False
    capability_policy: Literal["coarse_v1"] = CAPABILITY_POLICY_VERSION
    anchors: list[AnchorState] = Field(default_factory=list, max_length=64)
    invariants: list[StateRequirement] = Field(default_factory=list, max_length=64)


class ActualStateHandoff(_Contract):
    """Only an opt-in switch; intent comes from the frozen P0 plan contract."""

    enabled: StrictBool = False


class ObservationFact(ObservationQuestion):
    state: Presence
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    evidence: str = Field(default="", max_length=512)


class ImageObservation(_Contract):
    version: int = Field(default=1, ge=1, le=1)
    image_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    provider: NonBlank | None = None
    facts: list[ObservationFact] = Field(default_factory=list, max_length=256)
