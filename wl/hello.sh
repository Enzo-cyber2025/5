#!/bin/bash
set -eux
echo "hello"
sudo apt-get update -q
sudo apt-get install -y wget unzip
echo "apt done"
which wget
