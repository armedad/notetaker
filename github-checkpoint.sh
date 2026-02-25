#!/bin/bash
# github-checkpoint.sh - Commit and push changes in notetaker
#
# Usage:
#   ./github-checkpoint.sh "Your commit message here"
#
# Examples:
#   ./github-checkpoint.sh "Fix transcription bug"
#   ./github-checkpoint.sh "Add audio compression support"
#
# The script will:
#   1. Show any uncommitted changes
#   2. Stage all changes (git add -A)
#   3. Commit with your message
#   4. Push to remote

set -e

cd "$(dirname "$0")"

# Check for commit message argument
if [[ -z "$1" ]]; then
    echo "Usage: ./github-checkpoint.sh \"Your commit message\""
    echo ""
    echo "Examples:"
    echo "  ./github-checkpoint.sh \"Fix transcription bug\""
    echo "  ./github-checkpoint.sh \"Add audio compression support\""
    exit 1
fi

commit_msg="$1"

# Check if there are any changes
if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    echo "✓ No changes to commit"
    exit 0
fi

echo "📁 Changes detected:"
git status --short
echo ""

# Stage all changes
git add -A

echo "Commit: $commit_msg"
git commit -m "$commit_msg"

echo ""
echo "Pushing..."
git push

echo ""
echo "✅ Done"
