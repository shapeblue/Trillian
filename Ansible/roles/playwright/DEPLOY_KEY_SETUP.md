# Playwright GitHub Deploy Key Setup

## Overview
The Playwright VM requires a GitHub deploy key to clone the private test repository. For security, this key is **never committed to git**. Instead, it's stored in Jenkins credentials and injected at build time.

## One-Time Setup (Jenkins Administrator)

### Step 1: Generate Deploy Key (Local)
```bash
ssh-keygen -t ed25519 -C "trillian-playwright-deploy" -f playwright_deploy_key -N ""
```

### Step 2: Add Public Key to GitHub
1. Copy the public key: `cat playwright_deploy_key.pub`
2. Go to: https://github.com/shapeblue/cloudstack-ui-automation/settings/keys
3. Click "Add deploy key"
4. **Title**: `Trillian Playwright VM`
5. **Key**: Paste the public key
6. **Allow write access**: **UNCHECK** (read-only)
7. Click "Add key"

### Step 3: Store Private Key in Jenkins
1. Go to Jenkins: `Manage Jenkins` → `Credentials` → `Global credentials`
2. Click "Add Credentials"
3. **Kind**: Secret text
4. **Scope**: Global
5. **Secret**: Paste the **entire private key** (including `-----BEGIN` and `-----END` lines)
6. **ID**: `playwright-github-deploy-key`
7. **Description**: `GitHub deploy key for Playwright test repository (read-only)`
8. Click "Create"

### Step 4: Update Jenkins Job
Add to the Trillian job's "Build Environment" section:
1. Check "Use secret text(s) or file(s)"
2. Add "Secret text" binding:
   - **Variable**: `PLAYWRIGHT_GITHUB_KEY`
   - **Credentials**: Select `playwright-github-deploy-key`

## How It Works
- Jenkins injects the private key as environment variable `PLAYWRIGHT_GITHUB_KEY`
- Ansible reads it during deployment: `{{ lookup('env', 'PLAYWRIGHT_GITHUB_KEY') }}`
- Key is deployed to `/root/.ssh/id_rsa_playwright` on the VM
- Git clone uses this key automatically via SSH config
- Key never touches git repository

## Security Benefits
- ✅ Key never committed to version control
- ✅ Encrypted at rest in Jenkins credentials store
- ✅ Audit trail via Jenkins logs
- ✅ Easy rotation without code changes
- ✅ Role-based access control (only Jenkins admins see it)
- ✅ Complies with GitHub's secret scanning policies

## For Team Members
No action required. Once Jenkins is configured, builds automatically receive the deploy key. Team members trigger builds normally without any credential management.
