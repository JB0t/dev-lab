FROM node:18-alpine

# Create app directory
WORKDIR /usr/src/app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --omit=dev && npm cache clean --force

# Copy app source
COPY . .

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
  adduser -S app -u 1001

# Change ownership of app directory
RUN chown -R app:nodejs /usr/src/app
USER app

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health/live', (res) => { process.exit(res.statusCode === 200 ? 0 : 1) }).on('error', () => process.exit(1))"

# Reduce file system monitoring noise
ENV NODE_OPTIONS="--max-old-space-size=256"

# Start the application
CMD ["npm", "start"]