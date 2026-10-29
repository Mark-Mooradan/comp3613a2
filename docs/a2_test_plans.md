# COMP 3613 Assignment 2 — Test Plans

## Project and scope

The application is the Student Awards incentive system described in
[`report.md`](report.md). It has four workflows:

1. Log Volunteer Hours (Student)
2. Approve Volunteer Hours (Admin)
3. Create Prize (Admin)
4. Redeem a Prize (Student)

The plans below cover the service rules, the FastAPI routes and their database
effects, and acceptance of the four workflows against the current wireframes.
The workflow pages are HTML forms; their POST routes accept form-encoded data
and respond with redirects. `/health` and `/api/users` are JSON endpoints.

## Unit Test Plan

**Purpose:** Verify each domain service in isolation. Repository objects are
mocked so the tests check service decisions and repository calls without a
database, HTTP request, or template.

| ID | Service / behavior | Test data and action | Expected result |
|---|---|---|---|
| UT-01 | Submit volunteer hours | Submit a student's activity, organization, hours, and date. | A `VolunteerEntry` with the supplied values and `Pending` status is passed to the repository and returned. |
| UT-02 | Review volunteer hours | Review an entry with a whitespace-padded, mixed-case `approve` action. | The service normalizes the action and asks the repository to set `Approved`. |
| UT-03 | Reject invalid review action | Submit an action other than `approve` or `reject`. | A `ValueError` is raised and no repository update is made. |
| UT-04 | Review missing/already-decided entry | Repository returns no updated entry. | A `ValueError` explains that the entry is missing or already decided. |
| UT-05 | Create prize | Supply name, description, hours cost, and inventory. | The service creates a `Prize`, delegates it to the repository, and returns it. |
| UT-06 | Load rewards | Repository provides a balance and prize list. | The service returns both values unchanged for the requesting student. |
| UT-07 | Redeem eligible prize | Prize exists, has inventory, balance covers its cost, and inventory update succeeds. | The prize is returned and one redemption/inventory update is requested for that student and prize. |
| UT-08 | Reject invalid redemption | Try a missing prize, an out-of-stock prize, a balance below cost, or an inventory update that loses a race. | Each case raises the corresponding `ValueError`; no redemption is recorded for missing, out-of-stock, or unaffordable prizes. |

**Execution:** `pytest tests/test_unit.py`

## Integration Test Plan

**Purpose:** Exercise the actual FastAPI routes, authentication, templates,
service/repository wiring, and persisted database effects. Tests use an
in-memory SQLite database and replace the session dependency; they do not
connect to the configured development or production database.

| ID | Route(s) / workflow | Setup and action | Expected result |
|---|---|---|---|
| IT-01 | `GET /health`, `GET /api/users` | Request both endpoints against a database containing test student and admin accounts. | Health returns `{"ok": true}`; users returns the expected public fields and does not expose passwords. |
| IT-02 | `GET, POST /volunteer-hours`; `GET, POST /admin/volunteer-hours/{id}/review` | Log in as student, submit a dated entry, then log in as admin and reject it. | Form pages render, POSTs redirect, the entry is initially `Pending`, the admin sees it, and rejection persists as `Rejected` and removes it from the pending list. A student is denied the admin page. |
| IT-03 | `POST /login`; `POST /admin/volunteer-hours/{id}/review`; `GET, POST /admin/prizes/new`; `GET /rewards`; `POST /rewards/{id}/redeem` | Submit 6.5 hours as a student, approve them as admin, create prizes costing 5 and 7 hours, then try the unaffordable prize and redeem the affordable one. Retry the redeemed prize after its inventory reaches zero. | The reward page shows the derived 6.5-hour balance. The unaffordable attempt leaves inventory and redemptions unchanged and displays a failure message. Successful redemption records one row, decrements inventory, displays a success message, and refreshes the balance to 1.5 hours. A second attempt reports out-of-stock. |

**Execution:** `pytest tests/test_integration.py`

## User Acceptance Test (UAT) Plan

**Purpose:** Have a student and admin confirm that each named workflow can be
completed and that the visible outcome agrees with the wireframes and stated
business rules.

**Environment and test accounts**

- Run the application against a disposable test database with the current
  schema and one student and one admin account.
- Use a browser (or the matching requests in
  [`postman_collection.json`](postman_collection.json)); test as both roles.
- Record each case as **Pass**, **Fail**, or **Blocked**, with the observed
  result and any defect reference.

| ID | Workflow / role | Preconditions and steps | Acceptance criteria |
|---|---|---|---|
| UAT-01 | Log Volunteer Hours — Student | Sign in as a student. Open Log Hours, enter an activity, organization, positive hours, and date, then submit. | The form is usable and the student sees confirmation that the entry is pending approval. The submitted values appear in the admin's pending-review list with `Pending` status. |
| UAT-02 | Approve Volunteer Hours — Admin | Sign in as admin. Open the review list for a pending student entry and choose Approve. Repeat with another pending entry and choose Reject. | Each decision shows its outcome. Decided entries disappear from the pending list; approved hours contribute to the student's spendable balance, while rejected hours do not. |
| UAT-03 | Create Prize — Admin | Sign in as admin. Open the prize form and enter a name, description, cost in hours, and available quantity. Submit. | A creation confirmation appears. The prize appears on the student rewards page with the entered cost and quantity. |
| UAT-04 | Redeem a Prize — Student | Sign in as a student with enough approved hours. View Rewards, redeem an in-stock affordable prize, then attempt an unaffordable or out-of-stock prize. | The successful redemption confirms, reduces the balance by the prize cost, decreases quantity by one, and is reflected when Rewards is refreshed. Invalid attempts explain the reason and do not change balance or inventory. |

### UAT exit criteria

- All four workflows are accepted by their intended roles.
- No unresolved critical or high-severity issue prevents a workflow from
  completing.
- Any failed or blocked case has an owner and retest result recorded.

## Running the automated tests

From the repository root, run:

```text
pytest
```

The project pytest configuration is in `pyproject.toml`. Integration tests use
only in-memory SQLite and can run without resetting the application's database.
