# fleche-ase

[fleche](https://github.com/pmrv/fleche) digest hooks for the [Atomic Simulation Environment](https://wiki.fysik.dtu.dk/ase/): `Atoms`, its constraints, `Calculator`, `VibrationsData` and the `ase.thermochemistry` classes.

```bash
pip install fleche-ase
```

Installing it is all it takes: fleche finds the hooks through its `fleche` entry point group.
Without it, fleche does not digest these values.
Destructuring value stores inline an `Atoms` into its parent entry like a scalar, unless it carries a live calculator.

How each type is digested is described in fleche's [entry point documentation](https://fleche.readthedocs.io/en/latest/digests/entry_points.html).

This package lives in the fleche repository, under `src/fleche-ase`, and is versioned and released independently of fleche itself.
