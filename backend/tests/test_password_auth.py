from app import password_auth


def test_hash_then_verify_round_trips():
    hashed = password_auth.hash_password("Correct-Horse9")
    assert password_auth.verify_password("Correct-Horse9", hashed)


def test_wrong_password_does_not_verify():
    hashed = password_auth.hash_password("Correct-Horse9")
    assert not password_auth.verify_password("Wrong-Password1", hashed)


def test_hash_is_never_the_plaintext():
    hashed = password_auth.hash_password("Correct-Horse9")
    assert hashed != "Correct-Horse9"
    assert "Correct-Horse9" not in hashed


def test_two_hashes_of_the_same_password_differ():
    # bcrypt embeds a random salt per hash -- if this ever failed, it'd mean
    # gensalt() broke or got hardcoded, both real regressions.
    assert password_auth.hash_password("Correct-Horse9") != password_auth.hash_password("Correct-Horse9")


def test_verify_against_a_malformed_hash_returns_false_not_a_crash():
    assert not password_auth.verify_password("anything", "not-a-real-bcrypt-hash")
