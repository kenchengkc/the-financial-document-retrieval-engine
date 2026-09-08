# Operating Cost Budget

FDRE has a **hard recurring infrastructure budget of $15/month** and a **normal operating target of $10/month or less**, leaving headroom for usage variance and provider pricing changes.

This budget is an engineering constraint. A feature that requires additional recurring infrastructure is not production-ready for FDRE unless an existing service can be reduced or removed to keep the total inside the cap.

## Cost principles

1. **No service for optics.** Do not add Redis, Kafka, a separate vector database, a search cluster, a warehouse, or a monitoring SaaS unless a measured requirement cannot be met economically by the existing stack.
2. **Reuse before scaling.** Reuse database pools, provider clients, HTTP connections, immutable lookup indexes, and cached deterministic results before increasing compute or adding services.
3. **Avoid unnecessary paid model work.** Historical research data should not be bulk-embedded unless retrieval quality requires it. Cache/reuse deterministic results and preserve provider rate limits.
4. **Keep batch work bounded.** Ingestion and research workflows should be incremental, resumable, and able to skip unchanged work.
5. **Storage growth must preserve research value.** Prefer compact representations such as `halfvec` and Parquet when they preserve correctness and reproducibility.
6. **Cost changes are reviewed like correctness changes.** Pull requests that can change recurring spend must state the expected direction and the resource that drives it.

## Budget guardrails

| Level | Monthly recurring spend | Action |
| --- | ---: | --- |
| Target | `<= $10` | Normal operation |
| Warning | `> $10` | Review database, compute, model, and egress usage before adding workload |
| Hard cap | `$15` | Do not add recurring capacity; reduce or defer nonessential workload |

Vendor prices and free-tier allowances change over time, so this document intentionally does not freeze provider price tables. Billing dashboards are the source of truth for actual spend.

## Preferred optimization order

When cost or latency rises, optimize in this order:

1. eliminate duplicate work and unnecessary provider calls;
2. reuse clients/connections and immutable lookup state;
3. improve query/index efficiency;
4. batch or schedule noninteractive work;
5. reduce retained representation size where correctness is unchanged;
6. only then consider additional paid infrastructure.

## Protected research controls

The cost ceiling must not be met by weakening:

- point-in-time filtering;
- survivorship-bias protections;
- source and feature lineage;
- fail-closed identity/evidence behavior;
- frozen evaluation artifacts;
- benchmark and OOS methodology;
- required tests or CI validation.

A cheaper result that cannot be reproduced or trusted is not an optimization.
