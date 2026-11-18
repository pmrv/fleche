"""Values the sister packages declare as leaves of a destructuring store (#1063).

fleche-pandas and fleche-ase list them under the ``fleche`` entry point
``destructure``: depth 0, inlined into their parent like an ``int``.
fleche-numpy's arrays are covered in test_destructuring_arrays.py.
"""

import pytest

from fleche.digest import digest
from fleche.storage.memory import ValueMemory


def entries(value, remaining_depth=1):
    vm = ValueMemory({}, remaining_depth=remaining_depth)
    key = vm.save(value)
    assert key == digest(value)
    return vm, key


class TestPandas:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("fleche_pandas")

    @pytest.mark.parametrize("make", [
        lambda pd: pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}),
        lambda pd: pd.Series([1.0, 2.0], name="s"),
        lambda pd: pd.Index([3, 4], name="i"),
    ], ids=["DataFrame", "Series", "Index"])
    def test_inlined(self, make):
        value = make(self.pd)
        vm, key = entries({"v": value, "n": 1})
        assert set(vm.storage) == {key}
        assert vm.load(key)["v"].equals(value)

    def test_split_at_depth_zero(self):
        frame = self.pd.DataFrame({"a": [1]})
        vm, _ = entries([frame], remaining_depth=0)
        assert digest(frame) in vm.storage


class TestAse:
    ase = pytest.importorskip("ase")
    pytest.importorskip("fleche_ase")

    def atoms(self):
        from ase import Atoms
        return Atoms("Cu2", positions=[[0, 0, 0], [0, 0, 2]], cell=[5, 5, 5], pbc=True)

    def test_bare_atoms_inlined(self):
        atoms = self.atoms()
        vm, key = entries([atoms, 1])
        assert set(vm.storage) == {key}
        assert vm.load(key)[0] == atoms

    def test_atoms_with_stored_results_inlined(self):
        from ase.calculators.singlepoint import SinglePointCalculator
        atoms = self.atoms()
        atoms.calc = SinglePointCalculator(atoms, energy=1.5)
        vm, key = entries([atoms, 1])
        assert set(vm.storage) == {key}
        assert vm.load(key)[0].get_potential_energy() == 1.5

    def test_atoms_with_a_live_calculator_stays_separate(self):
        """The calculator is pickled with the structure and may be a whole model."""
        from ase.calculators.emt import EMT
        atoms = self.atoms()
        atoms.calc = EMT()
        vm, key = entries([atoms, 1])
        assert digest(atoms) in vm.storage
        assert vm.child_digests(key) == {digest(atoms)}
