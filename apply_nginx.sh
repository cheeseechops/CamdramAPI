#!/bin/bash
# Insert CamDram proxy into nginx jarvis config. Run with: sudo ./apply_nginx.sh

set -e
NGINX_CONF="/etc/nginx/sites-available/jarvis"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$NGINX_CONF" ]; then
  echo "Not found: $NGINX_CONF"
  exit 1
fi

# Insert the camdram location block after "location = /visage {" ... "}" and before "location ^~ /visage/"
# Using a temp file to avoid sed portability issues
BLOCK=$(cat <<'EOF'

    # CamDram API & UI (under /visage so it's reachable from the visage area)
    location ^~ /visage/camdram/ {
        proxy_pass http://127.0.0.1:5002/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix /visage/camdram;
    }

EOF
)

if grep -q 'location \^~ /visage/camdram/' "$NGINX_CONF"; then
  echo "CamDram block already present in $NGINX_CONF"
  exit 0
fi

# Insert after the line "    }" that follows "location = /visage" and before "    location ^~ /visage/"
awk '
  /location = \/visage/ { found_visage=1; print; next }
  found_visage && /^    \}$/ && !inserted {
    print
    print "    "
    print "    # CamDram API & UI (under /visage so it'"'"'s reachable from the visage area)"
    print "    location ^~ /visage/camdram/ {"
    print "        proxy_pass http://127.0.0.1:5002/;"
    print "        proxy_set_header Host $host;"
    print "        proxy_set_header X-Real-IP $remote_addr;"
    print "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"
    print "        proxy_set_header X-Forwarded-Proto $scheme;"
    print "        proxy_set_header X-Forwarded-Prefix /visage/camdram;"
    print "    }"
    print "    "
    inserted=1
    found_visage=0
    next
  }
  { print }
' "$NGINX_CONF" > "$NGINX_CONF.new" && mv "$NGINX_CONF.new" "$NGINX_CONF"
echo "Added CamDram block to $NGINX_CONF"
echo "Reload nginx: sudo nginx -t && sudo systemctl reload nginx"
exit 0
