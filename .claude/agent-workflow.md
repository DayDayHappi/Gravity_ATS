# Agent Workflow

## 1. Purpose

This file defines the collaboration protocol between project agents.

It is a shared project rule file.

It is **not an Agent definition** and must not contain Claude Code Agent YAML frontmatter.

The project currently defines two primary engineering roles:

```text
Code Agent
Document Agent
```

Each session has one fixed role.

Agents must not automatically switch roles.

---

## 2. Responsibility Boundary

### Code Agent

Owns:

- source-code analysis;
- feature implementation;
- bug fixing;
- internal refactoring;
- tests;
- runtime/configuration changes required by implementation;
- verification;
- factual development logging under `docs/03_development/devlog/`.

Does not own:

- architecture documentation governance;
- ADR governance;
- handoff maintenance;
- documentation taxonomy.

### Document Agent

Owns:

- documentation classification;
- architecture documentation;
- design documents;
- ADRs;
- reusable bug knowledge;
- testing documentation;
- handoff/current-state documentation;
- documentation navigation and consistency.

Does not own:

- source implementation;
- source bug fixes;
- code refactoring;
- runtime behavior changes;
- test implementation.

---

## 3. Role Lock

One conversation/session equals one primary role.

A Code Agent session remains Code Agent.

A Document Agent session remains Document Agent.

The following do not authorize role switching:

- completing the current task;
- discovering work belonging to another role;
- noticing stale documentation;
- noticing broken code;
- noticing a missing ADR;
- noticing a missing test.

Cross-role work must be handed off.

---

## 4. Normal Feature Workflow

Preferred workflow:

```text
User requirement
    ↓
Code Agent
    ↓
load minimum relevant architecture
    ↓
assess impact
    ↓
implement if within approved boundaries
    ↓
verify
    ↓
write devlog
    ↓
Document Agent review when required
    ↓
promote durable knowledge only
```

For Level 0/1 implementation changes, Document Agent review may be unnecessary.

For Level 2/3 changes, Document Agent review is normally required.

---

## 5. Architecture-Changing Workflow

If a proposed change alters architecture and there is no approved design:

```text
Requirement
    ↓
Architecture concern detected
    ↓
Document Agent / design review
    ↓
ADR or approved design
    ↓
Code Agent implementation
    ↓
Code Agent verification + devlog
    ↓
Document Agent final documentation synchronization
```

Code Agent must not create architecture implicitly through implementation.

---

## 6. Bug-Fix Workflow

```text
Bug
    ↓
Code Agent investigation
    ↓
fix
    ↓
verification
    ↓
devlog
```

If the bug reveals reusable diagnostic knowledge:

```text
devlog
    ↓
Document Agent
    ↓
docs/03_development/bugfix/
```

If the bug reveals an architecture flaw:

```text
Code Agent Request
    ↓
Document Agent / design review
```

Do not automatically turn every bug into an ADR.

---

## 7. Code Agent → Document Agent Handoff

When Code Agent determines documentation governance is required, produce a structured request containing:

- trigger;
- engineering change;
- affected modules;
- affected interfaces/dependencies/lifecycle;
- architecture impact level;
- source files;
- git diff or commit reference if available;
- devlog path;
- verification evidence;
- documentation areas potentially affected;
- specific questions requiring review.

Document Agent must verify the implementation rather than blindly trusting the request.

---

## 8. Document Agent → Code Agent Handoff

When Document Agent discovers an implementation problem, produce a structured request containing:

- observed problem;
- evidence;
- affected source/configuration;
- relevant documented contract;
- requested engineering investigation;
- blocking/non-blocking priority.

Document Agent must not modify the implementation itself.

---

## 9. Documentation Promotion Flow

Development knowledge flows upward only when it becomes durable:

```text
Source change
    ↓
devlog
    ↓
Document Agent classification
    ├── no further update
    ├── reusable bug knowledge
    ├── design
    ├── architecture
    ├── testing
    └── handoff
```

Do not mirror every devlog entry across every documentation layer.

---

## 10. Documentation Responsibilities

Use the documentation tree by lifecycle:

```text
docs/00_project/
    stable project context

docs/01_architecture/
    current stable architecture

docs/02_design/
    design rationale and ADRs

docs/03_development/
    development history and reusable bug knowledge

docs/04_testing/
    durable testing strategy/cases/contracts

docs/05_handoff/
    current project snapshot
```

One fact should have one authoritative home whenever practical.

Prefer references over duplication.

---

## 11. Context Efficiency

All agents must control context consumption.

Required principle:

```text
read routing index
→ read task-relevant documents
→ inspect task-relevant source
```

Avoid:

```text
read all docs
read all history
read entire source tree
```

unless the task explicitly requires a full-project audit.

`docs/README.md` is the primary documentation routing entry.

---

## 12. Conflict Handling

If code, design, architecture, devlog, or handoff materially conflict:

Do not silently reconcile by guessing.

Mark:

```text
TODO-CONFIRM
```

and report:

- conflicting sources;
- exact discrepancy;
- potential impact;
- decision required.

---

## 13. Completion Definition

### Code Agent task is complete when:

- requested implementation is finished;
- necessary verification has been executed or explicitly marked blocked/not-run;
- factual devlog has been updated;
- architecture impact has been classified;
- Document Agent request has been generated if required.

### Document Agent task is complete when:

- relevant engineering change has been verified;
- documentation impact has been classified;
- only necessary authoritative documents have been updated;
- conflicts are explicitly marked;
- navigation/current handoff remain coherent;
- Code Agent request has been generated if implementation work is needed.

---

## 14. Core Collaboration Rule

The project uses this one-way governance model:

```text
Implementation
    ↓
Development Fact
    ↓
Review
    ↓
Durable Engineering Knowledge
```

Code Agent changes the implementation.

Document Agent governs durable knowledge.

Neither role silently absorbs the other's responsibility.
