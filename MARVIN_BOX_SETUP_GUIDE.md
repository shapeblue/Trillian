# Marvin Box Virtual Machine Setup Guide

## Overview
This guide explains how to create a Marvin Box virtual machine in the Trillian project for use as a UI automation test control plane.

## What is a Marvin Box?

A Marvin Box is a dedicated virtual machine that Trillian deploys to run CloudStack integration tests. It comes pre-configured with:
- **Marvin** - CloudStack's integration testing framework
- **CloudMonkey** - CloudStack CLI tool
- **Test suites** - Smoke tests, component tests, and integration tests
- **iSCSI target** - For storage testing
- **Test configuration** - Pre-generated test data and environment-specific configs

## Prerequisites

1. A working parent CloudStack environment
2. Ansible 2.x installed
3. CloudMonkey configured and pointing to your parent cloud
4. Required templates available in parent cloud:
   - **Marvin template**: Default name is "Marvin iSCSI"
   - Service offering: Default name is "Marvin"
5. Network configured: Default is specified in `def_marvin_network` variable

## Quick Start - Creating a Marvin Box

### Step 1: Configure Your Environment Variables

First, copy and configure the group_vars file:

```bash
cd Ansible
cp group_vars/all.sample group_vars/all
```

Edit `group_vars/all` and set the Marvin-specific variables:

```yaml
# Marvin VM Configuration
def_marvin_username: "root"                          # SSH username
def_marvin_password: "P@ssword123"                   # SSH password
def_marvin_network: "your-network-name"              # Network name in parent cloud
def_marvin_service_offering: "Marvin"                # Service offering name
def_marvin_server_template: "Marvin iSCSI"          # Template name in parent cloud
def_marvin_tests_source: "github"                    # Source for tests
def_marvin_tests_github_source: "https://github.com/apache/cloudstack"
def_marvin_images_location: "http://your-ip/marvin" # Test images location
```

### Step 2: Generate Environment Configuration

Run the configuration generator with `build_marvin=yes`:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  env_name=my-test-env \
  env_version=cs410 \
  mgmt_os=7 \
  hvtype=k \
  kvm_os=7 \
  hv=2 \
  pri=2 \
  sec=1 \
  build_marvin=yes \
  env_accounts=all \
  wait_till_setup=yes'
```

**Key Parameters:**
- `build_marvin=yes` - **REQUIRED** to create the Marvin box
- `env_name` - Your environment name
- `env_version` - CloudStack version (cs410, cs49, etc.)
- `mgmt_os` - Management OS (6=CentOS6, 7=CentOS7, u=Ubuntu)
- `hvtype` - Hypervisor type (k=KVM, x=XenServer, v=VMware)
- `hv` - Number of hypervisors
- `pri` - Number of primary storage pools
- `wait_till_setup=yes` - Wait for system VMs to be running

### Step 3: Deploy the Environment

After generation completes, deploy the VMs:

```bash
ansible-playbook deployvms.yml -i ./hosts_my-test-env --extra-vars 'env_name=my-test-env env_version=cs410'
```

This will:
1. Create the Marvin VM in your parent cloud
2. Install Marvin and CloudStack integration tests
3. Configure iSCSI target for storage tests
4. Generate test configuration files
5. Set up test scripts in `/marvin/` directory

## Marvin Box Details

### What Gets Installed

Once deployed, the Marvin box contains:

**Directory Structure:**
```
/marvin/
├── smoketests.sh              # Smoke test runner
├── componenttests.sh          # Component test runner
├── runtests.sh                # Main test runner
├── additionaltests.sh         # Additional tests
├── test_data.py               # Test data configuration
├── <env-name>-advanced-cfg    # Marvin config file
├── tests/                     # CloudStack integration tests
├── tools/                     # Test utilities
│   └── xunit-reader.py        # XUnit result parser
├── error/                     # Failed test results
└── pass/                      # Passed test results
```

**Installed Packages:**
- `cloudstack-marvin` - Marvin testing framework
- `cloudstack-integration-tests` - Full test suite
- Python dependencies for test execution
- iSCSI utilities for storage testing

### Accessing the Marvin Box

After deployment, find the IP address from the inventory:

```bash
cat hosts_my-test-env | grep marvin
```

SSH to the box:
```bash
ssh root@<marvin-ip>
# Password: As set in def_marvin_password (default: P@ssword123)
```

### Running Tests

**Smoke Tests:**
```bash
cd /marvin
./smoketests.sh
```

**Component Tests:**
```bash
cd /marvin
./componenttests.sh
```

**Custom Tests:**
```bash
cd /marvin
nosetests --with-marvin --marvin-config=<env-name>-advanced-cfg \
  -s -a tags=advanced tests/smoke/test_vm_life_cycle.py
```

## Advanced Configuration

### Custom Service Offering

Override the default service offering:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  ... \
  build_marvin=yes \
  marvin_service_offering="Custom-Marvin-Offering"'
```

### Custom Template

Use a different template:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  ... \
  build_marvin=yes \
  marvin_server_template="CentOS-8-Marvin"'
```

### Multiple Networks

If your Marvin box needs to be on a specific network:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  ... \
  build_marvin=yes \
  marvin_network="test-network"'
```

### Test Categories

Specify which test categories to run:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  ... \
  build_marvin=yes \
  marvin_test_categories="smoke,component"'
```

## Example: Complete Setup for UI Automation

Here's a complete example for setting up a Marvin box as a UI automation control plane:

```bash
# Step 1: Generate config
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  env_name=ui-automation-env \
  env_comment="UI automation test control plane" \
  env_version=cs410 \
  mgmt_os=7 \
  hvtype=k \
  kvm_os=7 \
  hv=2 \
  pri=2 \
  sec=1 \
  build_marvin=yes \
  env_accounts=all \
  wait_till_setup=yes \
  wait_for_template=yes \
  marvin_network="mgmt-network" \
  marvin_service_offering="Medium Instance"' \
  -i localhost

# Step 2: Deploy VMs
ansible-playbook deployvms.yml \
  -i ./hosts_ui-automation-env \
  --extra-vars 'env_name=ui-automation-env env_version=cs410'

# Step 3: Get Marvin IP
MARVIN_IP=$(cat hosts_ui-automation-env | grep marvin | awk '{print $2}' | cut -d'=' -f2)
echo "Marvin Box IP: $MARVIN_IP"

# Step 4: Access and verify
ssh root@$MARVIN_IP
cd /marvin
ls -la
```

## Troubleshooting

### Marvin Box Not Created

**Issue:** No Marvin VM appears after deployment

**Solution:** 
- Ensure `build_marvin=yes` was set in generate-cloudconfig
- Check inventory file: `cat hosts_<env-name> | grep marvin`
- Verify template exists: Check parent cloud for "Marvin iSCSI" template

### Template Not Found

**Issue:** Error about missing template

**Solution:**
- List available templates in parent cloud
- Update `marvin_server_template` to match existing template
- Or create/register the required template

### Network Issues

**Issue:** Marvin VM has no IP or wrong network

**Solution:**
- Verify network name: `marvin_network="correct-network-name"`
- Ensure network exists in parent cloud
- Check network is available in the build zone

### SSH Access Denied

**Issue:** Cannot SSH to Marvin box

**Solution:**
- Verify password matches `def_marvin_password` in group_vars/all
- Check if VM is running in parent cloud
- Verify security groups allow SSH (port 22)

## Integration with CI/CD

The Marvin box can be integrated into CI/CD pipelines:

```bash
# Example Jenkins/GitLab CI script
export MARVIN_IP="10.x.x.x"
ssh root@$MARVIN_IP "cd /marvin && ./smoketests.sh"
scp root@$MARVIN_IP:/marvin/pass/*.xml ./test-results/
```

## Cleanup

To destroy the environment including the Marvin box:

```bash
ansible-playbook destroyvms.yml -i ./hosts_ui-automation-env
```

## Additional Resources

- Marvin role tasks: `Ansible/roles/marvin/tasks/main.yml`
- Test templates: `Ansible/roles/marvin/templates/`
- Build VMs task: `Ansible/tasks/buildvms.yml` (lines 620-676)
- Inventory template: `Ansible/templates/nestedinventory.j2` (line 130-133)

## Summary

To create a Marvin Box for UI automation testing:

1. **Set `build_marvin=yes`** when running `generate-cloudconfig.yml`
2. **Configure** the required templates and networks in `group_vars/all`
3. **Deploy** using `deployvms.yml`
4. **Access** the VM and use the pre-configured test scripts in `/marvin/`

The Marvin box acts as your test control plane with all necessary tools and configurations ready for CloudStack testing and automation.
