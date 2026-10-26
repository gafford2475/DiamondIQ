import pytest
from fastapi.testclient import TestClient

from diamondiq import auth
from diamondiq import models as m
from diamondiq.api.main import app
from diamondiq.auth import hash_password, verify_password
from diamondiq.db import SessionLocal


def test_password_hashing():
    h = hash_password("a long passphrase")
    assert h.startswith("scrypt$") and "a long passphrase" not in h
    assert verify_password("a long passphrase", h)
    assert not verify_password("a long passphrasE", h)
    assert hash_password("same") != hash_password("same")  # salted


@pytest.fixture()
def fresh():
    """An app client against an empty users table."""
    with SessionLocal() as s:
        s.query(m.AuthSession).delete()
        s.query(m.User).delete()
        s.commit()
    auth.throttle.failures.clear()
    auth.SETUP_CODE = None
    with TestClient(app) as c:  # startup prints a setup code because there are no users
        yield c
    with SessionLocal() as s:
        s.query(m.AuthSession).delete()
        s.query(m.User).delete()
        s.commit()


def test_everything_requires_sign_in(fresh):
    assert fresh.get("/players").status_code == 401
    assert fresh.get("/health").status_code == 200
    assert fresh.get("/app/").status_code == 200  # the app shell loads and shows the sign-in screen


def test_first_admin_setup_needs_the_logged_code(fresh):
    assert fresh.get("/auth/status").json() == {"needs_setup": True}
    body = {"email": "Owner@Example.com", "name": "Owner", "password": "a strong passphrase"}
    assert fresh.post("/auth/setup", json={**body, "setup_code": "WRONG-CODE-0000"}).status_code == 403
    r = fresh.post("/auth/setup", json={**body, "setup_code": auth.SETUP_CODE.lower()})
    assert r.status_code == 201 and r.json()["role"] == "admin" and r.json()["email"] == "owner@example.com"
    assert fresh.get("/players").status_code == 200  # signed in by setup
    assert fresh.post("/auth/setup", json={**body, "setup_code": "x"}).status_code == 409
    assert fresh.get("/auth/status").json() == {"needs_setup": False}


def test_roles_login_logout_and_admin_management(fresh):
    with SessionLocal() as s:
        auth.create_user(s, "admin@example.com", "Ada", "admin passphrase", role="admin")
    r = fresh.post("/auth/login", json={"email": "admin@example.com", "password": "admin passphrase"})
    assert r.status_code == 200 and r.json()["token"]
    token = r.json()["token"]

    # admin adds a viewer and a scout
    assert fresh.post("/auth/users", json={"email": "v@example.com", "name": "Vic", "role": "viewer", "password": "short"}).status_code == 422
    vid = fresh.post("/auth/users", json={"email": "v@example.com", "name": "Vic", "role": "viewer", "password": "viewer passphrase"}).json()["id"]
    fresh.post("/auth/users", json={"email": "s@example.com", "name": "Sam", "role": "scout", "password": "scout passphrase"})
    assert len(fresh.get("/auth/users").json()) == 3
    assert fresh.patch(f"/auth/users/{fresh.get('/auth/me').json()['id']}", json={"role": "scout"}).status_code == 422

    # bearer tokens work for scripts
    with TestClient(app) as script:
        assert script.get("/players", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # viewer can read but not write, and can't manage users
    with TestClient(app) as v:
        v.post("/auth/login", json={"email": "v@example.com", "password": "viewer passphrase"})
        assert v.get("/players").status_code == 200
        assert v.post("/players", json={"first_name": "A", "last_name": "B"}).status_code == 403
        assert v.get("/auth/users").status_code == 403
        # deactivating the viewer signs them out
        fresh.patch(f"/auth/users/{vid}", json={"is_active": False})
        assert v.get("/players").status_code == 401

    # scout can write
    with TestClient(app) as sc:
        sc.post("/auth/login", json={"email": "s@example.com", "password": "scout passphrase"})
        assert sc.post("/players", json={"first_name": "A", "last_name": "B", "current_level": "HS"}).status_code == 201
        assert sc.post("/auth/me/password", json={"current_password": "nope", "new_password": "another passphrase"}).status_code == 401
        assert sc.post("/auth/me/password", json={"current_password": "scout passphrase", "new_password": "another passphrase"}).status_code == 204
        assert sc.get("/auth/me").status_code == 200  # still signed in here after the change
        assert sc.post("/auth/logout").status_code == 204
        assert sc.get("/players").status_code == 401

    fresh.post("/auth/logout")
    assert fresh.get("/players", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_login_throttling(fresh):
    with SessionLocal() as s:
        auth.create_user(s, "t@example.com", "T", "right passphrase")
    for _ in range(5):
        assert fresh.post("/auth/login", json={"email": "t@example.com", "password": "wrong guess!"}).status_code == 401
    assert fresh.post("/auth/login", json={"email": "t@example.com", "password": "right passphrase"}).status_code == 429
