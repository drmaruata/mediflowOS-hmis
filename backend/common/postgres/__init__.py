"""PostgreSQL backend with schema-per-module table placement.

Architecture doc section 6 states each module owns its tables, with "schema
per module inside the one database", and section 10 refers to a ``quality``
schema. The models express that with dotted ``db_table`` values such as
``"registry.patient"``.

Django's stock schema editor quotes ``db_table`` verbatim, so
``db_table = "registry.patient"`` produces ``"registry.patient"`` - a single
identifier, i.e. one table literally *named* ``registry.patient`` in the
default schema. The declared schema separation never happens, and the row
level security SQL in section 7 of the architecture doc cannot be applied to
it.

This backend resolves those dotted names to genuine PostgreSQL schemas. It
mirrors the layout of ``django.db.backends.postgresql``: Django imports a
custom backend as ``<ENGINE>.base``, so this directory must expose ``base``
and may keep its schema editor in ``schema``.
"""