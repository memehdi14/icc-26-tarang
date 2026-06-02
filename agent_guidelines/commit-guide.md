# Commit Instructions

## Branching Rules

Never work directly on the `main` branch.

Create a feature branch before starting any task:

```bash
git checkout main
git pull origin main
git checkout -b feature/<short-task-name>
```

Examples:

```bash
feature/device-provisioning
feature/mqtt-support
feature/dashboard-ui
```

Bug fixes should use:

```bash
bugfix/<issue-name>
```

Examples:

```bash
bugfix/wifi-timeout
bugfix/mqtt-reconnect
```

---

## Development Workflow

### 1. Sync Latest Changes

```bash
git checkout main
git pull origin main
```

### 2. Create Feature Branch

```bash
git checkout -b feature/<feature-name>
```

### 3. Implement Changes

Keep changes focused on a single feature or bug fix.

### 4. Stage Changes

```bash
git add .
```

### 5. Commit Changes

```bash
git commit -m "<commit-message>"
```

### 6. Push Branch

```bash
git push origin <branch-name>
```

### 7. Open Pull Request

Create a Pull Request targeting:

```text
main
```

### 8. Request Review

At least one teammate must review the Pull Request.

### 9. Merge

Merge only after approval.

### 10. Delete Branch

Delete the feature branch after merging.

---

## Commit Message Guidelines

A commit should represent one logical change.

### Good Examples

```text
Add MQTT device provisioning
Implement OTA firmware update support
Fix WiFi reconnection timeout
Add sensor calibration workflow
Update project documentation
Refactor telemetry processing service
```

### Bad Examples

```text
update
fix
changes
final
new stuff
work done
```

---

## Commit Message Format

Use imperative tense:

```text
Add ...
Fix ...
Update ...
Refactor ...
Remove ...
Implement ...
```

Examples:

```bash
git commit -m "Add UART timeout handling"
git commit -m "Fix MQTT reconnect issue"
git commit -m "Update README setup instructions"
git commit -m "Implement device registration API"
```

---

## Repository Hygiene

Do not commit:

* Build outputs
* Generated code
* Temporary files
* IDE settings
* Secrets
* API keys
* Passwords
* Environment files containing credentials

Examples:

```text
build/
dist/
out/
.vscode/
.idea/
*.log
*.tmp
.env
```

---

## Pull Request Checklist

Before opening a Pull Request:

* [ ] Code builds successfully
* [ ] Changes tested locally
* [ ] No secrets committed
* [ ] Branch rebased with latest main
* [ ] Commit messages are meaningful
* [ ] Documentation updated if required

---

## Rebase Before Merge

Always sync with the latest main branch:

```bash
git fetch origin
git rebase origin/main
```

Resolve conflicts before creating or merging a Pull Request.

---

## Rules Summary

* Never commit directly to `main`
* One feature per branch
* One logical change per commit
* Always use Pull Requests
* Require at least one review
* Rebase before merge
* Delete merged branches
* Keep repository clean
* Write meaningful commit messages
