pandas
======

How ``fleche`` digests pandas values.

``DataFrame``, ``Series``, ``Index`` (with its subclasses), ``pd.Timedelta``
and ``pd.NA`` are digested by the ``fleche-pandas`` companion package
(``pip install fleche-pandas``, or ``pip install "fleche[pandas]"``), which
pulls in ``fleche-numpy``; without it ``fleche`` refuses them as
:exc:`~fleche.digest.Indigestible`.  ``pd.Timestamp`` and ``pd.NaT`` are
``datetime.datetime`` subclasses and need no companion package.

Timedeltas
----------

A ``pd.Timedelta`` digests by its exact length in nanoseconds, whatever unit
it stores: ``pd.Timedelta("5s")``, ``pd.Timedelta(5000, "ms")`` and
``pd.Timedelta("5s").as_unit("s")`` digest alike.

``pd.Timedelta`` subclasses ``datetime.timedelta`` and compares equal to one of
the same length, but the two digest apart.  ``pd.NaT`` is not a
``pd.Timedelta`` (it also stands for missing datetimes) and keeps a digest of
its own.

This covers single values.  A ``TimedeltaIndex`` or a timedelta ``Series``
digests by its dtype and values, so there the unit matters:
``pd.to_timedelta(["5s"]).as_unit("s")`` and ``pd.to_timedelta(["5s"])`` digest
apart.
