from datetime import date
from unittest.mock import Mock

import pytest

from app.models.prize import Prize
from app.models.volunteer_entry import VolunteerEntry, VolunteerEntryStatus
from app.repositories.prize_repository import PrizeRepository
from app.repositories.redemption_repository import RedemptionRepository
from app.repositories.volunteer_entry_repository import VolunteerEntryRepository
from app.services.prize_service import PrizeService
from app.services.redemption_service import RedemptionService
from app.services.volunteer_hours import VolunteerHoursService


def test_submit_entry_creates_pending_entry_through_repository():
    repository = Mock(spec=VolunteerEntryRepository)
    repository.create.side_effect = lambda entry: entry
    service = VolunteerHoursService(repository)

    entry = service.submit_entry(
        student_id=7,
        activity_name="Beach clean-up",
        organization="Campus Club",
        hours=3.5,
        entry_date=date(2026, 10, 28),
    )

    assert entry.status is VolunteerEntryStatus.PENDING
    assert entry.student_id == 7
    assert entry.activity_name == "Beach clean-up"
    assert entry.organization == "Campus Club"
    assert entry.hours == 3.5
    assert entry.date == date(2026, 10, 28)
    repository.create.assert_called_once_with(entry)


def test_review_entry_normalizes_action_and_updates_repository():
    repository = Mock(spec=VolunteerEntryRepository)
    expected = VolunteerEntry(
        id=12,
        student_id=7,
        activity_name="Beach clean-up",
        organization="Campus Club",
        hours=3.5,
        date=date(2026, 10, 28),
        status=VolunteerEntryStatus.APPROVED,
    )
    repository.update_status.return_value = expected
    service = VolunteerHoursService(repository)

    result = service.review_entry(entry_id=12, action=" APPROVE ")

    assert result is expected
    repository.update_status.assert_called_once_with(
        12, VolunteerEntryStatus.APPROVED
    )


def test_review_entry_rejects_unknown_action_without_repository_call():
    repository = Mock(spec=VolunteerEntryRepository)
    service = VolunteerHoursService(repository)

    with pytest.raises(ValueError, match="Action must be approve or reject"):
        service.review_entry(entry_id=12, action="defer")

    repository.update_status.assert_not_called()


def test_review_entry_reports_missing_or_already_decided_entry():
    repository = Mock(spec=VolunteerEntryRepository)
    repository.update_status.return_value = None
    service = VolunteerHoursService(repository)

    with pytest.raises(ValueError, match="Entry 12 not found or already decided"):
        service.review_entry(entry_id=12, action="reject")


def test_create_prize_builds_model_and_delegates_to_repository():
    repository = Mock(spec=PrizeRepository)
    repository.create.side_effect = lambda prize: prize
    service = PrizeService(repository)

    prize = service.create_prize(
        name="Coffee voucher",
        description="A campus cafe drink",
        cost_in_hours=4,
        quantity_available=6,
    )

    assert prize.name == "Coffee voucher"
    assert prize.description == "A campus cafe drink"
    assert prize.cost_in_hours == 4
    assert prize.quantity_available == 6
    repository.create.assert_called_once_with(prize)


def test_get_rewards_returns_repository_balance_and_prizes():
    repository = Mock(spec=RedemptionRepository)
    prizes = [Prize(name="Coffee voucher", description="Drink", cost_in_hours=4)]
    repository.get_balance.return_value = 5.5
    repository.list_prizes.return_value = prizes
    service = RedemptionService(repository)

    balance, result = service.get_rewards(student_id=7)

    assert balance == 5.5
    assert result == prizes
    repository.get_balance.assert_called_once_with(7)
    repository.list_prizes.assert_called_once_with()


def test_redeem_prize_checks_balance_and_records_redemption():
    repository = Mock(spec=RedemptionRepository)
    prize = Prize(
        id=3,
        name="Coffee voucher",
        description="A campus cafe drink",
        cost_in_hours=4,
        quantity_available=2,
    )
    repository.get_prize.return_value = prize
    repository.get_balance.return_value = 5
    repository.create_redemption_and_decrement_inventory.return_value = True
    service = RedemptionService(repository)

    result = service.redeem_prize(student_id=7, prize_id=3)

    assert result is prize
    repository.get_prize.assert_called_once_with(3)
    repository.get_balance.assert_called_once_with(7)
    repository.create_redemption_and_decrement_inventory.assert_called_once_with(
        student_id=7,
        prize_id=3,
    )


@pytest.mark.parametrize(
    ("prize", "balance", "inventory_update", "message"),
    [
        (None, 10, True, "This prize is no longer available."),
        (
            Prize(
                id=3,
                name="Coffee voucher",
                description="Drink",
                cost_in_hours=4,
                quantity_available=0,
            ),
            10,
            True,
            "This prize is out of stock.",
        ),
        (
            Prize(
                id=3,
                name="Coffee voucher",
                description="Drink",
                cost_in_hours=4,
                quantity_available=1,
            ),
            3,
            True,
            "You need 4 approved hours to redeem this prize.",
        ),
        (
            Prize(
                id=3,
                name="Coffee voucher",
                description="Drink",
                cost_in_hours=4,
                quantity_available=1,
            ),
            4,
            False,
            "This prize is out of stock.",
        ),
    ],
)
def test_redeem_prize_rejects_unavailable_or_ineligible_redemptions(
    prize, balance, inventory_update, message
):
    repository = Mock(spec=RedemptionRepository)
    repository.get_prize.return_value = prize
    repository.get_balance.return_value = balance
    repository.create_redemption_and_decrement_inventory.return_value = (
        inventory_update
    )
    service = RedemptionService(repository)

    with pytest.raises(ValueError, match=message):
        service.redeem_prize(student_id=7, prize_id=3)

    if prize is None or prize.quantity_available == 0 or balance < prize.cost_in_hours:
        repository.create_redemption_and_decrement_inventory.assert_not_called()
