# Île-de-France rail crowding planner

Forecasts how busy Île-de-France rail stations are by day and hour, so travellers can pick a less crowded time slot.

## Language

**Station crowding**:
Expected entries at a **Counting point** or **Place** during a given hour, expressed as a **Crowding score**; the **Expected entries** figure is shown alongside.
_Avoid_: occupancy, load, affluence

**Crowding score**:
Headline 0–100 (or banded) score: expected entries for the hour relative to that station's own **Reference level**. Comparable across time slots at one station, not across stations.

**Reference level**:
One level per station, shared by all day types: the 95th percentile of hourly **Expected entries** over the last 12 months, excluding flagged disruption and holiday days. Fixed between data refreshes. Scores above 100 are allowed and shown as "exceptional".
_Avoid_: per-day-type reference, max

**Expected entries**:
Secondary figure: forecast entries per hour, from raw validations (labelled as such).

**Train load**:
Estimated number of passengers on board a train as it passes a station in a given direction (experimental, not in v0).
_Avoid_: crowding, occupancy

**Trip crowding**:
How crowded a journey from one station to another is at a given time (out of scope; needs origin–destination data).

**Counting point**:
The unit the validation data reports entries for; the domain's "station". Exact granularity to be confirmed in the validation documentation (source #3).
_Avoid_: stop, arrêt, platform

**Place**:
A user-facing grouping of one or more **Counting points** that form one physical location (e.g. a hub split across operators in the data).
_Avoid_: hub, pôle, station (in app copy, use only when one Place = one Counting point)

**Typical week view**:
Hour-by-hour **Crowding score** per **Day type**, with no date; the default view, shipped first.

**Date forecast**:
Hour-by-hour **Crowding score** for a specific future date (up to ~60 days ahead), shown as a delta against the **Typical week view** with its reasons (holidays, weather, planned works). Weather only within its forecast range.
_Avoid_: prediction for past dates

**Day type**:
The category of day that hourly profiles are averaged over (exact categories to be confirmed in the validation documentation).

## Relationships

- A **Date forecast** = daily forecast for that date × the hourly profile of its **Day type**.

- A **Place** groups one or more **Counting points**; a **Counting point** belongs to exactly one **Place**.
- **Place** values are sums of their **Counting points**; entries are never split by line.
- **Station crowding** is derived from entries at one **Counting point** (or summed over a **Place**); **Train load** would aggregate entries from upstream stations along a line.

## Example dialogue

> **Dev:** "The user picked Gare de Lyon on line 1 eastbound. Do we show **Train load**?"
> **Domain expert:** "No. v0 shows **Station crowding** for Gare de Lyon only. Line and direction don't change it."

> **Dev:** "Saturday 15h scores 30 and Tuesday 8h scores 90 at the same station. Is Saturday's peak not 100?"
> **Domain expert:** "No. There's one **Reference level** per station for the whole week, so 30 means Saturday afternoon is far quieter than a weekday rush."

## Flagged ambiguities

- "validation" may cover entries, transfers (gates between metro and RER inside a hub) and exits. v0 assumes **entries**; pending: confirm in the documentation PDF. If transfers are included, **Place** sums may double-count and hub scores are labelled "includes transfers".

- "station" was used for counting points, per-line stops and app picks. Resolved: **Counting point** (data unit) vs **Place** (display grouping); no per-line split. Pending: verify granularity in the documentation PDF.
- "crowding" was used for station entries (Phase 6 v1), train load (v2) and trip experience (app input). Resolved: v0 means **Station crowding** only.
