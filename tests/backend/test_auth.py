"""auth 单元测试：密码哈希 + JWT。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)


def test_password_wrong_rejected():
    hashed = hash_password("right")
    assert not verify_password("wrong", hashed)


def test_password_hash_salted():
    """同一密码两次哈希应不同（bcrypt 随机盐）。"""
    assert hash_password("x" * 8) != hash_password("x" * 8)


def test_token_roundtrip():
    token = create_access_token(42, "bob")
    payload = decode_token(token)
    assert payload == {"user_id": 42, "username": "bob"}


def test_token_garbage_rejected():
    with pytest.raises(HTTPException) as ei:
        decode_token("not-a-jwt")
    assert ei.value.status_code == 401


def test_token_tampered_rejected():
    token = create_access_token(1, "a")
    with pytest.raises(HTTPException):
        decode_token(token[:-2] + "xx")
