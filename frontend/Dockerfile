# Stage 1: Build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Accept build-time env vars for Vite
ARG VITE_API_URL
ARG VITE_GOOGLE_CLIENT_ID
# Write .env.production so Vite picks them up
RUN if [ -n "$VITE_API_URL" ]; then \
      echo "VITE_API_URL=$VITE_API_URL" > .env.production; \
      echo "VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID" >> .env.production; \
    fi
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
