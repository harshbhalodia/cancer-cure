import pytest

from app.services.safety import EMERGENCY, URGENT, lint, triage


@pytest.mark.parametrize(
    "text,level",
    [
        ("He has chest pain since morning", EMERGENCY),
        ("I can't breathe properly", EMERGENCY),
        ("bleeding from the mouth that won't stop", EMERGENCY),
        ("slurred speech and face drooping", EMERGENCY),
        ("I don't want to live anymore", EMERGENCY),
        ("Temperature is 101 and chills tonight", URGENT),
        ("new swelling in his neck", URGENT),
        ("unable to swallow even water", URGENT),
        ("What does SUV max mean in a PET scan?", None),
        ("Can you summarise the latest report?", None),
    ],
)
def test_triage_levels(text, level):
    assert triage(text).level == level


@pytest.mark.parametrize(
    "answer",
    [
        "You should stop chemotherapy now.",
        "Take 500 mg twice daily with food.",
        "Skip the immunotherapy for a few weeks.",
        "Try turmeric instead of radiation.",
        "This is definitely a recurrence.",
        "You will be cured.",
    ],
)
def test_lint_blocks_unsafe(answer):
    assert lint(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "Please do not stop treatment without talking to your oncologist.",
        "Ask your oncologist whether to pause immunotherapy.",
        "The report says the lesion shrank from 34 mm to 18 mm [D1 p1].",
        "Your records list a dose of 40 mg/m2, which is decided by the oncology team.",
        "The PET-CT impression says the lesion appears to be a recurrent neoplastic lesion.",
    ],
)
def test_lint_allows_safe(answer):
    assert lint(answer) == []
