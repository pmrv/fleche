# fleche-pandas

[fleche](https://github.com/pmrv/fleche) digest hooks for pandas: `DataFrame`, `Series`, `Index` (with `MultiIndex`, `RangeIndex`, ...), `pd.Timedelta` and `pd.NA`.

```bash
pip install fleche-pandas
```

Installing it is all it takes: fleche finds the hooks through its `fleche` entry point group.
Without it, fleche refuses these values as `Indigestible` rather than guess at a digest.
It pulls in [fleche-numpy](https://pypi.org/project/fleche-numpy/), since object columns are digested element by element and often hold arrays.

How pandas objects are digested is described in fleche's [pandas documentation](https://fleche.readthedocs.io/en/latest/digests/pandas.html).

This package lives in the fleche repository, under `src/fleche-pandas`, and is versioned and released independently of fleche itself.
