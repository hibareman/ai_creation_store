# System Architecture Diagram

Use this diagram in slides to explain the Souq Engine architecture at a high level.
The SVG version is available at `docs/system_architecture.svg`.

```mermaid
flowchart LR
    U[Users\nStore Owner / Customer / Super Admin]
    FE[Next.js Frontend\nReact + TypeScript + Tailwind]
    API[Django REST API\nDRF + SimpleJWT + Swagger]

    AUTH[users\nAuth, roles, tenant context]
    ADMIN[platform_admin\nSuper Admin dashboard]
    STORE[stores\nStores, settings, domains, publish flow]
    CATALOG[categories + products\nCatalog, images, inventory]
    ORDER[orders\nCart, checkout, customers, orders]
    THEME[themes\nTemplates and appearance]
    SEO[seo\nMetadata and public SEO]
    AI[AI Store Creation Service\nDraft generation and apply workflow]

    SVC[Service / Selector / Serializer Layer\nBusiness rules and tenant scoping]
    DB[(PostgreSQL / SQLite Dev\nPersistent business data)]
    CACHE[(Redis or Django LocMem Cache\nTemporary AI drafts)]
    MEDIA[(Media Storage\nUploaded images)]
    PROVIDER[Ollama / OpenAI-compatible Provider\nLLM responses]
    DOCS[OpenAPI Docs\nSwagger / ReDoc]

    U --> FE --> API
    API --> AUTH
    API --> ADMIN
    API --> STORE
    API --> CATALOG
    API --> ORDER
    API --> THEME
    API --> SEO
    API --> AI
    API --> DOCS

    AUTH --> SVC
    ADMIN --> SVC
    STORE --> SVC
    CATALOG --> SVC
    ORDER --> SVC
    THEME --> SVC
    SEO --> SVC
    AI --> SVC

    SVC --> DB
    SVC --> MEDIA
    AI --> CACHE
    AI --> PROVIDER
    PROVIDER --> AI
```

## AI Draft Workflow

```mermaid
flowchart LR
    A[Store description] --> B[Prompt builder]
    B --> C[AI provider]
    C --> D[Parser]
    D --> E[Schema validator]
    E --> F[Temporary draft cache]
    F --> G[Owner review / regeneration]
    G --> H[Apply approved draft]
    H --> I[(Database)]
    H --> J[Cleanup draft cache]
```

