
from src.kr.rules import check_shift_duration


def test_shift_within_limit():
    result = check_shift_duration(8, 16, 9)
    assert result["passed"] is True


def test_shift_exceeds_limit():
    result = check_shift_duration(8, 19, 9)
    assert result["passed"] is False


def test_shift_at_exact_limit():
    result = check_shift_duration(8, 17, 9)
    assert result["passed"] is True


def test_invalid_shift_times():
    result = check_shift_duration(18, 8, 9)
    assert result["passed"] is False
