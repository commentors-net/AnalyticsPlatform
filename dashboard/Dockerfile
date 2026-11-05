# Production Nginx Container for Standalone Dashboard SPA
FROM nginx:1.25-alpine-slim

# Remove default nginx config
RUN rm -rf /etc/nginx/conf.d/*

# Copy custom nginx configuration
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf

# Copy static dashboard SPA assets
COPY dashboard/ /usr/share/nginx/html/dashboard/

# Expose HTTP port
EXPOSE 80

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1:80/dashboard/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
