"""C2 continuation prose keeps identity and incoming blocking authority."""
from app.services.h3_execution_optimizer import _identity_picture_subjects
from app.services.h3_native_prompt import check_native_prompt


def test_identity_picture_pronoun_in_its_own_subject_definition():
    prompt = ("<Subject 1> is 宫女1. <Picture 2> applies only to her permanent identity.\n"
              "<Subject 2> is 侍从1. <Picture 3> applies only to his permanent identity.")
    assert _identity_picture_subjects(prompt, "<Picture 2>") == {"<Subject 1>"}
    assert _identity_picture_subjects(prompt, "<Picture 3>") == {"<Subject 2>"}


def test_identity_picture_pronoun_with_multiple_subjects_is_not_inferred():
    prompt = "<Subject 1> is 宫女1 beside <Subject 2>. <Picture 2> applies only to her permanent identity."
    assert _identity_picture_subjects(prompt, "<Picture 2>") == set()


def test_verified_incoming_video_do_not_overwrite_blocking_is_preservation():
    prompt = ("subject_definitions:\n<Subject 1> is A.\nsummary:\nA corridor.\n"
              "retention_analysis:\nIdentity images do not overwrite the current costumes, bodies, poses, "
              "floor positions, or blocking already established by the incoming video.\n"
              "detailed_description:\nContinue from incoming video.\n"
              "overall_soundscape:\nQuiet.\nnon_diegetic_music:\nN/A")
    authority = {"subject_bindings": {"<Subject 1>": "A"}, "reference_bindings": [],
                 "continuation": {"binding_verified": True}}
    checks, _ = check_native_prompt(prompt, [], authority, prompt, {})
    assert checks["blocking_preservation_wording"]
    authority["continuation"]["binding_verified"] = False
    checks, _ = check_native_prompt(prompt, [], authority, prompt, {})
    assert not checks["blocking_preservation_wording"]
