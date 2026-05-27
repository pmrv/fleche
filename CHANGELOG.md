# Changelog

## [0.14.0](https://github.com/pmrv/fleche/compare/0.13.1...0.14.0) (2026-05-27)


### Features

* **config:** walk CWD→HOME and merge fleche.toml files ([#553](https://github.com/pmrv/fleche/issues/553)) ([c3f3d20](https://github.com/pmrv/fleche/commit/c3f3d2014ad3c78e4af5503f8ad35e4fb8eeb99a))
* **metadata:** add Environment and Git metadata ([#565](https://github.com/pmrv/fleche/issues/565)) ([c671895](https://github.com/pmrv/fleche/commit/c67189557293558d9f29dcdcaae926f88e3dbcf0))
* **metadata:** add Version metadata capturing fleche version ([a813391](https://github.com/pmrv/fleche/commit/a813391c242eab32c68c9dc7c91c1696de0675a7))
* **metadata:** also record python_version in Environment ([e44a759](https://github.com/pmrv/fleche/commit/e44a7599a78b4cf74ce900103b35b775a03d6322))
* **query:** add QueryIterator.transfer for replaying matches into a target cache ([#566](https://github.com/pmrv/fleche/issues/566)) ([b3d60dc](https://github.com/pmrv/fleche/commit/b3d60dcb57422b212c455c060286791748a0ff24))
* **query:** shrink lookup keys in QueryIterator.table by default ([ce44ebb](https://github.com/pmrv/fleche/commit/ce44ebb76866bef8389bbfe40c93add44d777d25))


### Bug Fixes

* **call:** fall back to permissive signature for un-introspectable builtins ([#559](https://github.com/pmrv/fleche/issues/559)) ([d7bd30d](https://github.com/pmrv/fleche/commit/d7bd30d336080feacdc9355348bd27488c3f0149))
* **config:** default XDG_CONFIG_HOME to ~/.config per spec ([56fb9a9](https://github.com/pmrv/fleche/commit/56fb9a99f424bd79ff0a49e9723fc4e9b013a14d))
* rename put() parameter call→value to match parent class signature ([#546](https://github.com/pmrv/fleche/issues/546)) ([1f8b822](https://github.com/pmrv/fleche/commit/1f8b82288ff8234502c77edd61df0023b0663525))
* **sql:** handle legacy INTEGER version column on load ([#578](https://github.com/pmrv/fleche/issues/578)) ([1040f0d](https://github.com/pmrv/fleche/commit/1040f0d7cdc188de0af161cd18bcc2d2930bf15e))
* **types:** satisfy ty after variadic shrink ([fe7245a](https://github.com/pmrv/fleche/commit/fe7245a35674f81f983bc28a15586ce580c399a9))


### Performance Improvements

* **caches:** batch shrink via shrink(*keys) variadic API ([c9e64c4](https://github.com/pmrv/fleche/commit/c9e64c4aea00a54c9e86752ba3a291784dda5786))
* **sql:** replace ORM-materialised _evict with bulk DELETE ([#535](https://github.com/pmrv/fleche/issues/535)) ([e0eca8f](https://github.com/pmrv/fleche/commit/e0eca8f3e83a37a4dfeddb588605c8a84fc0f61b))
