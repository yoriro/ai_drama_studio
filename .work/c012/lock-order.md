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
| L2 | asset edit/current/delete | candidate Episode locks → Asset → current dependent Shots → current dependent Clips → AssetImage/media (`backend/app/services/assets.py:49-181`, `207-232`, `422-454`, `481-521`); slot-only assets omit Shots | T05 uses the same order for shot-bound and slot-only assets; locked relationships are re-read before dependent updates |
| L2 | video commit | Task → Episode → Asset → Shot → Clip → ClipVideo (`backend/app/services/clip_video_commit.py:214-272`) | T04 removed the reverse source edge |
| L3 | shot text/binding edit | candidate current/requested Assets → Episode → Asset (ascending id) → Shot → related Clips (`backend/app/services/shots.py:69-176`) | T06 re-reads the current ShotAsset rows after parent locks before applying binding changes |
| L3 | video commit | Task → Episode → Asset → Shot → Clip (`backend/app/services/clip_video_commit.py:214-272`) | both paths now share the source-row order |
| L4 | clip create/slot/delete | create discovers candidates then locks Episode → Asset (ascending id) → Shot (ascending id) → occupied Clip (ascending id) before writing relations; slot enabled locks Clip → slot; slot override locks Episode → Clip → slot; delete locks Episode → Shot (ascending id) → Clip → ClipShot/slot/ClipVideo (`backend/app/services/clips.py:206-333`, `353-435`, `707-920`) | T07 exercises create conflict, slot mutation, and delete/media winners in both scheduling directions |
| L4 | source mutation | shot/asset operations lock their source rows before dependent Clip updates | T07 keeps the same Clip/Shot/Asset order and does not add a project-wide lock |
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

## T05 result

`backend/app/services/assets.py` now discovers episode dependencies before any
row lock, locks `Episode → Asset → Shot → Clip`, and obtains current
dependent IDs after each parent-level lock.  Asset patch, current-image, and
delete were exercised for both shot-bound and slot-only assets in both start
directions; each produced one committed video, a stale Clip, and the expected
revision/slot result.  The existing C009 enqueue-lock regression completed 13
tests.  Raw evidence is `.work/c012/T05-L2.stdout.log`,
`.work/c012/T05-C009.stdout.log`, and the L2 event in
`.work/c012/locks-acceptance.json`.

## T06 result

`backend/app/services/shots.py` now discovers current and requested asset IDs
without locks, then locks the Episode, Assets, Shot, and related Clips in
ascending order.  Text and binding edits were each interleaved with the real
video commit in both start directions; the resulting Shot was revision
2/changed, the Clip stale, and one committed take remained.  Raw evidence is
`.work/c012/T06-L3.stdout.log`.

## T07 result

`backend/app/services/clips.py` now takes the common source locks before
Clip for create selection, uses Episode → Clip → slot for slot overrides, and
uses Episode → Shot → Clip before relationship and media rows for deletion.
The lock-after reads validate the current clip identity and current ClipShot
set before mutating.  The L4 probe exercised create conflict, slot mutation,
and deletion with the real video commit in both scheduling directions; it
left create at HTTP 422, preserved one Clip for the conflict case, kept the
slot mutation at revision 2/stale with one committed take, and removed the
delete winner's Clip/relations while retaining source Shots and moving the
video to trash.  B L4 completed 1 test; the existing C009 enqueue-lock suite
completed 13 tests.  R `locks --case L4` completed with child returncode 0,
`timed_out=false`, and `scheduled_case=false` against the T01 database.
Raw evidence is `.work/c012/T07-L4-final3.stdout.log`,
`.work/c012/T07-C009-final.stdout.log`,
`.work/c012/T07-acceptance-final3.stdout.log`, and
`.work/c012/locks-acceptance.json`.
