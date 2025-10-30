#!/usr/bin/env python2
import json
import sys
from jinja2 import Environment, FileSystemLoader, Undefined

# Get command line arguments
vars_file = sys.argv[1]      # JSON file with variables
template_file = sys.argv[2]  # Template file path
output_file = sys.argv[3]    # Output file path

# Load variables from JSON
with open(vars_file, 'r') as f:
    vars_dict = json.load(f)\
    
# Pre-populate missing password variables with their def_ versions
password_vars = [
    'mgmtsrv_password',
    'kvm_password', 
    'xs_password',
    'vmware_esxi_password',
    'dbsrv_password',
    'marvin_password',
    'playwright_password',
    'pri_password',
    'pri_password_iscsi',
    'sec_password'
]

print("=== Password Variable Population Debug ===")
for var in password_vars:
    if var not in vars_dict or not vars_dict[var]:
        def_var = 'def_' + var
        if def_var in vars_dict:
            print("Populating {} from {} = {}".format(var, def_var, vars_dict[def_var]))
            vars_dict[var] = vars_dict[def_var]
        else:
            print("WARNING: {} not in vars_dict and {} not found".format(var, def_var))
    else:
        print("OK: {} already set to {}".format(var, vars_dict[var]))
print("=== End Password Debug ===")

class SilentUndefined(Undefined):
    """Return None for undefined variables instead of raising errors"""
    def _fail_with_undefined_error(self, *args, **kwargs):
        return None
    def __str__(self):
        return ''
    def __bool__(self):
        return False

# Define custom filters to match Ansible's behavior
def bool_filter(value):
    """Convert value to boolean like Ansible does"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ['true', 'yes', '1', 'y']
    return bool(value)

def to_json_filter(value, *args, **kwargs):
    """Convert to JSON"""
    return json.dumps(value)

def default_filter(value, default='', boolean=False):
    """Provide default value if undefined/none"""
    if boolean:
        return value if value else default
    return value if value is not None else default

# Setup Jinja2 with custom filters
env = Environment(loader=FileSystemLoader('.'), undefined=SilentUndefined)
env.filters['bool'] = bool_filter
env.filters['to_json'] = to_json_filter
env.filters['default'] = default_filter

template = env.get_template(template_file)

# Render
output = template.render(**vars_dict)

# Write
with open(output_file, 'w') as f:
    f.write(output)

print('Created: ' + output_file)
