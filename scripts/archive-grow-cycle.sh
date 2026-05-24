#!/bin/bash
# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# License: MIT
#
# archive-grow-cycle.sh — Package a completed grow cycle for offsite storage
# Usage: bash archive-grow-cycle.sh <cycle-name>
# Example: bash archive-grow-cycle.sh grow-cycle-02-lions-mane-may24

set -euo pipefail

MYCODO_SKILL_BASE="${MYCODO_SKILL_BASE:-$HOME/.mycodo}"
CYCLE_NAME="${1:-grow-cycle-$(date +%Y%m%d)}"
SOURCE_DIR="${MYCODO_SKILL_BASE}/output"
ARCHIVE_DIR="${MYCODO_SKILL_BASE}/archive"
DEST_DIR="$ARCHIVE_DIR/$CYCLE_NAME"

echo "=== Mycodo Grow Cycle Archive ==="
echo "Cycle name: $CYCLE_NAME"

# Count files before
HTML_COUNT=$(find "$SOURCE_DIR" -name 'mycodo_report_*.html' | wc -l)
JPG_COUNT=$(find "$SOURCE_DIR" -name 'mycodo_report_*.jpg' | wc -l)
TOTAL_MB=$(du -sm "$SOURCE_DIR" | cut -f1)

echo "Files found: $HTML_COUNT HTML + $JPG_COUNT JPG ($TOTAL_MB MB)"

if [ "$HTML_COUNT" -eq 0 ]; then
    echo "Nothing to archive in $SOURCE_DIR"
    exit 0
fi

mkdir -p "$DEST_DIR"

# Move all current reports to archive
find "$SOURCE_DIR" -maxdepth 1 -name 'mycodo_report_*' -exec mv {} "$DEST_DIR/" \;

echo "Archived to: $DEST_DIR"
echo "Size: $(du -sh "$DEST_DIR" | cut -f1)"
echo ""
echo "Next steps:"
echo "  1. Review: ls $DEST_DIR"
echo "  2. Tarball: tar czf ${CYCLE_NAME}.tar.gz -C $ARCHIVE_DIR $CYCLE_NAME"
echo "  3. Move to external drive or cloud storage"
echo "  4. Next cycle will start fresh in $SOURCE_DIR"
