"""Offline natal calculation smoke test — no live users or payments."""
from natal_compat import natal, natal_pair, city_info
for city in ("Москва","Самара","Владивосток"):
    place=city_info(city)
    assert place is not None, f"birth city not resolved: {city}"
a=natal("05.01.1990","04:30","Москва")
b=natal("14.05.1993","13:10","Самара")
assert a and b, "natal calculation did not return valid planets"
assert 0<=a["sun"]<360 and 0<=a["ascendant"]<360
score,details=natal_pair(a,b)
assert 0<=score<=100
print("[test] offline natal synastry / Moscow / Samara / Vladivostok PASS",flush=True)
