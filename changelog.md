# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## 2.1.0 - 2024-04-15
### Changed
- no context generation is now a chat completion
- filter sources before document decode

### Fixed
- set the memory limit for pandoc to 4GB (#29)
- adjustments for changes in AppAPI in last two months (#26)
- pass useContext to the query function
- prune context/query to fit the context window
- pandoc hangs

### Added
- accelerator detection on container boot
- repair steps
- increase context length to 16384


## 2.0.1 - 2024-03-23
### Fixed
- user_id sanitisation for vectordb collection names
- symlink config.yaml in the persistent dir
- use requirements.cpu.txt in CI due to space constraints


## 2.0.0 - 2024-03-21
### Changed
- use ubuntu-22.04 to use gh runners
- migrate useful env vars to config(.cpu).yaml
- move config(.cpu)?.yaml to persistent_storage

### Fixed
- modifications to scoped context chat
- fix: location of config.yaml in the dockerfiles
- pre-commit autoupdate


## 1.2.0 - 2024-03-11
### Fixed
* fix: convert getenv's output to str
* type fixes and other numerous fixes
* fix: metadata search for provider
* move COLLECTION_NAME to vectordb dir
* skip ingestion .pot files

### Added
* Added initial cuda11.8 support (#16)
* Introduce /deleteSourcesByProviderForAllUsers and fixes
* add support for scoped context in query
* add integration test
* use /init and persistent storage


## 1.1.1 – 2024-02-14
### Fixed
* drop `.run/`
* revert pytorch to cpu-only package


## 1.1.0 – 2024-02-13
### Added
* add end_separator option in config
* support new content providers

### Fixed
* update app_api auth middleware
* fix add ctransformers to supported models list
* update readme with new tips and tricks
* update Makefile
* update llama_cpp_python to fix inference on gpu machines
* use normal torch for arm builds


## 1.0.1 – 2024-01-04
### Fixed
* updated app store description and readme


## 1.0.0 – 2023-12-21
### Added
* the app
