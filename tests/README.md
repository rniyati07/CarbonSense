# tests/

Test suites organized by scope and purpose.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `unit/` | Unit tests for individual service and model components | **ENG-3** (all sub-epics) |
| `integration/` | Integration tests across distributed pipeline — contract tests at every service boundary | **ENG-3**, **ENG-4**, **ENG-5** |
| `security/tenant_isolation_fuzzer/` | Tenant isolation fuzzer — deliberately attempts cross-tenant reads/writes and asserts every attempt fails closed at the RLS layer | **ENG-1f** |
| `performance/` | Performance benchmarks — latency targets per TRD 9.1 | **ENG-7** |
| `e2e/` | End-to-end pipeline tests — synthetic tenant with golden COMBED fixture, known expected findings | **ENG-3**, **ENG-4** |

## Rules

1. Every epic must include tests.
2. The tenant isolation fuzzer runs on every data-layer PR — it is a security-critical test class with the same severity as a failing build.
3. The golden COMBED fixture is used as a known-output regression suite.
4. Use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.performance`, `@pytest.mark.e2e`.