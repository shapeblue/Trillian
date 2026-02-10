# Playwright Test Reporting Setup (Jenkins)

**For:** `feature/playwright-integration` branch (ephemeral VM approach)  
**Goal:** Display Playwright test reports as clickable HTML links in Jenkins

---

## Overview

When tests run on the Playwright VM, they generate:
- HTML report with test results
- Screenshots of failures
- Videos of test execution

We need to get these artifacts to Jenkins so the team can view them.

**How it works:**
1. Tests run on Playwright VM
2. **BEFORE teardown:** Fetch artifacts to Jenkins workspace
3. Jenkins HTML Publisher displays report
4. Team clicks link: `http://jenkins/job/Trillian/BUILD_NUMBER/Playwright_Test_Report/`

---

## Prerequisites

**Install Jenkins HTML Publisher Plugin:**

1. Go to Jenkins → `Manage Jenkins` → `Manage Plugins`
2. Click `Available` tab
3. Search for "HTML Publisher"
4. Install "HTML Publisher Plugin"
5. Restart Jenkins if prompted

---

## Setup Instructions

### Step 1: Add Artifact Fetch Stage

In your main Trillian Jenkinsfile, add this stage **BEFORE teardown**:

```groovy
stage('Fetch Playwright Artifacts') {
    when {
        expression { params.build_playwright == 'yes' }
    }
    steps {
        script {
            dir('Ansible') {
                sh '''
                    ansible-playbook -i hosts_${BUILD_TAG} fetch-playwright-artifacts.yml
                '''
            }
        }
    }
}
```

**Important:** This must run BEFORE you tear down the Playwright VM!

### Step 2: Add HTML Publisher to Post Section

In your Jenkinsfile `post` section:

```groovy
post {
    always {
        script {
            if (fileExists('playwright-artifacts/playwright-report/index.html')) {
                publishHTML([
                    allowMissing: false,
                    alwaysLinkToLastBuild: true,
                    keepAll: true,
                    reportDir: 'playwright-artifacts/playwright-report',
                    reportFiles: 'index.html',
                    reportName: 'Playwright Test Report',
                    reportTitles: 'Playwright UI Tests'
                ])
                
                echo "✅ Playwright Report: ${env.BUILD_URL}Playwright_Test_Report/"
            }
            
            // Optional: Archive raw artifacts for download
            if (fileExists('playwright-artifacts')) {
                archiveArtifacts artifacts: 'playwright-artifacts/**/*', 
                                 allowEmptyArchive: true
            }
        }
    }
}
```

### Step 3: Wait for Tests to Complete

The tests are scheduled with `at` command (run 1 minute after VM is ready). You need to wait for them to finish before fetching artifacts.

**Option A: Fixed wait time** (simple but not optimal)
```groovy
stage('Wait for Playwright Tests') {
    when {
        expression { params.build_playwright == 'yes' }
    }
    steps {
        echo "Waiting for Playwright tests to complete..."
        sleep time: 5, unit: 'MINUTES'  // Adjust based on test suite size
    }
}
```

**Option B: Poll for completion** (better)
```groovy
stage('Wait for Playwright Tests') {
    when {
        expression { params.build_playwright == 'yes' }
    }
    steps {
        script {
            timeout(time: 15, unit: 'MINUTES') {
                waitUntil {
                    def result = sh(
                        script: """
                            ansible playwright_host -i Ansible/hosts_${BUILD_TAG} -m shell -a 'test -f /playwright/tests/playwright-report/index.html' || echo 'not ready'
                        """,
                        returnStatus: true
                    )
                    return result == 0
                }
            }
        }
    }
}
```

---

## Complete Pipeline Structure

Here's what your pipeline stages should look like:

```
1. Checkout code
2. Deploy Trillian environment
3. Deploy Playwright VM (if build_playwright=yes)
4. Schedule Playwright tests (at command)
5. Wait for Playwright tests to complete ← NEW
6. Fetch Playwright artifacts ← NEW
7. Teardown environment
8. Post: Publish HTML Report ← NEW
```

---

## Testing the Setup

### Run a Test Build

1. Trigger Trillian build with `build_playwright=yes`
2. Wait for build to complete
3. Go to Jenkins build page
4. Look for "Playwright Test Report" link in left sidebar
5. Click it to view interactive HTML report

**Expected result:**
- Clickable link appears in Jenkins UI
- Report opens in new tab
- Shows all test results, screenshots, videos
- Can navigate through test cases

---

## Troubleshooting

### "Playwright Test Report" link doesn't appear

**Check:**
```bash
# In Jenkins build workspace
ls -la playwright-artifacts/playwright-report/index.html
```

If missing:
- Did tests actually run? Check Playwright VM logs: `/playwright/logs/`
- Did fetch stage run? Check Jenkins console output
- Was fetch stage run BEFORE teardown?

### Report shows but has no content

**Likely causes:**
- Tests didn't generate report (failed to run)
- Synchronize didn't copy all files
- Check Jenkins console for errors in fetch stage

### "unable to find valid certification path to requested target"

**Fix in Jenkins:**
```groovy
// Add to Jenkinsfile if you have SSL issues
publishHTML([
    ...
    escapeUnderscores: false,
    reportName: 'Playwright Test Report'
])
```

### Artifacts are huge and filling Jenkins disk

**Add cleanup:**
```groovy
// In post section
post {
    always {
        script {
            // Keep only last 5 builds
            def builds = currentBuild.rawBuild.parent.builds
            if (builds.size() > 5) {
                builds[5..-1].each { build ->
                    build.delete()
                }
            }
        }
    }
}
```

---

## Accessing Reports

### Via Jenkins UI

**Direct link format:**
```
http://jenkins:8080/job/Reference_Trillian/BUILD_NUMBER/Playwright_Test_Report/
```

Example:
```
http://jenkins:8080/job/Reference_Trillian/10892/Playwright_Test_Report/
```

### Via Build Page

1. Go to Jenkins build
2. Look at left sidebar
3. Click "Playwright Test Report"
4. Report opens in new tab

### Download Raw Artifacts

If you enabled `archiveArtifacts`:
```
http://jenkins:8080/job/Reference_Trillian/BUILD_NUMBER/artifact/playwright-artifacts/
```

---

## What You'll See in the Report

**Main page:**
- Test summary (passed/failed/skipped)
- Execution time
- List of all test cases

**For each test:**
- Test name and status
- Execution duration
- Error message (if failed)
- Screenshots of failures
- Video recording of test execution
- Browser console logs

**Interactive features:**
- Filter by status (passed/failed/skipped)
- Search test names
- Click test to see details
- Play video inline
- View screenshots inline

---

## Sharing Reports with Team

**Slack notification example:**

```groovy
// In post section
success {
    script {
        if (params.build_playwright == 'yes') {
            slackSend(
                color: 'good',
                message: "✅ Playwright tests PASSED for ${env.BUILD_TAG}\nReport: ${env.BUILD_URL}Playwright_Test_Report/"
            )
        }
    }
}

failure {
    script {
        if (params.build_playwright == 'yes') {
            slackSend(
                color: 'danger',
                message: "❌ Playwright tests FAILED for ${env.BUILD_TAG}\nReport: ${env.BUILD_URL}Playwright_Test_Report/"
            )
        }
    }
}
```

**Email notification:**

```groovy
post {
    always {
        script {
            if (params.build_playwright == 'yes' && fileExists('playwright-artifacts/playwright-report/index.html')) {
                emailext(
                    subject: "Playwright Tests - ${currentBuild.result} - ${env.BUILD_TAG}",
                    body: """
                        Build: ${env.BUILD_URL}
                        Test Report: ${env.BUILD_URL}Playwright_Test_Report/
                        
                        Status: ${currentBuild.result}
                    """,
                    to: 'qa-team@company.com'
                )
            }
        }
    }
}
```

---

## Notes

- Reports are kept for configured number of builds (default: forever, can be changed in Jenkins job config)
- Each build gets its own report
- Reports are accessible even after environment is torn down
- No need to keep Playwright VM running

---

## Next Steps

After confirming this works:
- [ ] Add Slack/email notifications
- [ ] Set up report retention policy
- [ ] Document for team in wiki
- [ ] Add example screenshots of report to documentation

---

**Questions?** Test with a build and check Jenkins console output for any errors.
