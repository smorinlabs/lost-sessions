# Changelog

## [0.3.2](https://github.com/smorinlabs/lost-sessions/compare/v0.3.1...v0.3.2) (2026-11-24)


### Dependencies

* **deps-dev:** bump import-linter from 2.15 to 2.17 ([45e1cb1](https://github.com/smorinlabs/lost-sessions/commit/45e1cb1f9170b586bd8a4e056a86689d2f0058aa))
* **deps-dev:** bump sphinx-autodoc-typehints from 3.13.8 to 3.17.6 ([5ea3b1f](https://github.com/smorinlabs/lost-sessions/commit/5ea3b1f0526fb0db73b194f3a31b56f6de99eb02))
* **deps-dev:** bump the lint-and-format group across 1 directory with 3 updates ([14255c1](https://github.com/smorinlabs/lost-sessions/commit/14255c160024775e2a4af084d175f4bd80798fc3))
* **deps-dev:** bump the test group across 1 directory with 2 updates ([f74588a](https://github.com/smorinlabs/lost-sessions/commit/f74588a78ad8362e074bda6d497e0307b15dc0be))
* **deps:** bump pluggy from 1.6.0 to 1.7.0 ([8deb0ff](https://github.com/smorinlabs/lost-sessions/commit/8deb0ff50eb93d9b4aa4148fcc99849ac1a9c3b8))
* **deps:** bump the github-actions group across 1 directory with 3 updates ([9a8f2ef](https://github.com/smorinlabs/lost-sessions/commit/9a8f2effdc7376f7dc3a954a091aa59b344af92b))

## [0.3.1](https://github.com/smorinlabs/lost-sessions/compare/v0.3.0...v0.3.1) (2026-11-24)


### Bug Fixes

* **ci:** allow muse reviews to complete ([8900c02](https://github.com/smorinlabs/lost-sessions/commit/8900c02bb28aa1e4752d4a28d41780357c61651c))
* **ci:** guard audit triage retries and url checks ([4351bc7](https://github.com/smorinlabs/lost-sessions/commit/4351bc708ecc25ed1c851b3b4c8f3a610c9bf18e))
* **ci:** publish completed muse responses ([bd16657](https://github.com/smorinlabs/lost-sessions/commit/bd16657f14a510ec5ccc65531d6283d3bb114269))
* **ci:** update muse pilot review safeguards ([cad0c05](https://github.com/smorinlabs/lost-sessions/commit/cad0c05270967803e4b021d8e8dd180c2b488e08))

## [0.3.0](https://github.com/smorinlabs/lost-sessions/compare/v0.2.1...v0.3.0) (2026-11-15)


### Features

* **evidence:** add optional session evidence storage ([dc4be6d](https://github.com/smorinlabs/lost-sessions/commit/dc4be6d2d0ce57536798c33315f6a690585e2b00))
* **evidence:** add optional session records and companion skill ([4cea44d](https://github.com/smorinlabs/lost-sessions/commit/4cea44d76725bbde695441d82e07d09a975030aa))
* **evidence:** expose optional evidence commands ([810e7ce](https://github.com/smorinlabs/lost-sessions/commit/810e7ce4628611027efb4d3ad566608a4a366b9e))


### Bug Fixes

* **evidence:** correlate the latest ending with its opening ([086f6ed](https://github.com/smorinlabs/lost-sessions/commit/086f6edb49b79c1a02aea15f46639d2a62c05f7e))
* **evidence:** enforce receipt size and compact json errors ([8e5ea0d](https://github.com/smorinlabs/lost-sessions/commit/8e5ea0da02903fb438aa183218ac3fceecc93562))
* **evidence:** handle empty stores and ignored hook payloads ([d7f68be](https://github.com/smorinlabs/lost-sessions/commit/d7f68becdfc2cb448e124a885143ea0118c6d84a))
* **evidence:** support plugin checkouts without symlinks ([3821135](https://github.com/smorinlabs/lost-sessions/commit/38211356addb9b2f4304a844b4af2335e765bb23))
* **evidence:** tolerate writer contention across platforms ([d73a3cc](https://github.com/smorinlabs/lost-sessions/commit/d73a3cc72f3be9aa254b6d0ea54b39dd2f9b8717))
* **rex:** run the shell fallback under a Bourne-family shell ([8e31a91](https://github.com/smorinlabs/lost-sessions/commit/8e31a918647d55e34724c3ef1e1adcbdc62ab05f))
* **rex:** tabs fall back to a shell prompt when the agent exits ([5cd47aa](https://github.com/smorinlabs/lost-sessions/commit/5cd47aa44893ee75860f546b5ae6daf96ba8e40c))

## [0.2.1](https://github.com/smorinlabs/lost-sessions/compare/v0.2.0...v0.2.1) (2026-11-14)


### Dependencies

* **deps:** bump the github-actions group across 1 directory with 2 updates ([07d355e](https://github.com/smorinlabs/lost-sessions/commit/07d355ee5ba13c19a6428b114c3d8e35abd76102))
* **deps:** bump the runtime group across 1 directory with 2 updates ([e5b0fc4](https://github.com/smorinlabs/lost-sessions/commit/e5b0fc4af26094849849f7d299f29f4eed9b96a3))

## [0.2.0](https://github.com/smorinlabs/lost-sessions/compare/v0.1.0...v0.2.0) (2026-11-14)


### Features

* add list, open --print and history on the plugin core ([c2b4676](https://github.com/smorinlabs/lost-sessions/commit/c2b4676ba9704560b87ec6a2e3c60974f1a8e3a8))
* add plugins, install and uninstall ([3a0625f](https://github.com/smorinlabs/lost-sessions/commit/3a0625fb088a34943e831ff4e0570a26c3f7a82a))
* add the four agent plugins and the inventory command ([2980768](https://github.com/smorinlabs/lost-sessions/commit/298076801a6ab330ad6378425338e0428f791776))
* add the plugin manager, hookspecs and cli factory ([c769509](https://github.com/smorinlabs/lost-sessions/commit/c769509f9d70dbc4758861114b6a6df20169a20e))
* add the recover menu and a plugin contract suite ([26bb54d](https://github.com/smorinlabs/lost-sessions/commit/26bb54d96c6336d9dbbf793a97019d3a906cb467))
* open sessions in herdr and rex through manager plugins ([890f09a](https://github.com/smorinlabs/lost-sessions/commit/890f09ab58ed78f47e92abafb73cac418ebfcf13))


### Bug Fixes

* harden plugin loading against repeated entries and record discovered distributions ([d23c093](https://github.com/smorinlabs/lost-sessions/commit/d23c09359806b492e812ec7b0735c7320375d8e2))
* keep malformed stores and a missing process table from crashing the inventory ([9b76d6f](https://github.com/smorinlabs/lost-sessions/commit/9b76d6f73e1af72839c389d4e593b7c9c1d7b0ab))
* keep subdirectory fragments and let a requested plugin replace its old source ([72436bd](https://github.com/smorinlabs/lost-sessions/commit/72436bd8a935b4ed6d048b026a4e0a79545c259a))
* keep third-party managers and odd responses from breaking open ([c1561f1](https://github.com/smorinlabs/lost-sessions/commit/c1561f156d01b277a15b1c5baf717b5088f986ee))
* leave a manager without a menu key out of the recover menu ([d69795d](https://github.com/smorinlabs/lost-sessions/commit/d69795d12e7347029f839d321b5fbe14c5cfdce3))
* read compact name@url specs and warn that extras are dropped on reinstall ([362f0e4](https://github.com/smorinlabs/lost-sessions/commit/362f0e417fbe5ad86dc3af52749881c05837a348))
* read process command lines in full on linux ([a1fe64e](https://github.com/smorinlabs/lost-sessions/commit/a1fe64e9d760cfc85427816deb33724ea22a5edc))
* refresh restore status before running menu choices; isolate the contract suite ([412d120](https://github.com/smorinlabs/lost-sessions/commit/412d12055e4ee4c73dbd48b62bfc6f4f08b8784f))
* thread the plugin manager through core and harden stored-data reads ([90fc2a6](https://github.com/smorinlabs/lost-sessions/commit/90fc2a64424c2c42c67d70d02de29f4c6ffd5e2f))


### Dependencies

* **deps-dev:** bump pytest ([e08bb95](https://github.com/smorinlabs/lost-sessions/commit/e08bb95ba5720f1002a198af932b52c50a5977ad))
* **deps-dev:** bump the lint-and-format group across 1 directory with 2 updates ([11285ff](https://github.com/smorinlabs/lost-sessions/commit/11285fffb115823f5f63fd50948b26466d47e0fa))

## Changelog
