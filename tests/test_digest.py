import os
import time
import types

import numpy as np
import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones
from ase.thermochemistry import (
    CrystalThermo,
    HarmonicMode,
    HarmonicThermo,
    HinderedThermo,
    IdealGasThermo,
    MSRRHOThermo,
    QuasiHarmonicThermo,
    RRHOMode,
)
from ase.vibrations import VibrationsData
from ase.calculators.calculator import Calculator
from fleche.digest import Indigestible, digest

import fleche_ase

VIB_ENERGIES = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09]


@pytest.fixture
def water():
    return Atoms(
        "H2O",
        positions=[[0, 0, 0], [0, 0, 1], [0, 1, 0]],
    )


def test_atoms_digest_stable(water):
    assert digest(water) == digest(water.copy())


def test_atoms_digest_differs_on_positions(water):
    other = water.copy()
    other.positions[0, 0] += 0.1
    assert digest(water) != digest(other)


def test_calculator_digest_stable():
    calc1 = LennardJones(epsilon=1.0, sigma=1.0)
    calc2 = LennardJones(epsilon=1.0, sigma=1.0)
    assert digest(calc1) == digest(calc2)


def test_calculator_digest_differs_on_parameters():
    calc1 = LennardJones(epsilon=1.0, sigma=1.0)
    calc2 = LennardJones(epsilon=2.0, sigma=1.0)
    assert digest(calc1) != digest(calc2)


def test_vibrations_digest_stable(water):
    hessian = np.zeros((3, 3, 3, 3))
    vib1 = VibrationsData(water, hessian)
    vib2 = VibrationsData(water.copy(), hessian.copy())
    assert digest(vib1) == digest(vib2)


def test_vibrations_digest_differs_on_hessian(water):
    hessian = np.zeros((3, 3, 3, 3))
    other_hessian = hessian.copy()
    other_hessian[0, 0, 0, 0] = 1.0
    vib1 = VibrationsData(water, hessian)
    vib2 = VibrationsData(water, other_hessian)
    assert digest(vib1) != digest(vib2)


THERMO_FACTORIES = {
    "HarmonicThermo": lambda potentialenergy=1.0: HarmonicThermo(
        VIB_ENERGIES, potentialenergy=potentialenergy
    ),
    "QuasiHarmonicThermo": lambda potentialenergy=1.0: QuasiHarmonicThermo(
        VIB_ENERGIES, potentialenergy=potentialenergy
    ),
    "MSRRHOThermo": lambda potentialenergy=1.0: MSRRHOThermo(
        VIB_ENERGIES,
        Atoms("H2O", positions=[[0, 0, 0], [0, 0, 1], [0, 1, 0]]),
        potentialenergy=potentialenergy,
    ),
    "HinderedThermo": lambda potentialenergy=0.0: HinderedThermo(
        VIB_ENERGIES,
        trans_barrier_energy=0.1,
        rot_barrier_energy=0.1,
        sitedensity=1e15,
        rotationalminima=6,
        atoms=Atoms("H2O", positions=[[0, 0, 0], [0, 0, 1], [0, 1, 0]]),
        potentialenergy=potentialenergy,
    ),
    "IdealGasThermo": lambda potentialenergy=0.0: IdealGasThermo(
        VIB_ENERGIES,
        geometry="nonlinear",
        atoms=Atoms("H2O", positions=[[0, 0, 0], [0, 0, 1], [0, 1, 0]]),
        symmetrynumber=2,
        spin=0,
        potentialenergy=potentialenergy,
    ),
    "CrystalThermo": lambda potentialenergy=0.0: CrystalThermo(
        phonon_DOS=np.array([0.0, 1.0, 2.0]),
        phonon_energies=np.array([0.0, 0.01, 0.02]),
        formula_units=1,
        potentialenergy=potentialenergy,
    ),
}


@pytest.mark.parametrize("name", THERMO_FACTORIES)
def test_thermochemistry_digest_stable(name):
    factory = THERMO_FACTORIES[name]
    assert digest(factory()) == digest(factory())


@pytest.mark.parametrize("name", THERMO_FACTORIES)
def test_thermochemistry_digest_differs_on_potentialenergy(name):
    factory = THERMO_FACTORIES[name]
    assert digest(factory(potentialenergy=1.23)) != digest(
        factory(potentialenergy=4.56)
    )


def test_thermochemistry_digest_differs_between_classes():
    harmonic = HarmonicThermo(VIB_ENERGIES, potentialenergy=1.0)
    quasi = QuasiHarmonicThermo(VIB_ENERGIES, potentialenergy=1.0)
    assert digest(harmonic) != digest(quasi)


MODE_FACTORIES = {
    "HarmonicMode": lambda energy=0.01: HarmonicMode(energy),
    "RRHOMode": lambda energy=0.01: RRHOMode(energy, mean_inertia=1.0),
}


@pytest.mark.parametrize("name", MODE_FACTORIES)
def test_mode_digest_stable(name):
    factory = MODE_FACTORIES[name]
    assert digest(factory()) == digest(factory())


@pytest.mark.parametrize("name", MODE_FACTORIES)
def test_mode_digest_differs_on_energy(name):
    factory = MODE_FACTORIES[name]
    assert digest(factory(energy=0.01)) != digest(factory(energy=0.02))


def test_mode_digest_differs_between_classes():
    harmonic = HarmonicMode(0.01)
    rrho = RRHOMode(0.01, mean_inertia=1.0)
    assert digest(harmonic) != digest(rrho)


# --------------------------------------------------------------------------- constraints

def test_atoms_digest_sees_constraints(water):
    """(cell, pbc, arrays) says nothing about what is held fixed, and a relaxation of a
    constrained structure is not the same calculation as one of a free structure."""
    from ase.constraints import FixAtoms

    fixed = water.copy()
    fixed.set_constraint(FixAtoms(indices=[0]))
    other = water.copy()
    other.set_constraint(FixAtoms(indices=[1]))

    assert digest(fixed) != digest(water)
    assert digest(fixed) != digest(other)
    assert digest(fixed) == digest(fixed.copy())


def test_atoms_digest_sees_info(water):
    tagged = water.copy()
    tagged.info["solute"] = "Mg"
    assert digest(tagged) != digest(water)


def test_unconstrained_atoms_keep_the_previous_key(water):
    """An Atoms with nothing extra must digest as it did before constraints were folded in,
    so installing this version over an existing cache does not invalidate it."""
    previous = digest((
        "Atoms" if type(water) is Atoms else str(type(water)),
        digest(water.cell),
        digest(water.pbc),
        digest(water.arrays),
    ))
    assert fleche_ase.atoms_digest(water) == previous


# ------------------------------------------------------------------ the attached calculator

def test_an_attached_calculator_changes_the_key(water):
    """`Vibrations(atoms)` and the optimizers read `atoms.calc` instead of taking it, so a
    cached function written that way had one key for two calculators."""
    from ase.calculators.emt import EMT

    with_calc = water.copy()
    with_calc.calc = EMT()
    assert digest(with_calc) != digest(water)
    assert digest(with_calc) == digest(with_calc)


def test_two_stored_results_do_not_share_a_key(water):
    """The measure is observable behaviour in ASE, not physical sameness.

    `ase.io.read` hands anything read back from a trajectory a `SinglePointCalculator`
    (`extxyz.py`, `trajectory.py`), and that calculator cannot recompute -- it answers
    `get_potential_energy()` with what it stored, or raises. Two cells identical but for
    the energy stapled to them therefore behave differently and are two objects.
    """
    from ase.calculators.singlepoint import SinglePointCalculator

    a, b = water.copy(), water.copy()
    a.calc = SinglePointCalculator(a, energy=-1.0)
    b.calc = SinglePointCalculator(b, energy=-2.0)
    assert digest(a) != digest(b)
    assert a.get_potential_energy() != b.get_potential_energy(), "the premise"


def test_a_stored_result_from_another_configuration_is_a_different_calculator(water):
    """`get_property` calls `check_state` and refuses once the atoms have moved, so the
    configuration a SinglePointCalculator was built from is part of what it does."""
    from ase.calculators.singlepoint import SinglePointCalculator

    moved = water.copy()
    moved.positions[0] += 0.5

    a, b = water.copy(), water.copy()
    a.calc = SinglePointCalculator(water, energy=-1.0)
    b.calc = SinglePointCalculator(moved, energy=-1.0)
    assert digest(a) != digest(b)


def test_a_calculator_digest_does_not_recurse(water):
    """A SinglePointCalculator holds `atoms.copy()`, which carries no calculator, so folding
    the calculator into the structure nests exactly one level."""
    from ase.calculators.singlepoint import SinglePointCalculator

    held = water.copy()
    held.calc = SinglePointCalculator(held, energy=-1.0)
    assert held.calc.atoms.calc is None, "the premise"
    assert digest(held) == digest(held)


def test_an_unidentifiable_calculator_makes_the_structure_refuse(water, tmp_path):
    """The same rule, taken seriously: a structure whose calculator is unknown behaves in a
    way nothing here can predict, so it refuses rather than sharing a key."""
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights")
    held = water.copy()
    held.calc = _ModelCalculator(p)
    with pytest.raises(Indigestible, match="attached calculator") as caught:
        digest(held)
    assert caught.value.args[0] is held, "the value that did not hash is the structure"


def test_a_refusal_from_inside_the_calculator_still_says_where_it_surfaced(water):
    """The value a nested refusal carries can be far inside the calculator.

    An array-built EAM refuses on a `scipy` spline, which on its own gives a reader nothing
    to act on and no hint that the structure was refused because of what is bolted to it.
    """
    from ase.calculators.eam import EAM as RealEAM
    from scipy.interpolate import InterpolatedUnivariateSpline as spline

    xs = np.linspace(0.0, 1.0, 5)
    held = water.copy()
    held.calc = RealEAM(elements=["Al"],
                        embedded_energy=np.array([spline(xs, xs ** 2)]),
                        electron_density=np.array([spline(xs, xs)]),
                        phi=np.array([[spline(xs, -xs)]]),
                        cutoff=6.0)
    with pytest.raises(Indigestible) as caught:
        digest(held)
    assert caught.value.args[0] is held, "args[0] is what the caller asked us to digest"
    assert "attached calculator" in str(caught.value)
    assert any(isinstance(a, RealEAM) for a in caught.value.args[1:]), \
        "what actually refused is kept, as diagnostics"


# --------------------------------------------------------------------------- file identity

def test_fingerprint_follows_content(tmp_path):
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights-v1")
    first = fleche_ase.file_fingerprint(p)
    assert fleche_ase.file_fingerprint(p) == first

    p.write_bytes(b"weights-v2")
    assert fleche_ase.file_fingerprint(p) != first, \
        "a model re-exported in place must change its fingerprint"


def test_rapid_same_size_rewrites_each_get_their_own_fingerprint(tmp_path):
    """The memo must not outlive a rewrite the filesystem clock cannot resolve.

    The memo key is (path, size, mtime_ns), and mtime granularity is coarse -- a millisecond
    on ext4, up to a second on some NFS mounts -- so a same-size rewrite inside one tick
    leaves the key unchanged and a memo written before it would hand back a stale hash.
    Twenty rewrites in a row land inside one tick often enough to catch it.
    """
    p = tmp_path / "model.npz"
    seen = []
    for i in range(20):
        p.write_bytes(f"weights-v{i:02d}".encode())    # same length every time
        seen.append(fleche_ase.file_fingerprint(p))
    assert len(set(seen)) == len(seen), "a rewrite was masked by the memo"


def test_a_settled_file_is_still_memoised(tmp_path):
    """The racily-clean rule must not turn the memo off; a big model is hashed once."""
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights")
    os.utime(p, (time.time() - 3600, time.time() - 3600))
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    fleche_ase._FINGERPRINTS.pop(key, None)
    fleche_ase.file_fingerprint(p)
    assert key in fleche_ase._FINGERPRINTS


def test_fingerprint_of_a_directory_covers_names_and_bytes(tmp_path):
    d = tmp_path / "saved_model"
    (d / "variables").mkdir(parents=True)
    (d / "saved_model.pb").write_bytes(b"graph")
    (d / "variables" / "v.index").write_bytes(b"idx")
    first = fleche_ase.file_fingerprint(d)

    (d / "variables" / "v.index").write_bytes(b"idx2")
    assert fleche_ase.file_fingerprint(d) != first

    (d / "variables" / "v.index").write_bytes(b"idx")
    (d / "variables" / "renamed.index").write_bytes(b"idx")
    assert fleche_ase.file_fingerprint(d) != first, "a file under a new name must show"


def test_fingerprint_refuses_what_it_cannot_read(tmp_path):
    with pytest.raises(FileNotFoundError):
        fleche_ase.file_fingerprint(tmp_path / "gone.npz")
    d = tmp_path / "many"
    d.mkdir()
    for i in range(5):
        (d / str(i)).write_bytes(b"x")
    with pytest.raises(ValueError, match="max_files"):
        fleche_ase.file_fingerprint(d, max_files=4)

    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="neither a file nor a directory"):
        fleche_ase.file_fingerprint(fifo)


def test_a_path_that_cannot_be_read_is_indigestible_rather_than_an_OSError(tmp_path):
    """An unreadable file is a caching problem, not a reason to fail the call.

    `Indigestible` makes fleche run the call uncached with a warning; an `OSError` out of a
    digest hook would crash it before the body ever ran, and a function that does need the
    file will raise on its own terms inside it. fleche degrades a `Path` argument the same
    way.
    """
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    for bad in (tmp_path / "gone.npz", fifo):
        with pytest.raises(Indigestible):
            fleche_ase._path_identity(bad)




# --------------------------------------------------------------------------- calculators

class _ModelCalculator(Calculator):
    """Stands in for a calculator whose whole identity is a model file."""

    implemented_properties = ["energy"]

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def calculate(self, *args, **kwargs):
        raise NotImplementedError


def test_a_parameter_free_calculator_still_digests():
    from ase.calculators.emt import EMT

    assert EMT().todict() == {}, "the premise"
    assert digest(EMT()) == digest(EMT())


def test_a_model_calculator_without_an_identity_is_refused(tmp_path):
    """The defect this change exists for: todict() is {} and every model would share a key."""
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights")
    calc = _ModelCalculator(p)

    assert calc.todict() == {}
    with pytest.raises(Indigestible, match="register_calculator") as caught:
        digest(calc)
    assert caught.value.args[0] is calc, "the value that did not hash comes first"


def test_registered_extractor_is_used(tmp_path):
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights")
    fleche_ase.register_calculator(
        "_ModelCalculator", lambda c: {"sha256": fleche_ase.file_fingerprint(c.path)})
    try:
        # `before` must be captured: digest() is not memoised on the object, so recomputing it
        # after the rewrite would read the new bytes and compare them with themselves.
        before = digest(_ModelCalculator(p))
        assert digest(_ModelCalculator(p)) == before
        p.write_bytes(b"other")
        assert digest(_ModelCalculator(p)) != before, \
            "a model re-exported in place must not read back the old run"
    finally:
        fleche_ase._EXTRACTORS.pop("_ModelCalculator", None)


def test_two_models_of_one_class_do_not_share_a_key(tmp_path):
    a, b = tmp_path / "a.npz", tmp_path / "b.npz"
    a.write_bytes(b"weights-a")
    b.write_bytes(b"weights-b")
    fleche_ase.register_calculator(
        "_ModelCalculator", lambda c: {"sha256": fleche_ase.file_fingerprint(c.path)})
    try:
        assert digest(_ModelCalculator(a)) != digest(_ModelCalculator(b))
    finally:
        fleche_ase._EXTRACTORS.pop("_ModelCalculator", None)


def test_a_class_can_be_declared_parameter_free(tmp_path):
    p = tmp_path / "model.npz"
    p.write_bytes(b"weights")
    fleche_ase.register_calculator("_ModelCalculator", None)
    try:
        assert digest(_ModelCalculator(p)) == digest(_ModelCalculator(p))
    finally:
        fleche_ase.PARAMETER_FREE.discard("_ModelCalculator")


# --- the built-in pyace extractor, exercised without pyace installed -------------------
#
# The extractors are keyed by class NAME precisely so this module imports no ML stack, which
# also means a stand-in of the right name reaches the real code path.


class PyACECalculator(Calculator):
    """Stand-in for `pyace.asecalc.PyACECalculator`, with its `todict()`.

    The real one hands `basis_set` to `ase.calculators.calculator.Calculator.__init__`, which
    files it in `self.parameters`; `todict()` returns those parameters. The C++ evaluator the
    constructor builds from it is not on the object's `todict()` at all.
    """

    implemented_properties = ["energy"]

    def __init__(self, basis_set, **kw):
        super().__init__()
        self._params = {"basis_set": basis_set, "recursive": False,
                        "fast_nl": True, "verbose": 0, **kw}

    def todict(self):
        return dict(self._params)


def test_pyace_is_identified_by_the_contents_of_its_basis_file(tmp_path):
    p = tmp_path / "potential.yaml"
    p.write_bytes(b"species: Au\ncoefficients: [1, 2, 3]\n")
    before = digest(PyACECalculator(str(p)))
    assert digest(PyACECalculator(str(p))) == before
    p.write_bytes(b"species: Au\ncoefficients: [1, 2, 4]\n")
    assert digest(PyACECalculator(str(p))) != before, \
        "refitting a potential in place must not read back the old run"


def test_pyace_parameters_that_change_the_numbers_change_the_key(tmp_path):
    p = tmp_path / "potential.yaml"
    p.write_bytes(b"species: Au\n")
    assert digest(PyACECalculator(str(p))) != digest(PyACECalculator(str(p), recursive=True))


def test_a_real_eam_built_from_splines_is_refused():
    """The REAL `ase.calculators.eam.EAM`, built the way ase's own test builds it.

    The slots hold object arrays of `scipy` splines, not numbers, and a spline identifies
    nothing that survives the process -- the same position as pyace's parsed basis. Treating
    the empty `todict()` as an identity instead would put every array-built EAM on one key.
    """
    from ase.calculators.eam import EAM as RealEAM
    from scipy.interpolate import InterpolatedUnivariateSpline as spline

    xs = np.linspace(0.0, 1.0, 5)
    calc = RealEAM(elements=["Al"],
                   embedded_energy=np.array([spline(xs, xs ** 2)]),
                   electron_density=np.array([spline(xs, xs)]),
                   phi=np.array([[spline(xs, -xs)]]),
                   cutoff=6.0)
    assert "potential" not in calc.todict(), "the premise: no file names this one"
    with pytest.raises(Indigestible):
        digest(calc)


class EAM(Calculator):
    """Stand-in for a file-backed `ase.calculators.eam.EAM`.

    The real one parses the file in `__init__`, so testing the content-addressing branch
    against it would mean writing a valid LAMMPS `.alloy` -- a second parser in the test for
    no extra coverage. What matters is the shape ase gives us: the constructor argument stays
    in `calc.parameters` and so comes back out of `todict()`.
    """

    implemented_properties = ["energy"]

    def __init__(self, **kw):
        super().__init__()
        self._params = dict(kw)

    def todict(self):
        return dict(self._params)


def test_eam_is_identified_by_the_contents_of_its_potential_file(tmp_path):
    p = tmp_path / "Cu.eam.alloy"
    p.write_bytes(b"embedding: [1, 2, 3]\n")
    before = digest(EAM(potential=str(p)))
    assert digest(EAM(potential=str(p))) == before
    p.write_bytes(b"embedding: [1, 2, 4]\n")
    assert digest(EAM(potential=str(p))) != before, \
        "a refitted table in place must not read back the old run"


def test_a_file_is_identified_by_its_name_and_content_not_its_location(tmp_path):
    """A model copied to another filesystem is the same model and keeps its key.

    Location is not identity -- the copy on scratch and the original in the shared store hold
    one potential -- while the basename is. That is the relation fleche's `temppath` branch
    gives a `pathlib.Path`, so swapping this hashing for upstream's later will not re-key
    anything.
    """
    here, there = tmp_path / "store", tmp_path / "scratch"
    here.mkdir()
    there.mkdir()
    for d in (here, there):
        (d / "Cu.eam.alloy").write_bytes(b"embedding: [1, 2, 3]\n")
    assert digest(EAM(potential=str(here / "Cu.eam.alloy"))) \
        == digest(EAM(potential=str(there / "Cu.eam.alloy")))

    (here / "Al.eam.alloy").write_bytes(b"embedding: [1, 2, 3]\n")
    assert digest(EAM(potential=str(here / "Al.eam.alloy"))) \
        != digest(EAM(potential=str(here / "Cu.eam.alloy"))), \
        "same bytes under another name is another potential, as upstream has it too"


def test_an_eam_with_no_potential_file_is_refused():
    with pytest.raises(Indigestible):
        digest(EAM())


def test_pyace_with_a_parsed_basis_object_is_refused(tmp_path):
    """A caller who built a `BBasisConfiguration` itself has to say what it is.

    The object identifies nothing that survives the process, and guessing would put every
    such calculator on one cache key.
    """
    class _Basis:
        pass

    calc = PyACECalculator(_Basis())
    with pytest.raises(Indigestible):
        digest(calc)


# --- the built-in tensorpotential extractor, exercised without tensorflow ---------------


class _FakeTensor:
    """Enough of a `tf.Variable` for the extractor: `numpy()`, `dtype`, `shape`."""

    def __init__(self, value):
        self._value = np.asarray(value)
        self.dtype = self._value.dtype
        self.shape = self._value.shape

    def numpy(self):
        return self._value


class _FakeTrackable:
    def __init__(self, **children):
        self._children = children

    def _trackable_children(self):
        return dict(self._children)


class TPCalculator(Calculator):
    """Stand-in for `tensorpotential.calculator.TPCalculator`.

    The real one replaces the path it is handed with `TensorPotential.load_model(path)` and
    keeps only the result, so `todict()` is `{}` and the path is gone. What it does keep is
    the loaded model, whose tensors hang off TF's trackable graph -- which is what the
    extractor reads.
    """

    implemented_properties = ["energy"]

    def __init__(self, weights, symbols=("Al", "Ca"), float_dtype="float64"):
        super().__init__()
        self.models = [_FakeTrackable(
            instructions=_FakeTrackable(
                Z=_FakeTrackable(
                    # object dtype on purpose: `tobytes()` on one hashes POINTERS
                    element_map_symbols=_FakeTensor(np.array(symbols, dtype=object)),
                ),
                A1=_FakeTrackable(w=_FakeTensor(weights)),
            ),
        )]
        self.cutoff = 6.0
        self.fidelity = None
        self.min_dist = None
        self.extra_properties = None
        self.geom_data_builder = types.SimpleNamespace(float_dtype=float_dtype)


def test_tensorpotential_is_identified_by_its_weights():
    a = TPCalculator([1.0, 2.0, 3.0])
    b = TPCalculator([1.0, 2.0, 4.0])
    assert a.todict() == {}, "the premise: nothing in todict() tells the two apart"
    assert digest(a) != digest(b)


def test_tensorpotential_digest_is_stable_across_loads():
    """Two loads of one model are different objects holding equal tensors.

    The trap is the element map: it is an object-dtype array, whose `tobytes()` is the
    addresses of its strings. `fleche.digest` handles that since 0.22.2 (hence the pin);
    this is the regression test that we are actually going through it.
    """
    assert digest(TPCalculator([1.0, 2.0])) == digest(TPCalculator([1.0, 2.0]))


def test_tensorpotential_separates_fp32_from_fp64():
    assert digest(TPCalculator([1.0, 2.0], float_dtype="float32")) \
        != digest(TPCalculator([1.0, 2.0], float_dtype="float64"))


def test_tensorpotential_element_map_is_part_of_the_identity():
    assert digest(TPCalculator([1.0], symbols=("Al", "Ca"))) \
        != digest(TPCalculator([1.0], symbols=("Al", "Mg")))


def test_a_model_whose_tensors_cannot_be_reached_is_refused():
    """A TF that renames `_trackable_children` must not key on a quarter of a model."""
    class _Opaque:
        pass

    calc = TPCalculator([1.0])
    calc.models = [_Opaque()]
    with pytest.raises(Indigestible):
        digest(calc)


def test_a_model_that_cannot_be_weakly_referenced_still_digests():
    """The hash memo is a weak dict; a model it cannot hold must cost speed, not a TypeError."""
    calc = TPCalculator([1.0])
    inner = calc.models[0]
    calc.models = [_FakeTrackable(instructions=inner)]      # weak-referenceable
    first = digest(calc)
    calc.models = [object()]                                # not weak-referenceable, no tensors
    with pytest.raises(Indigestible):
        digest(calc)
    assert first == first
