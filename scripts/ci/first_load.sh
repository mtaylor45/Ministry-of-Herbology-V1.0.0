#!/bin/sh
# The web app's first load, cold, as a Markdown section. The deployment.
#
# The document, then every script, stylesheet and preload it names under
# /_app/, fetched once each the way a first visit fetches them (no cache).
# Reports bytes on the wire, time to first byte and total time, and each
# asset's Cache-Control, because whether a second visit refetches them is
# Nginx's to decide.
set -eu
base=${MOH_BASE:-https://localhost}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -sk --compressed -o "$tmp/index.html" \
    -w '%{time_starttransfer} %{time_total} %{size_download}\n' "$base/" > "$tmp/doc"
read -r ttfb total size < "$tmp/doc"

grep -oE '(href|src)="/_app/[^"]+"' "$tmp/index.html" | sed -E 's/^(href|src)="//; s/"$//' \
    | sort -u > "$tmp/assets"

assets=0; asset_bytes=0; asset_time=0; caching=""
while read -r path; do
    out=$(curl -sk --compressed -D "$tmp/h" -o /dev/null \
        -w '%{time_total} %{size_download}' "$base$path")
    t=${out% *}; b=${out#* }
    assets=$((assets + 1)); asset_bytes=$((asset_bytes + b))
    asset_time=$(awk -v a="$asset_time" -v b="$t" 'BEGIN{print a+b}')
    cc=$(tr -d '\r' < "$tmp/h" | sed -n 's/^[Cc]ache-[Cc]ontrol: //p' | head -n 1)
    caching="$caching${cc:-none}\n"
done < "$tmp/assets"

ms() { awk -v s="$1" 'BEGIN{printf "%.1f", s*1000}'; }
echo
echo "### Web app, first load (cold, sequential)"
echo
echo "| | value |"
echo "| --- | ---: |"
echo "| document: time to first byte | $(ms "$ttfb") ms |"
echo "| document: total | $(ms "$total") ms, $size bytes |"
echo "| /_app/ assets named by the document | $assets |"
echo "| assets: total bytes (compressed) | $asset_bytes |"
echo "| assets: sum of fetch times | $(ms "$asset_time") ms |"
echo
echo "Cache-Control on those assets: $(printf "$caching" | sort | uniq -c | sed 's/^ *//' | paste -sd ';' -)"
