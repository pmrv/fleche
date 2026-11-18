# Changelog

## [1.1.0](https://github.com/pmrv/fleche/compare/fleche-numpy-1.0.0...fleche-numpy-1.1.0) (2026-11-18)


### Features

* **storage:** ChildItems, a destructure entry point, and object arrays destructured by fleche-numpy ([#1074](https://github.com/pmrv/fleche/issues/1074)) ([d13095c](https://github.com/pmrv/fleche/commit/d13095c0e3e031354263c2b0b2a1c89e6e9ceb20))
* **storage:** sister packages declare their types as depth-0 leaves ([#1083](https://github.com/pmrv/fleche/issues/1083)) ([644c64f](https://github.com/pmrv/fleche/commit/644c64f45e0031bf2d31ad934506a82d3395a5b3))

## 1.0.0 (2026-11-16)


### ⚠ BREAKING CHANGES

* **digest:** digesting numpy arrays, np.bool_, np.timedelta64 or pandas objects requires fleche-numpy / fleche-pandas (the fleche[numpy] and fleche[pandas] extras). A type with both __digest__ and an entry-point hook digests by __digest__. fleche._hashing is renamed fleche.hashing.

### Features

* **digest:** move numpy and pandas digests into sister packages ([#1058](https://github.com/pmrv/fleche/issues/1058)) ([4aaebce](https://github.com/pmrv/fleche/commit/4aaebcedfd19d398a082427d88bc135b423314e5))
