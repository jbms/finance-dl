import pytest

from finance_dl.ofx import sanitize_account_name


def test_sanitize_account_name_disallows_dot():
    with pytest.raises(ValueError):
        sanitize_account_name('.')


def test_sanitize_account_name_disallows_double_dot():
    with pytest.raises(ValueError):
        sanitize_account_name('..')


def test_sanitize_account_name_passes_through_standard_characters():
    account_name = 'abc1234.5678-90-XYZ'

    assert sanitize_account_name(account_name) == account_name


def test_sanitize_account_name_replaces_invalid_characters():
    assert sanitize_account_name('1234$!5678:XYZ') == '1234-5678-XYZ'
