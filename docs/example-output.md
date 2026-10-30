# Test case drafts

Status: **unapproved; not executed**.

Source-claim confirmation is supplied by the input author. This compiler does not verify source truth or completeness.

Phase: core. Cases: 4. Generation issues: 0. Backlog items: 1.

## TASK-051590dad33a5342: Filter tasks with All

Claims: CL-FILTER, CL-RESET. Status: unapproved; not executed.

Preparation:

- Reset the synthetic fixture to active tasks A and B and completed task C. Required state: Sample tasks loaded.

Steps:

1. Select the All filter.
   Expected: Tasks A, B and C are visible.

## TASK-64bad294e69bbc5a: Filter tasks with Active

Claims: CL-FILTER, CL-RESET. Status: unapproved; not executed.

Preparation:

- Reset the synthetic fixture to active tasks A and B and completed task C. Required state: Sample tasks loaded.

Steps:

1. Select the Active filter.
   Expected: Only tasks A and B are visible.

## TASK-a1ce38bdd370a122: Filter tasks with Completed

Claims: CL-FILTER, CL-RESET. Status: unapproved; not executed.

Preparation:

- Reset the synthetic fixture to active tasks A and B and completed task C. Required state: Sample tasks loaded.

Steps:

1. Select the Completed filter.
   Expected: Only task C is visible.

## TASK-e62daab2a5e6f8a8: Complete and archive an active task

Claims: CL-ARCHIVE, CL-COMPLETE, CL-RESET. Status: unapproved; not executed.

Preparation:

- Reset the synthetic fixture to active tasks A and B and completed task C. Required state: Sample tasks loaded.

Steps:

1. Mark active task A as complete.
   Expected: Task A shows Completed.
2. Archive task A.
   Expected: Task A is absent from the default list and present in the archive.

## Deferred or unresolved scope

- O-SYNC (gap_rule): Determine archive synchronization behavior. — R5 leaves the external synchronization rule undefined.
