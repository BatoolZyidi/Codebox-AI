from codebox.assistant import classify
from codebox.wake import PhraseMatcher


def test_wake_variants():
    m = PhraseMatcher("wakeup codebox AI")
    for t in ["wakeup codebox AI", "Wake up, Codebox AI.", "wake up code box A.I.", "Hey wake-up CodeBox ai please"]:
        assert m.find(t)[0], t
    assert not m.find("close yourself codebox AI")[0]
    assert not m.find("please rename the function")[0]


def test_wake_remainder():
    ok, rest = PhraseMatcher("wakeup codebox AI").find("Wake up Codebox AI. Where is login handled?")
    assert ok and rest == "Where is login handled?"


def test_close_phrase_and_fuzzy():
    m = PhraseMatcher("close yourself codebox AI")
    assert m.find("Close yourself, Codebox AI.")[0]
    assert m.find("close yourself codebox eye")[0]  # slight mishearing
    assert not m.find("wakeup codebox AI")[0]


def test_classify():
    assert classify("Apply.") == "apply"
    assert classify("yes, apply it") == "request"  # unknown combo must NOT auto-apply
    assert classify("Yes.") == "apply"
    assert classify("go ahead") == "apply"
    assert classify("Reject.") == "reject"
    assert classify("read it again") == "repeat"
    assert classify("show details") == "details"
    assert classify("undo that") == "undo"
    assert classify("Undo.") == "undo"
    assert classify("No.") == "reject"
    assert classify("Cancel") == "reject"
    assert classify("Help") == "help"
    assert classify("Details.") == "details"
    assert classify("rename get user to fetch user") == "request"
    assert classify("where is the apply function") == "request"
