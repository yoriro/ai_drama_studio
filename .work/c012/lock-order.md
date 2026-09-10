# C012 lock-order diagnostic (T03)

Baseline: production checkout `9bb0c18` (application code unchanged from
`c0830c34c05bb53b3111d39eb52b05bebd11a8d3`).  T04 rechecked the map after the
source-order change.  This is a diagnostic map, not a new database lock or a
statement that the probe has passed.  The intended
common order from C012 §2 is:

`Episode` → `Asset` (ascending id) → `Shot` (ascending id) → `Clip`
(ascending id) → the target relationship/media rows.

Only rows that the operation actually needs may be locked.  Candidate ids can
be discovered before the lock, but ownership, revision, and references must be
read again after the lock.

## Current explicit edges

| case | operation | current explicit row-lock edges | conflict observed by the probe |
|---|---|---|---|
| L1 | `enqueue_generate_clip_video` | enabled slot assets → Clip (`backend/app/services/generate_clip_video.py:554-558`) | Asset → Clip |
| L1 | `commit_generated_clip_video` | Task → Episode → Asset (ascending id) → Shot (ascending id) → Clip → ClipVideo (`backend/app/services/clip_video_commit.py:214-272`) | Baseline Clip → Shot → Asset; T04 source order now follows the common order |
| L2 | asset edit/current/delete | edit/current: Asset → dependent bulk Shot/Clip updates; delete: Episode → Shot → Asset → AssetImage (`backend/app/services/assets.py:85-136`, `179-205`, `391-422`, `452-483`) | Asset-path mutations can wait on a Clip/Shot already held by commit while commit waits on Asset |
| L2 | video commit | Task → Clip → Shot → Asset → ClipVideo (`backend/app/services/clip_video_commit.py:214-272`) | reverse edge against asset-dependent mutation |
| L3 | shot text/binding edit | Episode → Shot → Asset → dependent Clip update (`backend/app/services/shots.py:69-147`) | Shot → Asset against commit's Clip → Shot → Asset |
| L3 | video commit | Task → Clip → Shot → Asset (`backend/app/services/clip_video_commit.py:214-272`) | Clip → Shot |
| L4 | clip create/slot/delete | create selection locks Episode/Shot/Asset and then relation/Clip rows (`backend/app/services/clips.py:206-285`, `353-435`); delete locks Clip, relation rows, Shot, slots, and videos (`backend/app/services/clips.py:884-990`) | relation and source-row order differs by entry point |
| L4 | source mutation | shot/asset operations lock their source rows before dependent Clip updates | the same Clip/Shot/Asset cycle can be reached through a slot-only asset |
| L5 | `gen_shots` replacement | Episode → Shot → Clip → ClipVideo/slot override, then output Assets (`backend/app/tasks/gen_shots.py:155-235`, `253-273`) | API edits can acquire Asset/Shot/Clip in the opposite order |
| L5 | API edits | see L2–L4 rows above | replacement can observe a mixed lock order unless its source rows are locked first in the common order |

The `Task` lock in video commit is a condition/terminal-state guard and must
remain.  It must not be used to add a second wait on an unrelated active Task
while the target Clip is held.  PostgreSQL also takes implicit row/index locks
for `UPDATE`/`DELETE`, foreign-key checks, and the existing unique indexes
`uq_clip_shots_shot`, `uq_clip_shots_position`, current-media indexes, and the
active-task indexes.  The probe records those waits through
`pg_stat_activity`, `pg_locks`, and `pg_blocking_pids`; it does not treat a
statement timeout as a successful ordering result.

## Existing assertions that must remain true

- `backend/tests/task_system/test_c009_clip_video_commit.py` keeps atomic MP4
  commit, probed duration, cache-hit/current-take, source revision, cancel
  winner, compensation, and exact task-state assertions.
- `backend/tests/task_system/test_c009_enqueue_locks.py` keeps shot-bound and
  slot-only asset waits, post-lock snapshot values, stale/changed projection,
  and project/style/template lock barriers.
- C006 replacement/cancel tests keep the old-structure-on-failure and one
  atomic cancellation winner assertions.
- The C012 probe must compare both scheduling directions with the same fixture;
  it must report complete rows and media paths, not just “no exception”.

## T03 evidence boundary

The independent test uses real PostgreSQL connections, the production
`enqueue_generate_clip_video` and `commit_generated_clip_video` seams, and an
offline valid MP4 only for the file input.  A deterministic barrier is placed
after the production lock statement; a separate read-only connection records
the waiter and blockers.  L1 is expected to be red at this baseline because
the two operations can hold Asset and Clip in opposite order.  No T03 result
is a production lock fix or a real GPU/browser result.

## T04 result

`backend/app/services/clip_video_commit.py` now locks the snapshot Episode,
source Assets, source Shots, and target Clip in that order after the Task
condition check, then uses those locked rows for source comparison.  The T04
L1 probe completed commit-first and enqueue-first with one done task, one
queued follow-up, one current formal take, and no temporary file.  The C009
commit/enqueue regression completed 24 tests.  Raw evidence is in
`.work/c012/T04-L1.stdout.log`, `.work/c012/T04-C009.stdout.log`, and
`.work/c012/locks-acceptance.json`.
