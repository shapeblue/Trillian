#!/usr/bin/env python2
import json
import sys
from jinja2 import Environment, FileSystemLoader

# Get command line arguments
vars_file = sys.argv[1]      # JSON file with variables
template_file = sys.argv[2]  # Template file path
output_file = sys.argv[3]    # Output file path

# Load variables from JSON
with open(vars_file, 'r') as f:
    vars_dict = json.load(f)

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
env = Environment(loader=FileSystemLoader('.'))
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
