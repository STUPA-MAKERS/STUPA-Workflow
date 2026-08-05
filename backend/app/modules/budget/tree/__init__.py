"""Cost-center budget tree: CRUD, fiscal years, allocations, bookings, invoices.

Layout:

* `.service_base` — shared constructor plus lookup and audit helpers for all ops classes.
* `.nodes` — cost-center (node) CRUD, including a key rename with path rewrite.
* `.fiscal_years` — fiscal-year CRUD plus the label map on top-level budgets.
* `.allocations` — top-down allocation with parent and children constraints.
* `.applications` — application to cost-center assignment plus subtree listing.
* `.expenses` — expense and income bookings: create, update, filtered listing, delete.
* `.subbookings` — sub-bookings of a booking.
* `.invoices` — invoice CRUD plus ZUGFeRD import and file storage.
* `.transfers` — cost-center to cost-center transfers (paired bookings).
* `.revert` — audit-log revert of budget and money mutations.
* `.view` — scoped tree view with allocated, committed and requested roll-up.
* `.service` — `.service.BudgetTreeService`, the facade that combines the ops.
"""
