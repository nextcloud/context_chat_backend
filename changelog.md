<!--
  - SPDX-FileCopyrightText: 2023 Nextcloud GmbH and Nextcloud contributors
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->
# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).


## 4.4.1 - 2025-07-31

### Fixed

- fail fast for fatal embedding server errors (#198) @kyteinsky
- no initial check for the embedding loader (#198) @kyteinsky
- better retry mechanism in the embedding server (#198) @kyteinsky


## 4.4.0 - 2025-07-21

### Fixed
- improve source tracking so no file stat is lost (#190) @kyteinsky
- improve OCS signing error messages (#189) @kyteinsky
- handle encrypted pdf decryption error (#195) @kyteinsky

### Changed
- maintenance update (#184) @kyteinsky
- update issue template to attach logs (#193) @lukasdotcom
- bump llama_cpp_python (#196) @kyteinsky

### Added
- add doc search endpoint (#185) @kyteinsky
- pre download the tokenizer instead of mid operation (#191) @kyteinsky
- add endpoint for downloading logs (#192) @lukasdotcom
- use supervisord to manage the processes (#194) @kyteinsky


## 4.3.0 - 2025-05-08

### Fixed
- fix(nc_texttotext): retries and graceful error handling for schedule (#179) @kyteinsky
- fix(dyn_loader): richer error message for embedding server start fail (#179) @kyteinsky
- fix(deps): add libreoffice to install_deps (#180) @kyteinsky

### Changed
- bump minor version to match the companion app


## 4.2.0 - 2025-04-03

### Changed
- bump minor version to match the companion app


## 4.1.1 - 2025-04-02

### Fixed
- do not fail access update requests if source is not found in db (#163) @kyteinsky
- fix for when too many sources/chunks for postgres IN (#166) @Lukasdotcom
- retry on httpx exceptions in embedding requests (#168) @kyteinsky


## 4.1.0 - 2025-02-21

### Fixed
- fix sources that are decoded as only spaces fail to index (#157) @Lukasdotcom

### Added
- add endpoint to count indexed documents (#160) @marcelklehr


## 4.0.7 - 2025-02-10

### Changed
- ocs signature verification changes (#154) @kyteinsky

### Fixed
- fix logger issue (#153) @marcelklehr


## 4.0.6 - 2025-02-10

### Changed
- return sources to retry (#148) @marcelklehr
- log state of indexing regularly (#150) @marcelklehr

### Fixed
- skip issues with enhancement or to develop labels (#149) @kyteinsky
- package sha fix, upgrade and other fixes (#144) @kyteinsky
- add missing app_api env declaration for EXTERNAL_DB (#143) @kyteinsky


## 4.0.5 - 2025-01-20

### Fixed
- example env min app_api ver. 3.0.0 (#137) @kyteinsky
- add logging files to Dockerfile (#139) @kyteinsky
- make logs persistent (#140) @kyteinsky
- better handling of embedding server failure (#140) @kyteinsky

### Changed
- remove root logs dir (#140) @kyteinsky
- revert CI env var in embedding server proc (#140) @kyteinsky
- remove unsupported vectordb configs (#140) @kyteinsky
- update readme: remove beta status (#140) @kyteinsky
- update readme for logs (#140) @kyteinsky


## 4.0.4 - 2025-01-17

### Fixed
- proper handling of index locks (#133) @kyteinsky
- better logging (#135) @kyteinsky

### Changed
- remove update_progress fn now that there is no caller (#135) @kyteinsky


## 4.0.3 - 2025-01-11

### Fixed
- prevent two concurrent requests processing the same source (#130) @kyteinsky
- shorten wait to 10 mins before failing in load sources for max requests allowed (#130) @kyteinsky


## 4.0.2 - 2025-01-09

### Fixed
- fix utf-8 encoding fixes (#118) @kyteinsky
- decl access update in doc indexing (#125) @kyteinsky
- ignore temp exceptions during task polling (#127) @kyteinsky


## 4.0.1 - 2024-12-19

### Fixed
- only remove leftovers from previous db (#115) @kyteinsky


## 4.0.0 - 2024-12-17

### Changed
- database schema change for no data duplication (#108) @kyteinsky
- remove support for Chroma DB and Weaviate (#108) @kyteinsky

### Fixed
- consider delete successful if doc was not in db (#107) @kyteinsky
- catch exceptions in update_access loop (#109) @kyteinsky

### Added
- add reuse compliance (#111) @AndyScherzinger


## 4.0.0-beta5 - 2024-11-20

### Fixed

- selective context args (#105) @kyteinsky
- print the original traceback of the exception (#106) @kyteinsky


## 4.0.0-beta4 - 2024-11-14

### Fixed

- do not import types from llama before symlink fix (#102) @kyteinsky
- change postgres port to 5001 + fixes (#103) @kyteinsky


## 4.0.0-beta3 - 2024-11-12

### Fixed

- import signal package directly (#100) @kyteinsky


## 4.0.0-beta2 - 2024-11-11

### Fixed

- reset the vector db in favour of a new embedding model (#98) @kyteinsky


## 4.0.0-beta - 2024-11-07

Documents will be reindexed in this version. They will be reindexed again in the stable 4.0.0 release.
This version is not recommended for production use.

### Fixed
- Better error and context handling (#83) @kyteinsky
- Remove null bytes out of document texts (#86) @kyteinsky
- Add title to header validation in load docs (#87) @kyteinsky
- Memory leak fixes and marker tests (#89) @marcelklehr
- Download model in background task (#96) @kyteinsky @marcelklehr
- Isolate doc ingestion with a llama http server (#90) @kyteinsky

### Added
- Add postgresql vectordb support (#84) @kyteinsky
- Use multilingual embedding model (#81) @marcelklehr
- Install postgresql in the docker container (#95) @kyteinsky


## 3.1.0 - 2024-09-30

### Changed
- New minor version to maintain versioning consistency with the companion app


## 3.0.5 - 2024-09-19
### Fixed
- lock embedding model forward pass (#78) @kyteinsky


## 3.0.4 - 2024-09-18
### Fixed
- fix remaining lowercase comparisons for COMPUTE_DEVICE @kyteinsky


## 3.0.3 - 2024-09-18
### Fixed
- use uppercase comparisons for COMPUTE_DEVICE @kyteinsky
- add traceback to caught exception in doc loader @kyteinsky


## 3.0.2 - 2024-09-18
### Changed
- make stuff fit in 8GB VRAM and don't lock text2text api calls (#70) @kyteinsky

### Fixed
- fix: detect additional NVIDIA GPUs (#68) @kyteinsky


## 3.0.1 - 2024-08-01
### Changed
- update llama-cpp-python package in dockerfile @kyteinsky

### Fixed
- nvidia-cuda/llama.cpp compat issue @kyteinsky


## 3.0.0 - 2024-07-30
### Changed
- New major version to maintain versioning consistency with the companion app
- Update readme @kyteinsky

### Added
- Use Taskprocessing TextToText provider as LLM (#60) @marcelklehr
- Upgrade base image to cuda 12.2 @kyteinsky


## 2.2.1 - 2024-07-09
### Fixed
- use COMPUTE_DEVICE env var if present for config @kyteinsky
- add cuda compat llib path back @kyteinsky


## 2.2.0 - 2024-06-25
### Fixed
- leave room for generated tokens in the context window @kyteinsky
- Dockerfile llama-cpp-python install @kyteinsky
- Version based repair and other changes (#54) @kyteinsky
- .in.txt and use compiled llama-cpp-python @kyteinsky
- correctly log exceptions @kyteinsky
- do not verify docs before delete in Chroma (#53) @kyteinsky
- offload only when instantiated @kyteinsky
- add odfpy back and update deps @kyteinsky

### Changed
- up context limit to 30 @kyteinsky
- update configs @kyteinsky
- change repairs to be version based @kyteinsky
- upgrade base image to cuda 12.1 and drop cuda dev deps @kyteinsky
- gh: run the prompts without strategy matrix @kyteinsky

### Added
- simple queueing of prompts @kyteinsky
- dynamic loader and unloader @kyteinsky
- add `GET /enabled` for init check @kyteinsky
- Use the user's language (#50) @marcelklehr


## 2.1.1 - 2024-04-23
### Changed
- use 8192 as context length

### Fixed
- replace @ with .at. in collection name
- replace pandoc completely due to random memory hogs with other python packages
- types fixes and langchain import updates


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
