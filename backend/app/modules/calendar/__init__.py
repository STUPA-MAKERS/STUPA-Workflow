"""Calendar module: iCal subscription of the principal's meetings.

A personal, rotatable feed token (``principal.calendar_token``) authenticates
the ``.ics`` subscription URL — calendar clients cannot log in via OIDC. The
feed lists meetings of the gremien the principal is a member of.
"""
