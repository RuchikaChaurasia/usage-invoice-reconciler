# Dashboard requirements

> **Hypothetical scenario on synthetic data.** These requirements describe how I would approach the
> problem. I have not interviewed real stakeholders, so each is an assumption to validate.

## User and problem
**User:** a finance or billing-operations analyst who reconciles GPU usage against invoices each month.

**Assumed current state:** usage and invoices are compared by hand in spreadsheets. The work is slow,
easy to get wrong, and the results are hard to trust or repeat.

**Goal:** replace the spreadsheet with a self-serve view that shows what to chase first, in dollars,
and lets the user trace any number back to the underlying records.

## What the user needs to do
1. See the size of the problem in under 10 seconds (total dollars at risk, count, largest category).
2. See which exceptions matter most (sorted by dollars).
3. Narrow to a month, GPU type, exception type, or customer.
4. Click into one exception and understand why it was flagged, in plain language.
5. See the raw usage rows behind it.
6. Take the list into a spreadsheet (CSV export), because that is where follow-up happens.
7. Know whether the numbers can be trusted.

## Requirements and the reason for each

| Requirement | Why |
|---|---|
| Default view is exceptions sorted by dollars at risk, not all records | A finance user wants a work queue, not a data dump |
| Headline KPIs at the top; title and dollars at risk stay visible in the sidebar while scrolling | The total should never disappear while investigating one row |
| Filters: billing month, exception type, GPU type, customer | The four ways the assumed user slices the work |
| Drill-down from exception to plain-language explanation to underlying rows | The summary number must be traceable, or people will not trust it |
| Rows labeled Counted / Duplicate (not counted) / Late (after invoice) | Explains the logic without reading SQL |
| CSV export of the filtered list | Finance works in spreadsheets; export supports the transition |
| "Totals tie out" badge that turns red on failure | A visible trust signal, backed by the same checks as the tests |
| Plain-language labels, not column names | The user is not an engineer |
| Page-loaded time (data refresh time is a future item) | Stale data is a common reason dashboards are abandoned |

## Out of scope for this version
- Real billing logic: credits, discounts, commitments, taxes
- Writing back to billing systems or auto-correcting invoices
- Authentication and role-based access
- Scheduled refresh and alerting (specced as a future item; see the roadmap)
- Cloud hosting

## Technical notes for an engineering handoff
- Logic lives in SQL views, so any BI tool or a dbt model can reuse it.
- Data quality checks run in pytest and should move into the pipeline.
- Credentials in the demo are local placeholders. A real deployment needs a secrets manager.

## How I would measure success (no numbers claimed)
| Goal | How I would measure it |
|---|---|
| Less manual work | Time-and-motion log of one reconciliation cycle before and after |
| Trust | Share of flagged exceptions that finance confirms as real; whether the spreadsheet is retired |
| Adoption | Weekly active viewers and CSV exports after launch |
| Time saved per cycle | Minutes per monthly reconciliation, before vs after |

## Risks and open questions
- Rules may not match real billing, so definitions need sign-off from finance before launch.
- High false-positive rates would destroy trust; I would review a sample with finance in week one.
- Ownership: who fixes the data when an exception is a source problem, not an invoice problem?
