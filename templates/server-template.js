const express = require('express');
const app = express();
const port = process.env.PORT || PORT_PLACEHOLDER;
const version = process.env.APP_VERSION || 'v1';

app.use(express.json());

// Request logging middleware
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} - ${req.method} ${req.path} - ${req.ip}`);
  next();
});

// Health endpoints (REQUIRED)
app.get('/health/live', (req, res) => {
  res.status(200).json({
    status: 'alive',
    service: 'SERVICE_NAME_PLACEHOLDER',
    version: version,
    timestamp: new Date().toISOString()
  });
});

app.get('/health/ready', (req, res) => {
  res.status(200).json({
    status: 'ready',
    service: 'SERVICE_NAME_PLACEHOLDER',
    version: version,
    timestamp: new Date().toISOString()
  });
});

// Main endpoint
app.get('/', (req, res) => {
  res.json({
    service: 'SERVICE_NAME_PLACEHOLDER',
    version: version,
    message: 'SERVICE_NAME_PLACEHOLDER is running!',
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    node_env: process.env.NODE_ENV || 'development'
  });
});

// Metrics endpoint (basic)
app.get('/metrics', (req, res) => {
  const metrics = `# HELP SERVICE_NAME_PLACEHOLDER_uptime_seconds Service uptime in seconds
# TYPE SERVICE_NAME_PLACEHOLDER_uptime_seconds gauge
SERVICE_NAME_PLACEHOLDER_uptime_seconds{service="SERVICE_NAME_PLACEHOLDER",version="${version}"} ${process.uptime()}
`;
  res.set('Content-Type', 'text/plain');
  res.send(metrics);
});

// Graceful shutdown (REQUIRED)
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  process.exit(0);
});

app.listen(port, () => {
  console.log(`SERVICE_NAME_PLACEHOLDER ${version} running on port ${port}`);
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
});