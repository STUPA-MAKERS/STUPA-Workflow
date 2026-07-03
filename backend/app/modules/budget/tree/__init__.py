"""Cost-centre budget tree — CRUD, fiscal years, allocations, bookings, accounts, invoices.

Layout:

* :mod:`.service_base` — shared constructor + lookup/audit helpers for all ops classes.
* :mod:`.nodes`        — cost-centre (node) CRUD incl. key rename with path rewrite.
* :mod:`.fiscal_years` — fiscal-year CRUD + label map on top-level budgets.
* :mod:`.allocations`  — top-down allocation with parent/children constraints.
* :mod:`.applications` — application ↔ cost-centre assignment + subtree listing.
* :mod:`.expenses`     — expense/income bookings: create, update, filtered listing, delete.
* :mod:`.subbookings`  — sub-bookings of a booking, incl. CAMT/MT940 file import.
* :mod:`.accounts`     — bank accounts + FinTS connection config.
* :mod:`.invoices`     — invoice CRUD + ZUGFeRD import and file storage.
* :mod:`.transfers`    — cost-centre to cost-centre transfers (paired bookings).
* :mod:`.revert`       — audit-log revert of budget/money mutations.
* :mod:`.view`         — scoped tree view with allocated/committed/requested roll-up.
* :mod:`.service`      — :class:`~.service.BudgetTreeService` facade combining the ops.
"""
