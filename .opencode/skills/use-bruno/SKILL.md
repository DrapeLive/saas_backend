# Bruno API Client — Agent Skill

Bruno is a Git-friendly, offline-first API client. Collections are plain `.bru` files checked into version control. This skill covers everything needed to read, write, and reason about Bruno collections.

---

## File Structure

```
my-collection/
├── bruno.json                  # Collection root marker
├── environments/
│   ├── local.bru
│   ├── staging.bru
│   └── production.bru
├── auth/
│   ├── folder.bru              # Folder-level scripts/vars
│   └── login.bru
├── users/
│   ├── get-user.bru
│   └── create-user.bru
└── .gitignore                  # Should ignore .env
```

---

## .bru File Syntax (Bru Lang)

### Request file anatomy

```bru
meta {
  name: Get User
  type: http           # http | graphql
  seq: 1               # sort order in UI
  tags: [smoke, sanity]
}

get {
  url: {{base_url}}/api/users/{{user_id}}
  body: none
  auth: bearer
}

params:query {
  page: 1
  limit: 10
}

params:path {
  user_id: 123
}

headers {
  x-custom-header: some-value
}

auth:bearer {
  token: {{auth_token}}
}

body:json {
  {
    "name": "John",
    "email": "john@example.com"
  }
}

script:pre-request {
  // JavaScript runs before request is sent
  req.setHeader("x-timestamp", new Date().toISOString());
}

script:post-response {
  // JavaScript runs after response is received
  const data = res.getBody();
  bru.setEnvVar("auth_token", data.token);
}

tests {
  test("status is 200", () => {
    expect(res.status).to.equal(200);
  });
}

assert {
  res.status: eq 200
  res.body.id: isNumber
}
```

### HTTP methods

```bru
get { url: ... }
post { url: ...; body: json; auth: bearer }
put { url: ... }
patch { url: ... }
delete { url: ... }
options { url: ... }
head { url: ... }
```

### Body types

```bru
body: json          # application/json
body: text          # plain text
body: xml           # application/xml
body: form-urlencoded
body: multipart-form
body: graphql
body: none
```

### Auth types

```bru
auth: none
auth: bearer
auth: basic
auth: oauth2
auth: oauth1
auth: awsv4
auth: digest

auth:bearer {
  token: {{auth_token}}
}

auth:basic {
  username: {{username}}
  password: {{password}}
}
```

---

## Environment Files

Location: `environments/<name>.bru`

```bru
vars {
  base_url: https://api.example.com
  user_id: 42
  auth_token:              # leave blank, filled by script
}

vars:secret [
  password
  auth_token
]
```

- **`vars`** — plain variables, written to disk and safe to commit (as long as no secrets).
- **`vars:secret`** — listed variable names are stored encrypted by the OS, never written to the `.bru` file. Safe to commit the file; secret values are not in it.

Use `{{var_name}}` syntax anywhere in a request to interpolate.

---

## Variable Precedence (highest → lowest)

1. Runtime vars (`bru.setVar`)
2. Request vars
3. Folder vars
4. Collection vars
5. Environment vars (`bru.setEnvVar`)
6. Process env (`bru.getProcessEnv`)

---

## JavaScript Scripting API

Scripts run in `script:pre-request` and `script:post-response` blocks.

### `bru` — core object

#### Environment vars

```js
bru.getEnvName(); // current env name e.g. "staging"
bru.getEnvVar("key"); // read env var
bru.setEnvVar("key", "value"); // write env var (in-memory)
bru.setEnvVar("key", "value", { persist: true }); // write + save to disk
bru.hasEnvVar("key"); // boolean
bru.deleteEnvVar("key");
bru.getAllEnvVars(); // returns object
```

#### Runtime vars (shared across requests in a collection run)

```js
bru.getVar("key");
bru.setVar("key", value);
bru.hasVar("key");
bru.deleteVar("key");
bru.getAllVars();
```

#### Global env vars (workspace-wide)

```js
bru.getGlobalEnvVar("key");
bru.setGlobalEnvVar("key", value);
bru.hasGlobalEnvVar("key");
```

#### Collection / folder / request vars (read-only)

```js
bru.getCollectionVar("key");
bru.getFolderVar("key");
bru.getRequestVar("key");
bru.getProcessEnv("KEY"); // reads process.env.KEY
bru.getSecretVar("manager.key"); // reads from secret manager
```

#### Utilities

```js
await bru.sleep(ms); // pause execution
bru.interpolate("{{$randomEmail}}"); // resolve dynamic vars in a string
bru.cwd(); // absolute path to collection root
bru.isSafeMode(); // true = Safe Mode, false = Developer Mode
bru.getCollectionName();

// Run another request programmatically
const res2 = await bru.runRequest("Login");
const token = res2.data.token;

// Send an ad-hoc HTTP request
const r = await bru.sendRequest({ method: "GET", url: "https://example.com" });
```

#### Runner control (collection runs only)

```js
bru.setNextRequest("Request Name"); // jump to named request
bru.runner.skipRequest(); // skip current request
bru.runner.stopExecution(); // abort entire run
bru.runner.iterationData.get("col"); // read CSV/JSON data file value
bru.runner.iterationIndex; // zero-based row index
bru.runner.totalIterations;
```

---

### `req` — request object (pre-request scripts)

```js
req.getUrl() / req.setUrl(url)
req.getMethod() / req.setMethod("POST")
req.getHeader("name") / req.setHeader("name", "value")
req.getHeaders() / req.setHeaders({ key: value })
req.deleteHeader("name")
req.getBody() / req.setBody({ ... })
req.setTimeout(ms)
req.getAuthMode()                      // "bearer" | "basic" | "none" | ...
req.getName()
req.getTags()                          // ["smoke", "sanity"]
req.getExecutionMode()                 // "runner" | "standalone"
req.getExecutionPlatform()             // "app" | "cli"
```

---

### `res` — response object (post-response + test scripts)

```js
res.status; // 200
res.statusText; // "OK"
res.headers; // { "content-type": "application/json", ... }
res.body; // auto-parsed JSON object, or string
res.responseTime; // ms
res.url; // final URL after redirects

res.getStatus();
res.getStatusText();
res.getHeader("name");
res.getHeaders();
res.getBody();
res.setBody(newBody); // override for downstream tests
res.getResponseTime();
res.getSize(); // { body, headers, total } in bytes
```

---

## Common Patterns

### Auto-capture auth token after login

`script:post-response` in the Login request:

```js
const data = res.getBody();
// adjust path based on your API's response shape:
bru.setEnvVar("auth_token", data.token);
// or: data.data.token / data.access_token / data.result.accessToken
```

### Use token in all other requests

```bru
auth: bearer

auth:bearer {
  token: {{auth_token}}
}
```

### Multi-role auth (admin / superadmin)

Create two environments with different credentials:

`environments/admin.bru`

```bru
vars {
  base_url: https://api.example.com
  login_email: admin@company.com
  auth_token:
}
vars:secret [
  login_password
  auth_token
]
```

`environments/superadmin.bru`

```bru
vars {
  base_url: https://api.example.com
  login_email: superadmin@company.com
  auth_token:
}
vars:secret [
  login_password
  auth_token
]
```

Login request body:

```bru
body:json {
  {
    "email": "{{login_email}}",
    "password": "{{login_password}}"
  }
}
```

Switch roles by selecting environment in the UI top-right picker, then run Login once. All requests pick up `{{auth_token}}` automatically.

### Request chaining (pass data between requests)

In Request A `script:post-response`:

```js
bru.setVar("created_id", res.getBody().id);
```

In Request B URL:

```bru
get {
  url: {{base_url}}/api/items/{{created_id}}
}
```

Note: `{{created_id}}` works for runtime vars set with `bru.setVar`.

### Conditional pre-request logic

```js
// script:pre-request
if (!bru.hasEnvVar("auth_token")) {
    console.warn("No auth token — run Login first");
    bru.runner.skipRequest();
}
```

### Dynamic variables (built-in)

```
{{$randomEmail}}
{{$randomFirstName}}
{{$randomLastName}}
{{$randomFullName}}
{{$randomInt}}
{{$randomUuid}}
{{$guid}}
{{$timestamp}}
{{$isoTimestamp}}
```

Use in request fields directly or resolve in scripts with `bru.interpolate("{{$randomEmail}}")`.

---

## Writing Tests

Tests go in the `tests` block or alongside assertions:

```bru
tests {
  test("status is 200", () => {
    expect(res.status).to.equal(200);
  });

  test("body has token", () => {
    expect(res.body).to.have.property("token");
  });

  test("responds fast", () => {
    expect(res.responseTime).to.be.lessThan(1000);
  });
}
```

Inline assertions (no JS needed):

```bru
assert {
  res.status: eq 200
  res.body.token: isDefined
  res.body.id: isNumber
  res.responseTime: lt 2000
}
```

---

## Folder-level Scripts

`folder.bru` — runs for every request in the folder:

```bru
script:pre-request {
  // e.g. inject auth header for entire folder
  req.setHeader("Authorization", "Bearer " + bru.getEnvVar("auth_token"));
}
```

---

## Collection-level Config

`bruno.json`:

```json
{
    "version": "1",
    "name": "My API",
    "type": "collection",
    "ignore": [".env", "node_modules"]
}
```

---

## CLI Usage

```bash
# Install
npm install -g @usebruno/cli

# Run full collection
bru run --env staging

# Run specific folder
bru run auth/ --env staging

# Run with data file
bru run --env staging --csv-file-path data.csv

# Run by tag
bru run --env staging --tag smoke

# Output report
bru run --env staging --reporter-json results.json
```

---

## Secret Management for VCS Safety

Mark sensitive vars as secret in the environment file:

```bru
vars:secret [
  login_password
  auth_token
  api_key
]
```

Bruno stores the actual values encrypted on the local machine (OS keychain / AES-256 fallback). The `.bru` file only stores the variable _names_ — safe to commit.

For CI/CD, inject secrets via `.env` file or process environment:

```bash
bru run --env production --env-var "login_password=$SECRET_PASSWORD"
```

Read them in scripts with `bru.getProcessEnv("login_password")`.

---

## Key Gotchas

- `res` is only available in `script:post-response` and `tests` blocks, not in `script:pre-request`.
- `bru.setEnvVar` without `{ persist: true }` is in-memory only — changes are lost when the app restarts.
- `bru.setVar` (runtime vars) only live for the current collection run, not across separate runs.
- `bru.runner.*` methods have no effect on single-request runs, only collection runs.
- `bru.runRequest("Name")` uses the request's display name from `meta { name: ... }`, not the filename.
- Secret vars listed in `vars:secret` must be set manually via the UI on first use — they can't be set from scripts.
- The `seq` field in `meta` controls UI sort order; CLI runs in filesystem order unless `--sort` is specified.

> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.usebruno.com/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenCollection YAML Format

<Info>
  YAML support is available starting with Bruno 3.0.0. Bruno continues to support `.bru` files alongside the new YAML format.
</Info>

Starting with Bruno 3.0.0, you can save your API request data using YAML (`.yml`) files as an alternative to the `.bru` format. This YAML format follows the [OpenCollection specification](https://spec.opencollection.com/), an **open specification created by Bruno** for defining executable API collections.

## Why OpenCollection YAML?

OpenCollection combines the power of an open specification with the industry-standard YAML format:

### Open Specification

- **Community-driven standard** — OpenCollection is an open specification created by Bruno, designed to be transparent and extensible
- **No vendor lock-in** — Your API collections are stored in a well-documented, open format that you fully own and control
- **Interoperability** — Build tooling, integrations, and workflows around a documented specification

### Industry-Standard YAML Format

- **Universal format** — YAML is one of the most widely adopted data serialization formats, used across the software industry
- **Zero learning curve** — If you've worked with Kubernetes, Docker Compose, GitHub Actions, or countless other tools, you already know YAML
- **Human-readable** — Clean, intuitive syntax that's easy to read, write, and review in pull requests

### Seamless Tooling Integration

Since everything is stored in standard YAML, you can leverage the entire ecosystem of existing tools:

- **IDE support** — Native syntax highlighting in VS Code, JetBrains IDEs, Vim, and virtually any editor without additional extensions
- **Linting & validation** — Use tools like `yamllint`, `prettier`, or custom JSON Schema validators
- **Git integration** — GitHub, GitLab, and Bitbucket provide built-in YAML syntax highlighting and diff views for pull requests
- **Scripting & automation** — Parse and manipulate collections with standard YAML libraries in any programming language (Python, Node.js, Go, etc.)
- **CI/CD pipelines** — Easily integrate with existing pipeline tools that already understand YAML

## OpenCollection vs OpenAPI

OpenCollection and OpenAPI serve complementary purposes:

| OpenAPI                                                            | OpenCollection                                                        |
| ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| Defines **what** your API is — the contract, schema, and structure | Defines **how** to use your API — scenarios, workflows, and execution |
| API endpoints and HTTP methods                                     | Business workflows and sequences                                      |
| Request and response schemas                                       | Pre-request scripts and tests                                         |
| Authentication requirements                                        | Environment variables and secrets                                     |
| Data types and validation rules                                    | Runnable, shareable collections                                       |

**OpenAPI tells you the shape of the door. OpenCollection shows you how to walk through it.**

<Tip>
  Learn more about OpenCollection at [opencollection.com](https://www.opencollection.com/) and view the full specification at [spec.opencollection.com](https://spec.opencollection.com/).
</Tip>

## Quick Example

Here's what a simple POST request looks like in YAML format:

```yaml theme={null}
info:
    name: Create User
    type: http
    seq: 1

http:
    method: POST
    url: https://api.example.com/users
    body:
        type: json
        data: |-
            {
              "name": "John Doe",
              "email": "john@example.com"
            }
    auth: inherit

runtime:
    scripts:
        - type: tests
          code: |-
              test("should return 201", function() {
                expect(res.status).to.equal(201);
              });

settings:
    encodeUrl: true
```

Compare this to the equivalent `.bru` file:

```bru theme={null}
meta {
  name: Create User
  type: http
  seq: 1
}

post {
  url: https://api.example.com/users
  body: json
  auth: inherit
}

body:json {
  {
    "name": "John Doe",
    "email": "john@example.com"
  }
}

tests {
  test("should return 201", function() {
    expect(res.status).to.equal(201);
  });
}
```

## File Storage

When using YAML format, your collections will be stored with `.yml` file extensions instead of `.bru`. The folder structure uses `opencollection.yml` as the collection root file:

```
my-collection/
├── opencollection.yml   # Collection configuration (YAML format)
├── environments/
│   └── development.yml
├── users/
│   ├── folder.yml       # Folder configuration
│   ├── create-user.yml
│   ├── get-user.yml
│   └── delete-user.yml
└── orders/
    └── create-order.yml
```

Compare this to the `.bru` format structure which uses `bruno.json`:

```
my-collection/
├── bruno.json           # Collection configuration (Bru format)
├── collection.bru       # Collection-level settings
├── environments/
│   └── development.bru
├── users/
│   ├── folder.bru       # Folder configuration
│   ├── create-user.bru
│   ├── get-user.bru
│   └── delete-user.bru
└── orders/
    └── create-order.bru
```

## Migration

Bruno supports both `.bru` and `.yml` formats, so you can migrate your collections gradually. Both formats can coexist within the same collection during the transition period.

<Warning>
  Migration tooling is planned for a future release. For now, you can manually convert files or create new requests using the YAML format.
</Warning>

## Resources

- [OpenCollection Specification](https://spec.opencollection.com/)
- [OpenCollection JSON Schema](https://schema.opencollection.com/)
