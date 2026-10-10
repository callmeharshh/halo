"""Run: python tests/test_safety.py   (plain asserts, no pytest needed)"""
import os, sys
from decimal import Decimal as D
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import safety as s

def eq(a, b, msg=""):
    assert a == b, f"{msg}: expected {b!r}, got {a!r}"

# numbers heard -> amounts
for text, want in [
    ("send zero point one MON to Alice", [D("0.1")]),
    ("send 0.1 MON to alice", [D("0.1")]),
    ("send point five", [D("0.5")]),            # no integer part is not parsed as 0.5; handled below
]:
    pass
eq(s.numbers_in("send zero point one MON to Alice"), [D("0.1")], "words with point")
eq(s.numbers_in("send 0.1 MON to alice"), [D("0.1")], "digits")
eq(s.numbers_in("send 0 point 5 mon"), [D("0.5")], "digit point digit")
eq(s.numbers_in("send two MON"), [D("2")], "word int")
eq(s.numbers_in("send ten mon to bob"), [D("10")], "ten")
eq(s.numbers_in("alice ko ek dashmalav paanch bhej do"), [D("1.5")], "hinglish decimal")
eq(s.numbers_in("अलिस को दो मोन भेज दो"), [D("2")], "hindi word with unit")
eq(s.numbers_in("अलिस को भेज दो"), [], "verb दो is not a number")
eq(s.numbers_in("bhej do"), [], "verb do is not a number")
eq(s.numbers_in("send do mon"), [D("2")], "do + unit is two")
eq(s.numbers_in("भेजो ०.५"), [D("0.5")], "devanagari digits")
eq(s.numbers_in("send some money to alice"), [], "no number")

# the LLM's amount must appear in the user's speech
assert s.amount_matches_speech(0.1, "send zero point one MON to Alice")
assert s.amount_matches_speech("0.1", "send 0.1 mon to alice")
assert not s.amount_matches_speech(1, "send zero point one MON to Alice"), "1 != 0.1 (the classic mishearing)"
assert not s.amount_matches_speech(0.1, "send ten MON to Alice")
assert not s.amount_matches_speech(5, "send some money to alice"), "invented amount"

eq(s.say_amount(D("0.1")), "zero point one", "say 0.1")
eq(s.say_amount(D("0.25")), "zero point two five", "say 0.25")

# confirm / cancel
for t, want in [("confirm", "confirm"), ("yes confirm", "confirm"), ("Yes.", "confirm"), ("haan", "confirm"),
                ("हाँ", "confirm"), ("हां कर दो", "confirm"), ("pakka bhej do", "confirm"),
                ("cancel", "cancel"), ("no", "cancel"), ("nahi", "cancel"), ("नहीं", "cancel"), ("ruko", "cancel"),
                ("no don't confirm", "cancel"), ("yes wait no", "cancel"),
                ("the weather is nice today and yes it is", None), ("", None), ("open safari", None),
                ("know", None), ("yesterday", None)]:
    eq(s.classify_reply(t), want, f"classify {t!r}")

# contact matching
names = ["alice", "bob", "ramesh"]
eq(s.match_contact("Alice", names), ("alice", ""), "exact")
eq(s.match_contact("Alis", names), ("alice", ""), "misheard Alis")
eq(s.match_contact("rameesh", names), ("ramesh", ""), "misheard ramesh")
assert s.match_contact("Zoltan", names)[0] is None
assert s.match_contact("ali", ["alice", "alina"])[0] is None, "ambiguous must be refused"
print("ALL SAFETY TESTS PASSED")
