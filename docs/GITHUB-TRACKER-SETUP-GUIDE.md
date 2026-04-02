# GitHub Tracker Setup Guide

**Feature:** GitHub Milestone and Issue Tracker for Milvus Integration  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Repository:** `vinupalackal/mcp_web_client`

---

## Table of Contents

1. [Overview](#1-overview)
2. [What This Tracker Contains](#2-what-this-tracker-contains)
3. [Prerequisites](#3-prerequisites)
4. [One-Time Setup](#4-one-time-setup)
5. [Repository-Specific Tracker Structure](#5-repository-specific-tracker-structure)
6. [Verification Checklist](#6-verification-checklist)
7. [Recommended Team Conventions](#7-recommended-team-conventions)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Overview

This guide explains how to set up and verify the **GitHub tracker** used for the Milvus integration work in this repository.

In this project, the GitHub tracker is the combination of:
- **Milestones** for phase-level planning,
- **Issues** for implementation tasks,
- **Labels** for filtering and reporting,
- and optional **pull request references** for automatic issue closure.

The tracker is designed to mirror the delivery structure defined in:
- `Milvus_MCP_Integration_Requirements.md`
- `docs/MILVUS_MCP_INTEGRATION_HLD.md`
- `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 2. What This Tracker Contains

The Milvus tracker is organized around **6 milestones**:

| Milestone | Purpose |
|---|---|
| `M1 - Foundations` | dependency, schema, model, embedding, and persistence scaffolding |
| `M2 - Milvus + Ingestion` | Milvus store, indexing pipeline, and ingestion tests |
| `M3 - Chat Integration` | retrieval orchestration, health integration, and runtime-safe chat wiring |
| `M4 - Phase 1 Release` | docs, optional UI visibility, and release-readiness tasks |
| `M5 - Conversation Memory` | same-user long-term conversation memory |
| `M6 - Safe Tool Cache` | allowlisted, provenance-aware cache behavior |

It also uses labels such as:
- `milvus`
- `phase-1a`, `phase-1b`, `phase-1c`, `phase-1d`, `phase-2`, `phase-3`
- `backend`, `frontend`, `docs`, `tests`

---

## 3. Prerequisites

Before you manage the tracker, make sure you have:

1. A GitHub account with write access to `vinupalackal/mcp_web_client`
2. Git installed locally
3. GitHub CLI (`gh`) installed
4. Authentication completed for `github.com`

### 3.1 Install GitHub CLI

On macOS with Homebrew:

```bash
brew install gh
```

### 3.2 Authenticate GitHub CLI

Run:

```bash
gh auth login --web --git-protocol ssh --hostname github.com
```

This opens the GitHub device login flow in your browser and configures `gh` to work with the repository over SSH.

### 3.3 Confirm Authentication

```bash
gh auth status
gh repo view vinupalackal/mcp_web_client
```

You should see that you are logged in as your GitHub user and that the repository is accessible.

---

## 4. One-Time Setup

If the tracker does not already exist, perform the following steps.

### 4.1 Create Milestones

Create the six Milvus milestones in GitHub:

- `M1 - Foundations`
- `M2 - Milvus + Ingestion`
- `M3 - Chat Integration`
- `M4 - Phase 1 Release`
- `M5 - Conversation Memory`
- `M6 - Safe Tool Cache`

You can create milestones either:
- in the GitHub web UI, or
- with `gh api` / `gh issue create` flows

### 4.2 Create Labels

Recommended labels for this repository’s Milvus work:

| Label | Purpose |
|---|---|
| `milvus` | all Milvus tracking items |
| `phase-1a` | foundations scope |
| `phase-1b` | Milvus + ingestion scope |
| `phase-1c` | chat integration scope |
| `phase-1d` | docs and optional UI scope |
| `phase-2` | conversation memory scope |
| `phase-3` | safe cache scope |
| `backend` | backend implementation work |
| `frontend` | frontend/UI work |
| `docs` | documentation work |
| `tests` | validation and automated coverage |

### 4.3 Create Issues from the Implementation Plan

Use `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md` as the source of truth for issue creation.

Recommended pattern for each issue:
- clear task title,
- short scope section,
- acceptance criteria,
- milestone assignment,
- labels for phase and work type.

### 4.4 Link PRs to Issues

When you create a pull request, reference the issue in the PR description or commit message.

Examples:

```text
Closes #9
Refs #10
```

This allows GitHub to automatically close issues when the PR is merged.

---

## 5. Repository-Specific Tracker Structure

The current tracker is aligned to the implementation plan in `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`.

### 5.1 Milestone-to-Phase Mapping

| Phase | Milestone |
|---|---|
| Phase 1A | `M1 - Foundations` |
| Phase 1B | `M2 - Milvus + Ingestion` |
| Phase 1C | `M3 - Chat Integration` |
| Phase 1D | `M4 - Phase 1 Release` |
| Phase 2 | `M5 - Conversation Memory` |
| Phase 3 | `M6 - Safe Tool Cache` |

### 5.2 Recommended Issue Granularity

Keep issues small enough to review and close independently.

Good examples:
- one backend module,
- one schema addition,
- one test suite,
- one documentation slice,
- one integration step in `backend/main.py`.

Avoid combining unrelated work such as:
- dependency installation + Milvus store + chat integration in one issue,
- backend implementation + frontend UI + docs in one issue.

### 5.3 Suggested Branch Naming

Use milestone-aware branch names such as:

```bash
feat/m1-embedding-service
feat/m2-ingestion-service
feat/m3-chat-retrieval
fix/m3-degraded-mode
```

---

## 6. Verification Checklist

After setup, verify the tracker with the following commands.

### 6.1 List Milestones

```bash
gh api 'repos/vinupalackal/mcp_web_client/milestones?state=open&per_page=100'
```

### 6.2 List Milvus Issues

```bash
gh issue list --repo vinupalackal/mcp_web_client --label milvus --state open --limit 100
```

### 6.3 List Issues in a Specific Milestone

```bash
gh issue list --repo vinupalackal/mcp_web_client --milestone 'M1 - Foundations' --state open
```

### 6.4 Check Issue Details

```bash
gh issue view 9 --repo vinupalackal/mcp_web_client
```

### 6.5 Confirm Labels Exist

```bash
gh label list --repo vinupalackal/mcp_web_client
```

If all milestone, issue, and label sets appear correctly, the tracker setup is complete.

> **Note:** For large issue body edits, avoid long heredoc-based shell commands. Prefer `gh issue edit --body-file /tmp/file.md` or `gh api --input /tmp/payload.json`, then re-read the issue to verify the final body. See `docs/GITHUB-TRACKER-USER-GUIDE.md` for the full safe-edit workflow.

---

## 7. Recommended Team Conventions

### 7.1 Keep the Plan and Tracker in Sync

If the implementation plan changes materially, update:
1. `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`
2. the affected GitHub issues
3. milestone scope if needed

### 7.2 Close Issues Only on Done Criteria

Do not close an issue when coding has merely started. Close it only when:
- implementation is merged,
- tests relevant to the change pass,
- and documentation is updated when required.

### 7.3 Use Comments for Progress Notes

Use issue comments for meaningful updates such as:
- design decision made,
- dependency blocked,
- tests added,
- PR opened,
- scope split into follow-up issue.

### 7.4 Prefer Explicit Acceptance Criteria

Each issue should make it obvious what “done” means. This keeps milestone progress meaningful and reduces ambiguity during review.

---

## 8. Troubleshooting

**`gh: command not found`**  
→ Install GitHub CLI with `brew install gh`.

**`You are not logged into any GitHub hosts`**  
→ Run `gh auth login --web --git-protocol ssh --hostname github.com`.

**Repository access denied**  
→ Confirm you have write access to `vinupalackal/mcp_web_client` and that your SSH key is registered with GitHub.

**Milestones are missing**  
→ Recreate them manually in GitHub or via `gh api` using the milestone titles in this guide.

**Issue is in the wrong milestone**  
→ Edit the issue in the GitHub UI or run:

```bash
gh issue edit <issue-number> --repo vinupalackal/mcp_web_client --milestone 'M3 - Chat Integration'
```

**Labels are inconsistent**  
→ Standardize on the labels listed in [Section 4.2](#42-create-labels) and remove ad hoc variants.

---

## Summary

The Milvus GitHub tracker is intended to be the execution layer for the repository’s Milvus requirements, HLD, and implementation plan.

Once set up correctly, it gives the team:
- milestone-level progress visibility,
- issue-level execution tracking,
- cleaner PR-to-task traceability,
- and a repeatable delivery workflow for Phases 1A through 3.
