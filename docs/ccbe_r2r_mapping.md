# CCBE to R2R Action Mapping

```mermaid
graph TD
    LS[PUT /loadSources] --> EC[ensure_collections]
    EC -->|GET /v3/collections| RC1[(list collections)]
    EC -->|POST /v3/collections| RC2[(create collection)]
    LS --> UD[upsert_document]
    UD -->|POST /v3/documents| RU[(upload document)]
    UD -->|PUT /v3/documents/{id}/metadata| UM[(update metadata)]

    UA[POST /updateAccess] --> UAa[update_access]
    UAa -->|POST/DELETE /v3/collections/{cid}/documents/{doc}| RA[(update collection membership)]

    UAD[POST /updateAccessDeclarative] --> UAd[decl_update_access]
    UAd -->|GET /v3/documents/{id}/collections| RL[(list document collections)]
    UAd -->|POST/DELETE /v3/collections/{cid}/documents/{doc}| RA

    DS[POST /deleteSources] --> DD[delete_document] -->|DELETE /v3/documents/{id}| RDel[(delete document)]

    CID[POST /countIndexedDocuments] --> LD[list_documents] -->|GET /v3/documents| RD[(list documents)]

    Q[POST /query] --> SR[search] -->|POST /v3/retrieval/search| RS[(search)]
    DOCS[POST /docSearch] --> SR
```

## Endpoint narratives

- **`PUT /loadSources`** first ensures per-user collections then uploads each document. The controller resolves user IDs and metadata before calling `ensure_collections` and `upsert_document`【F:context_chat_backend/controller.py†L523-L590】. These backend calls translate to listing or creating collections【F:context_chat_backend/backends/r2r.py†L142-L174】 and posting or updating documents with server-side hash checks and metadata updates while using a custom ingestion mode【F:context_chat_backend/backends/r2r.py†L245-L378】.
- **`POST /updateAccessDeclarative`** synchronizes document membership for a set of users. CCBE invokes `decl_update_access`【F:context_chat_backend/controller.py†L334-L356】 which lists existing document collections and issues POST/DELETE requests to adjust membership【F:context_chat_backend/backends/r2r.py†L446-L469】.
- **`POST /updateAccess`** grants or revokes access for users. The controller delegates to `update_access`【F:context_chat_backend/controller.py†L369-L399】 which maps to R2R collection membership operations【F:context_chat_backend/backends/r2r.py†L421-L441】.
- **`POST /deleteSources`** removes documents by ID. CCBE calls `delete_document` for each identifier【F:context_chat_backend/controller.py†L443-L467】 which issues `DELETE /v3/documents/{id}` in R2R【F:context_chat_backend/backends/r2r.py†L403-L412】.
- **`POST /countIndexedDocuments`** reports document counts. When using R2R, it simply lists documents and returns the length【F:context_chat_backend/controller.py†L511-L517】【F:context_chat_backend/backends/r2r.py†L178-L185】.
- **`POST /query`** and **`POST /docSearch`** forward search requests to R2R. Both endpoints call `search` on the backend【F:context_chat_backend/controller.py†L727-L743】【F:context_chat_backend/controller.py†L768-L778】 which translates into `POST /v3/retrieval/search`【F:context_chat_backend/backends/r2r.py†L472-L520】.

## References

- R2R document upsert performs a server-side hash comparison by issuing `POST /v3/documents/search` with an empty query and metadata filter to avoid re-uploading unchanged files, updating metadata in place when hashes match and skipping documents that are still ingesting【F:context_chat_backend/backends/r2r.py†L246-L336】【F:context_chat_backend/backends/r2r.py†L187-L205】.
- Access control modifications operate through collection-document membership changes【F:context_chat_backend/backends/r2r.py†L421-L469】.
