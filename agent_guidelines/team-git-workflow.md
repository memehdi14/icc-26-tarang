# Team Git Workflow

Use this workflow for every code or documentation change in the Tarang repository.

## The short version

Do not make normal development changes directly on `main`.

Create a small branch, add your work there, push it, open a pull request, get one teammate review, then merge into `main`.

## Branch names

Use one of these formats:

```text
feature/<short-task-name>
bugfix/<issue-name>
```

Examples:

```text
feature/ecg-pipeline
feature/ble-dashboard
feature/ml-training-notebook
bugfix/ble-reconnect
bugfix/ecg-noise-filter
```

## Step-by-step workflow

### 1. Start from main

```bash
git checkout main
git pull origin main
```

### 2. Create a branch

```bash
git checkout -b feature/<short-task-name>
```

Example:

```bash
git checkout -b feature/ecg-filter
```

### 3. Add your code

Keep each branch focused on one task.

Good examples:

- Add ECG filtering code
- Update the firmware README
- Add BLE reconnect handling
- Improve the ML notebook

Avoid mixing unrelated changes in one branch.

### 4. Check what changed

```bash
git status
```

Review the file list before committing. Do not commit generated files, SDK folders, datasets, virtual environments, build outputs, PDFs, PPTs, or secrets.

### 5. Commit your work

```bash
git add .
git commit -m "Add ECG filter"
```

Use a short, meaningful commit message in imperative form:

```text
Add ...
Fix ...
Update ...
Refactor ...
Remove ...
Implement ...
```

### 6. Push your branch

```bash
git push origin feature/<short-task-name>
```

Example:

```bash
git push origin feature/ecg-filter
```

### 7. Open a Pull Request

On GitHub, open a pull request from your branch into:

```text
main
```

Use the pull request template and explain:

- What changed
- How it was tested
- Any files or behavior reviewers should check carefully

### 8. Get review

At least one teammate should review and approve the pull request before it is merged.

If there are requested changes, update the same branch and push again.

### 9. Merge into main

After approval, merge the pull request into `main`.

### 10. Delete the branch

After the pull request is merged, delete the feature or bugfix branch on GitHub.

## Before opening a pull request

Use this checklist:

- [ ] My branch name follows `feature/...` or `bugfix/...`
- [ ] The change is focused on one task
- [ ] The project builds or the documentation renders correctly
- [ ] I did not commit generated outputs
- [ ] I did not commit secrets, API keys, datasets, virtual environments, or SDK folders
- [ ] My commit message is meaningful
- [ ] I pulled or rebased against the latest `main`

## Repository layout reminder

Software projects live under:

```text
projects/
  tarang-firmware/
  tarang-ml/
```

Keep repository-level files such as `README.md`, `LICENSE.md`, and `.github/` at the root.
