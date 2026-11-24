"""Paperless filing: find the files to file, build them and hand them to Paperless.

The module reads the final protocols, the decisions on Anträge and the Haushaltspläne
in force, opens one job per file in the record of the module `paperless`, and runs the
jobs in the worker (`worker/paperless.py`). No module of the platform calls it at its
event: the worker finds the events within a minute, so an outage of Paperless never
reaches a finalization or a decision (§F/integrations/paperless/002523).
"""
