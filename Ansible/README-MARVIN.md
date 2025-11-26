# Marvin Box Quick Reference

For detailed instructions on creating and using a Marvin Box for UI automation testing, see the main [Marvin Box Setup Guide](../MARVIN_BOX_SETUP_GUIDE.md).

## Quick Start

To add a Marvin Box to your environment, use `build_marvin=yes` when generating config:

```bash
ansible-playbook generate-cloudconfig.yml --extra-vars '\
  env_name=my-test-env \
  env_version=cs410 \
  mgmt_os=7 \
  hvtype=k kvm_os=7 \
  hv=2 pri=2 \
  build_marvin=yes \
  env_accounts=all'
```

Then deploy:
```bash
ansible-playbook deployvms.yml -i ./hosts_my-test-env
```

## Configuration

Configure Marvin settings in `group_vars/all`:

```yaml
def_marvin_network: "your-network-name"
def_marvin_service_offering: "Marvin"
def_marvin_server_template: "Marvin iSCSI"
```

## What You Get

The Marvin Box includes:
- Marvin testing framework
- CloudStack integration tests
- Pre-configured test scripts in `/marvin/`
- iSCSI target for storage testing
- CloudMonkey CLI tool

## Learn More

See the complete [Marvin Box Setup Guide](../MARVIN_BOX_SETUP_GUIDE.md) for:
- Detailed configuration options
- Running tests
- Troubleshooting
- CI/CD integration
- Advanced examples
