# CCBE HTTP Endpoints

| Method | Path | Description |
|-------|------|-------------|
| GET | `/` | Basic service check returning a greeting【F:context_chat_backend/controller.py†L309-L314】 |
| PUT | `/enabled` | Enable or disable the app via AppAPI hook【F:context_chat_backend/controller.py†L317-L320】 |
| GET | `/enabled` | Report whether the app is currently enabled【F:context_chat_backend/controller.py†L323-L325】 |
| POST | `/init` | Kick off background initialization reporting progress to Nextcloud【F:context_chat_backend/controller.py†L328-L331】 |
| POST | `/updateAccessDeclarative` | Replace document access lists for users【F:context_chat_backend/controller.py†L334-L366】 |
| POST | `/updateAccess` | Allow or deny users access to a document【F:context_chat_backend/controller.py†L369-L409】 |
| POST | `/updateAccessProvider` | Manage document access by provider (builtin backend only)【F:context_chat_backend/controller.py†L412-L429】 |
| POST | `/deleteSources` | Remove documents by ID list【F:context_chat_backend/controller.py†L443-L476】 |
| POST | `/deleteProvider` | Delete documents belonging to a provider for all users【F:context_chat_backend/controller.py†L479-L492】 |
| POST | `/deleteUser` | Remove all documents and access entries for a user【F:context_chat_backend/controller.py†L495-L508】 |
| POST | `/countIndexedDocuments` | Count indexed documents across providers or via backend【F:context_chat_backend/controller.py†L511-L519】 |
| PUT | `/loadSources` | Ingest documents for users, ensuring collection mapping and deduplication【F:context_chat_backend/controller.py†L523-L590】 |
| POST | `/query` | Perform question answering, optionally retrieving context from backend【F:context_chat_backend/controller.py†L727-L765】 |
| POST | `/docSearch` | Search for documents matching a query without invoking the LLM【F:context_chat_backend/controller.py†L769-L804】 |
| GET | `/downloadLogs` | Download zipped server logs for debugging【F:context_chat_backend/controller.py†L802-L811】 |
