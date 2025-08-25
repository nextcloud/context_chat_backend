# CCBE to R2R Action Mapping

```mermaid
graph TD
    EC[CCBE `ensure_collections`] -->|GET /v3/collections| RC1[(R2R collections list)]
    EC -->|POST /v3/collections| RC2[(R2R collection create)]
    LD[CCBE `list_documents`] -->|GET /v3/documents| RD[(R2R documents list)]
    UD[CCBE `upsert_document`] -->|POST /v3/documents| RU[(R2R document upsert)]
    DD[CCBE `delete_document`] -->|DELETE /v3/documents/{id}| RDel[(R2R document delete)]
    SR[CCBE `search`] -->|POST /v3/retrieval/search| RS[(R2R search)]
```

## References
- `ensure_collections` performs both list and create operations on R2R collections【F:context_chat_backend/backends/r2r.py†L134-L166】
- `list_documents` queries the R2R documents endpoint with pagination parameters【F:context_chat_backend/backends/r2r.py†L170-L177】
- `upsert_document` uploads files and metadata to R2R【F:context_chat_backend/backends/r2r.py†L201-L283】
- `delete_document` removes a document from R2R by ID【F:context_chat_backend/backends/r2r.py†L296-L301】
- `search` forwards user queries to R2R's retrieval API【F:context_chat_backend/backends/r2r.py†L363-L379】
