"""fleche digest hooks for ASE objects.

Importing this package is all that is needed: :data:`digest_hooks` is published through
fleche's ``fleche`` entry point, so ``Atoms``, ``Calculator``, ``VibrationsData`` and the
``ase.thermochemistry`` classes become digestible arguments of any cached function.

Each hook documents its own rules; :func:`calculator_digest` is the one with a policy
worth reading before using it.
"""

import hashlib
import os
import time
import weakref
from pathlib import Path

import numpy

from ase import Atoms
from ase.calculators.calculator import Calculator
from ase.thermochemistry import AbstractMode, BaseThermoChem
from ase.vibrations import VibrationsData
from fleche.digest import Indigestible, digest, Digest

__all__ = ["atoms_digest", "calculator_digest", "vibrations_digest",
           "thermo_mode_digest", "thermochemistry_digest",
           "file_fingerprint", "register_calculator",
           "digest_hooks", "PARAMETER_FREE"]

#: Calculator class names whose empty ``todict()`` is the truth rather than a gap. Names, not
#: classes, so that nothing here imports a calculator backend. Extend it through
#: :func:`register_calculator` with ``extractor=None``.
PARAMETER_FREE = {"EMT", "LennardJones", "MorsePotential", "TIP3P", "TIP4P"}

_EXTRACTORS = {}
_FINGERPRINTS = {}
_MODEL_DIGEST = weakref.WeakKeyDictionary()
_BLOCK = 1 << 20
#: How deep :func:`_saved_model_tensors` follows TF's restore graph. GRACE's deepest tensor
#: sits at 3; the bound is there so a cyclic or pathological graph cannot hang a digest.
_TRACKABLE_DEPTH = 8


def _hash_file(path, m):
    with open(path, "rb") as fh:
        while chunk := fh.read(_BLOCK):
            m.update(chunk)


#: An mtime younger than this is not trusted to have settled.
_RACE_WINDOW_NS = 2_000_000_000


def file_fingerprint(path, max_files: int = 20000) -> str:
    """SHA-256 of a file's bytes, or of a directory's (relative path, bytes) listing.

    Memoised on ``(realpath, size, mtime_ns)`` -- for a directory, on the file count, the
    summed size and the newest mtime, so a reused model costs one ``stat`` per file rather
    than a reread. A hash whose mtime is younger than `_RACE_WINDOW_NS` is returned but not
    remembered: mtime granularity runs to a second on some NFS mounts, so a same-size rewrite
    inside one tick would leave the memo key unchanged and hand back the previous model's
    hash. Git skips its "racily clean" index entries for the same reason.

    Raises ``FileNotFoundError`` for a missing path and ``ValueError`` above *max_files*.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"cannot fingerprint {p}: does not exist")

    if p.is_file():
        st = p.stat()
        key, newest = (str(p), st.st_size, st.st_mtime_ns), st.st_mtime_ns

        def compute():
            m = hashlib.sha256()
            _hash_file(p, m)
            return m.hexdigest()
    else:
        files = sorted(f for f in p.rglob("*") if f.is_file())
        if len(files) > max_files:
            raise ValueError(f"cannot fingerprint {p}: {len(files)} files exceeds "
                             f"max_files={max_files}")
        stats = [f.stat() for f in files]
        newest = max((s.st_mtime_ns for s in stats), default=0)
        key = (str(p), len(files), sum(s.st_size for s in stats), newest)

        def compute():
            m = hashlib.sha256()
            for f in files:
                m.update(str(f.relative_to(p)).encode())
                m.update(b"\0")
                _hash_file(f, m)
            return m.hexdigest()

    hit = _FINGERPRINTS.get(key)
    if hit is not None:
        return hit
    value = compute()
    if time.time_ns() - newest > _RACE_WINDOW_NS:
        _FINGERPRINTS[key] = value
    return value


def register_calculator(class_name: str, extractor=None) -> None:
    """Teach :func:`calculator_digest` about a calculator class, by NAME.

    *extractor* takes the calculator and returns anything fleche can digest. ``extractor=None``
    instead declares the class parameter-free, i.e. that an empty ``todict()`` is its real
    identity.

    Matching walks the MRO by class name, so a subclass is covered by its parent's
    registration and nothing here has to import a backend.
    """
    if extractor is None:
        PARAMETER_FREE.add(class_name)
    else:
        _EXTRACTORS[class_name] = extractor


def _grace_runtime(calc):
    # grace_runtime.Model keeps `path`; the npz is the whole model, weights included, so its
    # bytes are the identity. uq and dispersion change the numbers, not just the speed.
    path = calc.model.path
    return {"model_path": str(Path(path).resolve()),
            "model_sha256": file_fingerprint(path),
            "uq": bool(getattr(calc, "uq_enabled", False)),
            "dispersion": repr(getattr(calc, "dispersion", None))}


def _file_backed(calc, key: str, label: str = "potential"):
    """``todict()``, with *key* replaced by the CONTENTS of the file it names.

    The pattern both pyace and EAM follow: the constructor parses a potential file into
    something in memory, and ase keeps the constructor ARGUMENT in ``calc.parameters``, so
    ``todict()`` still carries it. A path is not an identity -- refitting a potential in
    place leaves the key unchanged and every value stale -- so the file is hashed. The same
    argument also accepts an object the caller built itself, which identifies nothing that
    survives the process, and that is refused. The rest of ``todict()`` rides along: for
    pyace, ``recursive``, ``fast_nl`` and the gamma bounds all change the numbers.
    """
    try:
        params = dict(calc.todict())
    except Exception as e:                                             # noqa: BLE001
        raise _indigestible(calc, f"todict() raised {type(e).__name__}: {e}") from None
    value = params.pop(key, None)
    if isinstance(value, (str, os.PathLike)) and Path(value).exists():
        return {label: str(Path(value).resolve()),
                "sha256": file_fingerprint(value), **params}
    raise _indigestible(
        calc, f"its {key} is an in-memory object, not a file this process can hash")


def _pyace(calc):
    return _file_backed(calc, "basis_set")


def _eam(calc):
    """``EAM`` was in :data:`PARAMETER_FREE`, which was wrong.

    ``EAM(potential='Cu.eam.alloy')`` keeps that path in ``parameters``, so ``todict()`` is
    not empty and it never reached the parameter-free tier in practice. Built the other way
    it does not have a path at all: ase's own test constructs one as
    ``EAM(elements=['Al'], embedded_energy=np.array([spline(...)]), ...)``, i.e. object arrays
    of ``scipy`` splines. Those identify nothing that survives the process -- the same
    position as pyace's parsed basis -- so it refuses. Declaring the class parameter-free
    instead said the empty dict was its identity, when the empty dict is the gap.
    """
    return _file_backed(calc, "potential")


def _saved_model_tensors(model):
    """Every tensor hanging off a loaded SavedModel, as ``(dotted name, tensor)``, sorted.

    ``_trackable_children()`` is TF's own restore graph -- the structure that put the values
    back when the model was loaded -- so walking it reaches the weights, the element map and
    the ZBL table alike. It is private, hence the defensive ``except``: a TF that renames it
    yields nothing here, the extractor raises, and fleche refuses rather than keys on a
    quarter of a model.
    """
    found, seen = [], set()

    def walk(obj, path):
        if id(obj) in seen or len(path) > _TRACKABLE_DEPTH:
            return
        seen.add(id(obj))
        try:
            children = obj._trackable_children()
        except Exception:                                              # noqa: BLE001
            return
        for name, child in children.items():
            here = path + (str(name),)
            if hasattr(child, "numpy") and hasattr(child, "dtype"):
                found.append((".".join(here), child))
            walk(child, here)

    walk(model, ())
    return sorted(found, key=lambda kv: kv[0])


def _tensor_digest(model) -> Digest:
    """Digest of every tensor under *model*, one array at a time.

    `fleche.digest` does the arrays, including the dtype, the shape and -- since 0.22.2 --
    an object-dtype array by value rather than by the addresses `tobytes()` would return.
    The element map is such an array, so before that fix the same model digested differently
    on every load; it is why this package requires that version.
    """
    tensors = _saved_model_tensors(model)
    if not tensors:
        raise Indigestible(model, "no tensors are reachable through _trackable_children()")
    # One at a time: `tensor.numpy()` copies, and a GRACE model is ~150 MB of float64.
    return digest(tuple((name, digest(numpy.asarray(t.numpy()))) for name, t in tensors))


def _model_digest(model) -> Digest:
    """:func:`_tensor_digest`, memoised weakly so a dropped model does not keep its digest."""
    try:
        hit = _MODEL_DIGEST.get(model)
    except TypeError:           # not weak-referenceable: correctness first, pay the rehash
        return _tensor_digest(model)
    if hit is None:
        hit = _MODEL_DIGEST[model] = _tensor_digest(model)
    return hit


def _tensorpotential(calc):
    """`TPCalculator` replaces the path it was given with the loaded model, so hash the model.

    ``__init__`` does ``model = TensorPotential.load_model(model)`` and keeps only the result:
    the path is not on the calculator, not on the loaded object, and ``todict()`` is ``{}``.
    The tensors are on it, though, and they are a better identity than the path ever was --
    an fp32 re-export of the same training run lands on its own key without anyone saying so.

    Digesting is memoised per loaded model (~0.5 s for a 9 M-parameter GRACE model), weakly
    so that a model dropped by the caller does not keep its digest alive.
    """
    models = [_model_digest(model) for model in calc.models]
    builder = getattr(calc, "geom_data_builder", None)
    return {
        "models": models,
        # a numpy scalar, so float() keeps the key off numpy's repr
        "cutoff": None if calc.cutoff is None else float(calc.cutoff),
        "fidelity": getattr(calc, "fidelity", None),
        "min_dist": getattr(calc, "min_dist", None),
        "extra_properties": getattr(calc, "extra_properties", None),
        # fp32 and fp64 inference off one model are different numbers.
        "float_dtype": str(getattr(builder, "float_dtype", None)),
    }


def _single_point(calc):
    """A ``SinglePointCalculator`` IS its stored results; it cannot compute anything else.

    That is what separates it from a real calculator, whose cached ``results`` need not be
    digested because it would recompute the same numbers. This one would raise instead, so
    two of them holding different energies behave differently and must not share a key.

    ``get_property`` also calls ``check_state``, refusing when the atoms it is asked about
    have moved away from the configuration it was built from -- so that configuration is part
    of the identity too. ``__init__`` stores ``atoms.copy()``, which carries no calculator of
    its own, so this nests exactly one level and cannot recurse.
    """
    identity = {"results": calc.results, "atoms": atoms_digest(calc.atoms)}
    # SinglePointDFTCalculator reaches this through the MRO, and its extras are observable
    # through get_fermi_level() and friends.
    for attr in ("eFermi", "bz_kpts", "ibz_kpts", "bz2ibz"):
        if hasattr(calc, attr):
            identity[attr] = getattr(calc, attr)
    kpts = getattr(calc, "kpts", None)
    if kpts is not None:
        identity["kpts"] = [(k.weight, k.s, k.k, k.eps_n, k.f_n) for k in kpts]
    return identity


# Known model-backed calculators, keyed by class NAME so that importing this module pulls in
# no machine-learning stack. Anything else goes through register_calculator() at the call site.
register_calculator("GRACERuntimeCalculator", _grace_runtime)
register_calculator("PyACECalculator", _pyace)
register_calculator("TPCalculator", _tensorpotential)
register_calculator("SinglePointCalculator", _single_point)
register_calculator("EAM", _eam)


def _indigestible(value, why: str) -> Indigestible:
    # `args[0]` is the value that did not hash, as fleche raises it everywhere; the message
    # follows as diagnostics.
    return Indigestible(
        value,
        f"{why}; register_calculator({type(value).__name__!r}, extractor) "
        f"to say what identifies it.")


def _constraint_digest(con) -> Digest:
    try:
        return digest(con.todict())
    except AttributeError:
        raise Indigestible(con) from None


def atoms_digest(structure: Atoms) -> Digest:
    """Cell, pbc and arrays, plus ``constraints`` and ``info`` when either is non-empty.

    ``FixAtoms([0, 1])`` used to digest to nothing, so a constrained and an unconstrained
    relaxation of one cell shared a key. ``structure.calc`` is in for the same reason:
    ``Vibrations(atoms)`` and the optimizers take the calculator off the structure rather
    than as an argument, so without it one key covered two calculators.

    THE TEST IS OBSERVABLE BEHAVIOUR IN ASE, not physical sameness. Two cells that are
    identical but for an attached calculator answer ``get_potential_energy()`` differently,
    so they are two objects and get two keys -- including the common case of a structure read
    back from a trajectory, which ``ase.io.read`` hands a ``SinglePointCalculator``. The
    consequence of the same rule is that an ``Atoms`` whose calculator cannot be identified
    now refuses: its behaviour genuinely is unknown. See fleche-ase#4.
    """
    parts = [
        "Atoms" if type(structure) is Atoms else str(type(structure)),
        digest(structure.cell),
        digest(structure.pbc),
        digest(structure.arrays),
    ]
    # Conditional so an unconstrained Atoms keeps the key it had before this change and
    # existing caches stay valid.
    if len(structure.constraints):
        parts.append(("constraints",
                      tuple(_constraint_digest(c) for c in structure.constraints)))
    if structure.info:
        parts.append(("info", digest(structure.info)))
    if structure.calc is not None:
        try:
            parts.append(("calc", digest(structure.calc)))
        except Indigestible as exc:
            # The value that is not hashing, as far as the caller is concerned, is the
            # STRUCTURE: that is what it handed over, so that is `args[0]`, as everywhere
            # else. What came back can be something far inside the calculator -- a scipy
            # spline, say -- which is diagnostics, and follows.
            raise Indigestible(structure,
                               "its attached calculator cannot be digested",
                               *exc.args) from exc
    return digest(tuple(parts))


def vibrations_digest(vibrations: VibrationsData) -> Digest:
    return digest((
        "VibrationsData",
        digest(vibrations.get_atoms()),
        digest(vibrations.get_indices()),
        digest(vibrations.get_hessian_2d()),
    ))


def calculator_digest(calc: Calculator) -> Digest:
    """Identity of a calculator, refusing to guess rather than share a key.

    ``todict()`` is a serialisation contract for calculators whose parameters *are* their
    definition, and a model-backed calculator breaks it silently: an empty dict is both a
    valid answer and what "no idea" looks like. ``GRACERuntimeCalculator.todict()`` returns
    ``{}`` for a 75 MB model, so under a hook that trusted it every model shared one key.

    Identity is therefore resolved in three tiers -- an extractor registered for the class
    with :func:`register_calculator`, a non-empty ``todict()``, then an empty one on a class
    listed in :data:`PARAMETER_FREE` -- and anything else raises ``Indigestible``, which makes
    fleche run the call uncached with a warning. A slow run is recoverable; a cache hit for a
    different model is not.
    """
    for cls in type(calc).__mro__:
        if cls.__name__ in _EXTRACTORS:
            return digest((cls.__name__, "extractor", _EXTRACTORS[cls.__name__](calc)))

    try:
        params = calc.todict()
    except Exception as e:                                           # noqa: BLE001
        raise _indigestible(calc, f"todict() raised {type(e).__name__}: {e}") from None

    if params:
        return digest((type(calc).__name__, "todict", params))

    if any(cls.__name__ in PARAMETER_FREE for cls in type(calc).__mro__):
        return digest((type(calc).__name__, "parameter-free"))

    raise _indigestible(calc, "todict() is empty and nothing identifies it")


def thermo_mode_digest(mode: AbstractMode) -> Digest:
    return digest((
        type(mode).__name__,
        vars(mode),
    ))


def thermochemistry_digest(thermo: BaseThermoChem) -> Digest:
    return digest((
        type(thermo).__name__,
        vars(thermo),
    ))


digest_hooks = [
        (Atoms, atoms_digest),
        (VibrationsData, vibrations_digest),
        (Calculator, calculator_digest),
        (AbstractMode, thermo_mode_digest),
        (BaseThermoChem, thermochemistry_digest),
]
