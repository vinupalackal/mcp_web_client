# GitHub Tracker — User Guide

**Feature:** GitHub Milestone and Issue Workflow for Milvus Delivery  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Repository:** `vinupalackal/mcp_web_client`

---

## Table of Contents

1. [Overview](#1-overview)
2. [What You Use Day to Day](#2-what-you-use-day-to-day)
3. [Typical Delivery Workflow](#3-typical-delivery-workflow)
4. [How to Update the Tracker](#4-how-to-update-the-tracker)
5. [Recommended Status and Commenting Practices](#5-recommended-status-and-commenting-practices)
6. [Using the Tracker from GitHub CLI](#6-using-the-tracker-from-github-cli)
7. [Using the Tracker from the GitHub Web UI](#7-using-the-tracker-from-the-github-web-ui)
8. [Milestone-by-Milestone Usage in This Repo](#8-milestone-by-milestone-usage-in-this-repo)
9. [Common Scenarios](#9-common-scenarios)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

This guide explains how to **use and update** the GitHub tracker after it has been set up.

In this repository, the tracker is used to manage Milvus work from planning through merge. It provides a simple operational loop:

```text
Milestone → Issue → Branch → Commit / PR → Review → Merge → Issue closed
```

The tracker should reflect the real state of implementation work at all times.

---

## 2. What You Use Day to Day

Most contributors will interact with only four GitHub concepts:

| Item | How it is used |
|---|---|
| Milestone | shows the phase or release bucket for a task |
| Issue | tracks one implementation task |
| Label | helps filter by phase, area, or work type |
| Pull Request | delivers the change and closes the issue |

For Milvus work, always start from an existing milestone and issue whenever possible.

---

## 3. Typical Delivery Workflow

### 3.1 Pick the Next Issue

Choose the next open issue from the active milestone.

Example:
- `M1 - Foundations` → `M1: Add provider-agnostic embedding support`

### 3.2 Create a Branch

Example:

```bash
git checkout -b feat/m1-provider-agnostic-embedding
```

### 3.3 Implement the Change

Make the code, test, and doc changes required by the issue.

### 3.4 Reference the Issue

Use the issue number in your commits or PR description.

Examples:

```text
Refs #4
Closes #4
```

### 3.5 Open a Pull Request

Create a PR that clearly states:
- what was changed,
- which issue it addresses,
- what was tested,
- whether follow-up work remains.

### 3.6 Merge and Verify Closure

After merge:
- confirm the linked issue is closed,
- confirm milestone progress increased,
- and check whether follow-up issues should be opened.

---

## 4. How to Update the Tracker

### 4.1 Add a Progress Comment

When meaningful progress is made, add a concise update comment to the issue.

Good progress comments include:
- implementation started,
- module scaffolded,
- tests added,
- PR opened,
- blocker discovered,
- scope narrowed or split.

Example:

```text
Started implementation for EmbeddingService.
- Added provider-normalized request path
- Reused llm_client timeout handling
- Unit tests pending before PR
```

### 4.2 Update Labels

If work expands or narrows, update labels to keep filtering accurate.

Examples:
- add `tests` when test coverage work is included,
- add `docs` when README or operator documentation changes are required,
- keep the original phase label unless the issue is explicitly moved.

### 4.3 Move an Issue to Another Milestone

Only do this when the scope actually shifts.

Example:

```bash
gh issue edit 12 --repo vinupalackal/mcp_web_client --milestone 'M4 - Phase 1 Release'
```

### 4.4 Split Work into a Follow-Up Issue

If an issue becomes too large:
1. keep the current issue focused,
2. open a new follow-up issue,
3. link the two in comments,
4. keep acceptance criteria clean.

### 4.5 Close the Issue

Close the issue only when the acceptance criteria are satisfied and the change is merged.

---

## 5. Recommended Status and Commenting Practices

### 5.1 What “In Progress” Means

GitHub Issues do not have a native built-in status field in the basic issue model, so in this repository “in progress” is represented by one or more of:
- an assignee,
- an active branch,
- an open PR linked to the issue,
- a recent progress comment.

### 5.2 Comment Only When It Adds Signal

Good comments:
- explain design choices,
- document blockers,
- point to a PR,
- clarify why scope changed,
- record why an acceptance criterion moved.

Avoid comments that add little value, such as:
- “starting now”,
- “done soon”,
- “checking”.

### 5.3 Keep Acceptance Criteria Honest

If acceptance criteria change, update the issue body so the tracker remains a trustworthy source of delivery state.

---

## 6. Using the Tracker from GitHub CLI

### 6.1 List All Open Milvus Issues

```bash
gh issue list --repo vinupalackal/mcp_web_client --label milvus --state open --limit 100
```

### 6.2 List Issues for One Milestone

```bash
gh issue list --repo vinupalackal/mcp_web_client --milestone 'M3 - Chat Integration' --state open
```

### 6.3 View One Issue

```bash
gh issue view 9 --repo vinupalackal/mcp_web_client
```

### 6.4 Comment on an Issue

```bash
gh issue comment 9 --repo vinupalackal/mcp_web_client --body 'Retrieval service scaffolded. Starting test coverage next.'
```

### 6.5 Edit Labels

```bash
gh issue edit 9 --repo vinupalackal/mcp_web_client --add-label tests
```

### 6.6 Close an Issue

```bash
gh issue close 9 --repo vinupalackal/mcp_web_client --comment 'Merged via PR #123. Acceptance criteria complete.'
```

### 6.7 Reopen an Issue

```bash
gh issue reopen 9 --repo vinupalackal/mcp_web_client --comment 'Reopened because degraded-mode coverage is still incomplete.'
```

---

## 7. Using the Tracker from the GitHub Web UI

If you prefer the browser workflow:

1. Open the repository on GitHub
2. Go to **Issues**
3. Filter by label or milestone
4. Open the issue you are working on
5. Add comments, labels, milestone changes, or assignees as needed
6. Open or review the linked PR

The GitHub web UI is especially useful for:
- milestone progress bars,
- quick triage,
- editing issue descriptions,
- browsing related PRs and comments.

---

## 8. Milestone-by-Milestone Usage in This Repo

### `M1 - Foundations`
Use this for early scaffolding work such as:
- dependencies,
- schema additions,
- models,
- embedding service,
- persistence layer.

### `M2 - Milvus + Ingestion`
Use this for:
- Milvus store logic,
- collection lifecycle,
- ingestion pipeline,
- ingestion/store test coverage.

### `M3 - Chat Integration`
Use this for:
- retrieval orchestration,
- `backend/main.py` request-path wiring,
- health reporting,
- degraded-mode behavior,
- session trace helpers,
- integration tests.

### `M4 - Phase 1 Release`
Use this for:
- README updates,
- operator guidance,
- optional UI signal,
- release-readiness clean-up.

### `M5 - Conversation Memory`
Use this for:
- same-user recall,
- workspace-scoped memory,
- retention controls,
- memory isolation testing.

### `M6 - Safe Tool Cache`
Use this for:
- allowlisted cache behavior,
- deterministic cache key policy,
- provenance and audit data,
- cache safety tests.

---

## 9. Common Scenarios

### Scenario A — You are starting a new Milvus task

1. Find the next open issue in the active milestone
2. Assign yourself if your team uses assignees
3. Create a branch
4. Add a progress comment only if helpful
5. Open a PR that references the issue

### Scenario B — One issue became too large

1. Keep the current issue limited to its original acceptance criteria
2. Create a follow-up issue for the new scope
3. Link the issues together in comments
4. Put the follow-up into the correct milestone

### Scenario C — A blocker stops progress

Add a clear blocker comment:

```text
Blocked on Milvus collection schema finalization.
Need decision on payload-ref metadata before continuing search/upsert implementation.
```

If needed, open a small design or decision issue and link it.

### Scenario D — A PR only partially finishes the issue

Do not close the issue automatically unless the remaining work is moved to a new issue.

Preferred options:
- keep the issue open,
- or split the unfinished acceptance criteria into a follow-up issue.

---

## 10. Troubleshooting

**The issue does not close after merge**  
→ Confirm the PR description or merged commit used a closing keyword such as `Closes #9`.

**An issue is closed too early**  
→ Reopen it and leave a short note explaining what remains.

**The wrong milestone is showing progress**  
→ Check whether the issue was assigned to the wrong milestone.

**Too many issues show up in filters**  
→ Filter by both `milvus` and a phase label, or by milestone.

**The tracker no longer matches the implementation plan**  
→ Update the issue bodies and milestone scopes to match `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`.

---

## Summary

Use the GitHub tracker as the live execution view for Milvus delivery:
- milestones show phase progress,
- issues show task progress,
- labels keep work filterable,
- PR references keep implementation and planning connected.

If the tracker stays aligned with the implementation plan and actual merged work, it becomes a reliable source of project status for Milvus Phase 1A through Phase 3.
