#!/bin/bash
set -eux
which gh
gh auth status || true
gh issue comment 7 --body "hello wlh from gh CLI run=$GITHUB_RUN_ID sha=$(echo $GITHUB_SHA|cut -c1-8)"
echo OK
