#!/bin/sh

set -eu

# Enable HTTP Basic Auth when BASIC_AUTH_ENABLED=true.
AUTH_BASIC_DIRECTIVE=""
AUTH_BASIC_USER_FILE_DIRECTIVE=""
if [ "${BASIC_AUTH_ENABLED:-false}" = "true" ]; then
	AUTH_BASIC_DIRECTIVE='auth_basic "Restricted Demo";'
	AUTH_BASIC_USER_FILE_DIRECTIVE='auth_basic_user_file /etc/nginx/.htpasswd;'
fi

# envsubst only substitutes environment variables, so export the generated
# auth directives before rendering nginx.conf from the template.
export AUTH_BASIC_DIRECTIVE
export AUTH_BASIC_USER_FILE_DIRECTIVE

# Substitute environment variables in nginx config template
envsubst '${BACKEND_URL} ${AUTH_BASIC_DIRECTIVE} ${AUTH_BASIC_USER_FILE_DIRECTIVE}' \
	< /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Start nginx
exec nginx -g 'daemon off;'
