import re
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.main import app
from app.models.prize import Prize
from app.models.redemption import Redemption
from app.models.user import User
from app.models.volunteer_entry import VolunteerEntry, VolunteerEntryStatus
from app.utilities.security import encrypt_password


@pytest.fixture
def client_and_engine() -> Iterator[tuple[TestClient, Engine]]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    def override_get_session() -> Iterator[Session]:
        with Session(test_engine) as session:
            yield session

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_get_session

    with Session(test_engine) as session:
        session.add_all(
            [
                User(
                    username="test_student",
                    email="student@example.com",
                    password=encrypt_password("student-pass"),
                    role="regular_user",
                ),
                User(
                    username="test_admin",
                    email="admin@example.com",
                    password=encrypt_password("admin-pass"),
                    role="admin",
                ),
            ]
        )
        session.commit()

    client = TestClient(
        app,
        base_url="https://testserver",
        follow_redirects=False,
    )
    try:
        yield client, test_engine
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        test_engine.dispose()


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 303
    assert "access_token" in client.cookies


def test_health_and_user_api_return_expected_shapes(client_and_engine):
    client, _ = client_and_engine

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"ok": True}

    users_response = client.get("/api/users")
    assert users_response.status_code == 200
    users = users_response.json()
    assert {user["username"] for user in users} == {"test_student", "test_admin"}
    assert all(set(user) == {"id", "username", "email"} for user in users)


def test_student_submits_hours_and_admin_rejects_entry(client_and_engine):
    client, engine = client_and_engine
    login(client, "test_student", "student-pass")

    form_response = client.get("/volunteer-hours")
    assert form_response.status_code == 200
    assert "Log Volunteer Hours" in form_response.text

    forbidden_response = client.get("/admin/volunteer-hours")
    assert forbidden_response.status_code == 401
    assert "Unauthorized" in forbidden_response.text
    assert "Volunteer contribution review" not in forbidden_response.text

    submission_response = client.post(
        "/volunteer-hours",
        data={
            "activity_name": "Campus garden",
            "organization": "Green Club",
            "hours": "2.5",
            "date": "2026-10-28",
        },
    )
    assert submission_response.status_code == 303
    assert submission_response.headers["location"].endswith("/volunteer-hours")

    with Session(engine) as session:
        entry = session.exec(select(VolunteerEntry)).one()
        assert entry.status is VolunteerEntryStatus.PENDING
        assert entry.date == date(2026, 10, 28)

    login(client, "test_admin", "admin-pass")
    review_response = client.get("/admin/volunteer-hours")
    assert review_response.status_code == 200
    assert "Campus garden" in review_response.text
    entry_match = re.search(
        r"/admin/volunteer-hours/(\d+)/review",
        review_response.text,
    )
    assert entry_match is not None
    entry_id = int(entry_match.group(1))

    decision_response = client.post(
        f"/admin/volunteer-hours/{entry_id}/review",
        data={"action": "reject"},
    )
    assert decision_response.status_code == 303

    updated_review = client.get("/admin/volunteer-hours")
    assert f"Entry {entry_id} rejected." in updated_review.text
    assert "Campus garden" not in updated_review.text
    with Session(engine) as session:
        entry = session.get(VolunteerEntry, entry_id)
        assert entry is not None
        assert entry.status is VolunteerEntryStatus.REJECTED


def test_admin_creates_prize_and_student_redeems_with_balance_rules(
    client_and_engine,
):
    client, engine = client_and_engine
    login(client, "test_student", "student-pass")
    submission_response = client.post(
        "/volunteer-hours",
        data={
            "activity_name": "Food bank shift",
            "organization": "Community Pantry",
            "hours": "6.5",
            "date": "2026-10-27",
        },
    )
    assert submission_response.status_code == 303

    with Session(engine) as session:
        entry = session.exec(select(VolunteerEntry)).one()
        entry_id = entry.id

    login(client, "test_admin", "admin-pass")
    approval_response = client.post(
        f"/admin/volunteer-hours/{entry_id}/review",
        data={"action": "approve"},
    )
    assert approval_response.status_code == 303

    create_form = client.get("/admin/prizes/new")
    assert create_form.status_code == 200
    assert "Create Prize" in create_form.text

    for name, cost, quantity in (
        ("Available Reward", "5", "1"),
        ("Costly Reward", "7", "2"),
    ):
        create_response = client.post(
            "/admin/prizes/new",
            data={
                "name": name,
                "description": f"{name} description",
                "cost_in_hours": cost,
                "quantity_available": quantity,
            },
        )
        assert create_response.status_code == 303
        assert f"Prize '{name}' created." in client.get(
            "/admin/prizes/new"
        ).text

    with Session(engine) as session:
        prizes = {
            prize.name: prize
            for prize in session.exec(select(Prize)).all()
        }
        affordable_id = prizes["Available Reward"].id
        costly_id = prizes["Costly Reward"].id

    login(client, "test_student", "student-pass")
    rewards_response = client.get("/rewards")
    assert rewards_response.status_code == 200
    assert "Your Balance: 6.5 Hours" in rewards_response.text
    assert "Available Reward" in rewards_response.text
    assert "Costly Reward" in rewards_response.text

    unaffordable_response = client.post(f"/rewards/{costly_id}/redeem")
    assert unaffordable_response.status_code == 303
    rewards_after_rejection = client.get("/rewards")
    assert "You need 7 approved hours to redeem this prize." in (
        rewards_after_rejection.text
    )
    with Session(engine) as session:
        costly_prize = session.get(Prize, costly_id)
        assert costly_prize is not None
        assert costly_prize.quantity_available == 2

    redemption_response = client.post(f"/rewards/{affordable_id}/redeem")
    assert redemption_response.status_code == 303
    rewards_after_redemption = client.get("/rewards")
    assert "Prize redeemed successfully." in rewards_after_redemption.text
    assert "Your Balance: 1.5 Hours" in rewards_after_redemption.text
    with Session(engine) as session:
        affordable_prize = session.get(Prize, affordable_id)
        redemptions = session.exec(select(Redemption)).all()
        assert affordable_prize is not None
        assert affordable_prize.quantity_available == 0
        assert len(redemptions) == 1
        assert redemptions[0].student_id == entry.student_id

    out_of_stock_response = client.post(f"/rewards/{affordable_id}/redeem")
    assert out_of_stock_response.status_code == 303
    rewards_after_stock_error = client.get("/rewards")
    assert "This prize is out of stock." in rewards_after_stock_error.text
