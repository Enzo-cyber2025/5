#!/bin/bash
echo "hello world"
echo "run=$GITHUB_RUN_ID"
echo "test_val=hello" >> "$GITHUB_OUTPUT"
