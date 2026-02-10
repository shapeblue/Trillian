# Playwright QA Portal Database Integration

This document explains how Playwright test results are automatically uploaded to the QA Portal database for centralized tracking and visibility.

## Overview

After Playwright tests complete on the Trillian VM, results are automatically uploaded to the shared QA Portal database at `10.0.113.145`. This allows the team to track UI test results across all PR builds in one place.

## Architecture

```
┌─────────────────┐        ┌──────────────────┐        ┌────────────────┐
│  Playwright VM  │───────>│  QA Portal DB    │<───────│  QA Portal UI  │
│  (Trillian)     │        │  10.0.113.145    │        │  (web app)     │
│                 │        │  cloudstack_tests│        │                │
│  runtests.sh    │        │                  │        │                │
│  ↓              │        │  pr_playwright_  │        │  View results  │
│  upload-to-db.sh│        │  results table   │        │  Screenshots   │
│                 │        │                  │        │  Videos        │
└─────────────────┘        └──────────────────┘        └────────────────┘
         │                          │
         │                          │
         └──────────────────────────┘
          Test results + metadata
          (counts, duration, failures)
```

## Database Schema

Results are stored in the `pr_playwright_results` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT | Auto-increment primary key |
| `pr_number` | INT | GitHub PR number |
| `pr_title` | VARCHAR(500) | PR title |
| `test_suite` | VARCHAR(100) | Test suite name (default: 'ui-tests') |
| `total_tests` | INT | Total number of tests executed |
| `passed_tests` | INT | Number of passing tests |
| `failed_tests` | INT | Number of failing tests |
| `skipped_tests` | INT | Number of skipped tests |
| `duration_ms` | INT | Total test duration in milliseconds |
| `browser` | VARCHAR(50) | Browser used (chromium, firefox, webkit) |
| `failed_test_names` | TEXT | Comma-separated list of failed test names |
| `logs_url` | VARCHAR(500) | **Link to Jenkins HTML report with screenshots/videos** |
| `screenshot_count` | INT | Number of screenshots captured |
| `video_count` | INT | Number of videos recorded |
| `jenkins_build_number` | INT | Jenkins build number |
| `jenkins_job_name` | VARCHAR(200) | Jenkins job name |
| `trillian_env_id` | VARCHAR(100) | Trillian environment ID |
| `test_started_at` | DATETIME | Test execution start time |
| `test_completed_at` | DATETIME | Test execution completion time |
| `inserted_at` | DATETIME | Record creation timestamp |
| `updated_at` | DATETIME | Record update timestamp |

## Setup Instructions

### 1. Create Database Table

Run the migration script on the QA Portal database:

```bash
mysql -h 10.0.113.145 -u results -p'P@ssword123' cloudstack_tests < DBscripts/002_add_playwright_results_table.sql
```

### 2. Configuration (Already Done)

Database credentials are pre-configured in `group_vars/all.sample`:

```yaml
def_playwright_db_host: "10.0.113.145"
def_playwright_db_port: 3306
def_playwright_db_name: "cloudstack_tests"
def_playwright_db_user: "results"
def_playwright_db_pass: "P@ssword123"
```

You can override these per build:

```
ANY_OTHER_BUILD_OPTS: playwright_db_host=10.0.113.145
```

### 3. How It Works

When tests complete, the `runtests.sh` script automatically:

1. **Parses test results** from Playwright JSON output
2. **Extracts metadata**:
   - Test counts (total, passed, failed, skipped)
   - Failed test names
   - Duration
   - Screenshot/video counts
   - PR info (number, title) from Jenkins environment
3. **Uploads to database** using `/playwright/tools/upload-to-db.sh`
4. **Logs success/failure** (database upload failure is non-fatal)

## Viewing Results

### Option 1: Direct Database Query

```sql
SELECT 
  pr_number,
  pr_title,
  total_tests,
  passed_tests,
  failed_tests,
  duration_ms,
  logs_url,
  test_completed_at
FROM pr_playwright_results
ORDER BY test_completed_at DESC
LIMIT 10;
```

### Option 2: QA Portal UI (Future Enhancement)

The QA Portal can be extended to display Playwright results:

1. Add new route: `/ui-tests` or tab on PR dashboard
2. Query `pr_playwright_results` table
3. Display table with:
   - PR number (link to GitHub)
   - Test counts (passed/failed/skipped)
   - Duration
   - **"View Report" button** → opens `logs_url` (Jenkins HTML Publisher)
4. Filter by PR number, date range, pass/fail status

### Option 3: Jenkins HTML Publisher

The `logs_url` field points to the Jenkins HTML Publisher page:

```
http://jenkins/job/Reference_Trillian/123/Playwright_20Test_20Report/
```

This page contains:
- Full HTML test report
- All screenshots (embedded)
- All videos (playable)
- Test execution timeline

## Screenshot/Video Visualization

**Important:** Screenshots and videos are NOT stored in the database. They are stored in Jenkins artifacts and the database only stores the **link** to view them.

### How to Access Artifacts:

1. **Via Database Record:**
   ```sql
   SELECT logs_url FROM pr_playwright_results WHERE id = 123;
   ```
   → Opens Jenkins HTML Publisher page

2. **Via QA Portal UI (future):**
   - Click "View Report" button next to test result
   - Opens Jenkins HTML Publisher in new tab

3. **Direct Jenkins Access:**
   - Go to Jenkins build page
   - Click "Playwright Test Report" link in sidebar
   - Browse HTML report with embedded screenshots/videos

## Troubleshooting

### Database Connection Failed

Check network connectivity from Playwright VM:

```bash
ssh ubuntu@<playwright-vm-ip>
mysql -h 10.0.113.145 -u results -p'P@ssword123' cloudstack_tests -e "SELECT 1;"
```

If it fails:
- Verify database is running: `systemctl status mysql`
- Check firewall rules: port 3306 must be open
- Verify credentials are correct

### Upload Script Not Found

The upload script should be deployed automatically by Ansible. Verify:

```bash
ssh ubuntu@<playwright-vm-ip>
ls -la /playwright/tools/upload-to-db.sh
```

If missing, re-run Playwright role:

```bash
ansible-playbook deployvms.yml --tags playwright
```

### Results Not Appearing in Database

Check the test execution log:

```bash
ssh ubuntu@<playwright-vm-ip>
tail -100 /playwright/logs/runtests.log
```

Look for:
- `✓ Results uploaded to QA Portal database` (success)
- `⚠ Failed to upload results to database` (failure)
- Error messages with details

### Manual Upload

You can manually trigger upload:

```bash
ssh ubuntu@<playwright-vm-ip>
cd /playwright/tools
./upload-to-db.sh 12345 "Test PR Title"
```

## Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `playwright_db_host` | `10.0.113.145` | Database server hostname |
| `playwright_db_port` | `3306` | Database port |
| `playwright_db_name` | `cloudstack_tests` | Database name |
| `playwright_db_user` | `results` | Database username |
| `playwright_db_pass` | `P@ssword123` | Database password |

Override in Jenkins:

```
ANY_OTHER_BUILD_OPTS: playwright_db_host=10.0.200.50 playwright_db_pass=NewPassword
```

## Security Notes

1. **Credentials in plain text:** Database password is stored in plain text in Ansible variables. Consider using Ansible Vault for production.
2. **Network access:** Playwright VM must have network access to database server on port 3306.
3. **Database permissions:** User `results` only needs `INSERT` and `SELECT` permissions on `pr_playwright_results` table.

## Future Enhancements

1. **QA Portal UI Page:**
   - Add dedicated "UI Tests" page to QA Portal
   - Display test results in sortable/filterable table
   - Add trend charts (pass rate over time)
   - Embed screenshots/videos inline (optional)

2. **Test Trends:**
   - Track flaky tests (tests that fail intermittently)
   - Calculate average test duration
   - Alert on regression (sudden increase in failures)

3. **Slack/Email Notifications:**
   - Send notification when UI tests fail
   - Include link to Jenkins report and database record

## Related Documentation

- `docs/playwright-jenkins-reporting.md` - Jenkins HTML Publisher setup
- `Ansible/roles/playwright/README.md` - Playwright role documentation
- `DBscripts/002_add_playwright_results_table.sql` - Database schema
