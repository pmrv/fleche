# fleche-numpy

[fleche](https://github.com/pmrv/fleche) digest hooks for numpy: arrays (`np.ndarray` and its subclasses), `np.bool_` and `np.timedelta64`.

```bash
pip install fleche-numpy
```

Installing it is all it takes: fleche finds the hooks through its `fleche` entry point group.
Without it, fleche refuses these values as `Indigestible` rather than guess at a digest.
numpy number scalars (`np.float64`, `np.int32`, ...) need no hooks; fleche digests them itself.

How arrays are digested — dtype, shape and bytes, per field for structured dtypes, per element for object dtypes — is described in fleche's [numpy documentation](https://fleche.readthedocs.io/en/latest/digests/numpy.html).

This package lives in the fleche repository, under `src/fleche-numpy`, and is versioned and released independently of fleche itself.
