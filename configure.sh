#!/bin/sh

PYTHON_VERSION="2.7.11"

pyenv install -s $PYTHON_VERSION
pyenv virtualenv $PYTHON_VERSION trillian
pyenv rehash

pip install -IUr requirements.txt
pyenv rehash
