const express = require('express');
const redis = require('redis');
const cors = require('cors');
const helmet = require('helmet');
const promClient = require('prom-client');

const app = express();
const PORT = process.env.PORT || 3000;
const APP_VERSION = process.env.APP_VERSION || '1.0.0';
const REDIS_URL = process.env.REDIS_URL || 'redis://redis-service:6379';

// Prometheus metrics
const register = new promClient.Registry();

// Collect default metrics
promClient.collectDefaultMetrics({ register });

const httpRequestDuration = new promClient.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.1, 0.3, 0.5, 0.7, 1, 3, 5, 7, 10],
  registers: [register]
});

const httpRequestTotal = new promClient.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

const appInfo = new promClient.Gauge({
  name: 'app_info',
  help: 'Application information',
  labelNames: ['version'],
  registers: [register]
});

// Set app version metric
appInfo.set({ version: APP_VERSION }, 1);

// Redis client setup
let redisClient;
let redisConnected = false;

async function connectRedis() {
  try {
    redisClient = redis.createClient({ url: REDIS_URL });

    redisClient.on('error', (err) => {
      console.error('Redis Client Error:', err);
      redisConnected = false;
    });

    redisClient.on('connect', () => {
      console.log('Redis Client Connected');
      redisConnected = true;
    });

    await redisClient.connect();

    // Initialize some test data
    await redisClient.set('app:counter', '0');
    await redisClient.set('app:version', APP_VERSION);
    await redisClient.set('app:startup_time', new Date().toISOString());

  } catch (error) {
    console.error('Failed to connect to Redis:', error);
    redisConnected = false;
  }
}

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());

// Metrics middleware
app.use((req, res, next) => {
  const start = Date.now();

  res.on('finish', () => {
    const duration = (Date.now() - start) / 1000;
    const route = req.route ? req.route.path : req.path;

    httpRequestDuration
      .labels(req.method, route, res.statusCode.toString())
      .observe(duration);

    httpRequestTotal
      .labels(req.method, route, res.statusCode.toString())
      .inc();
  });

  next();
});

// Health check endpoints
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'healthy',
    version: APP_VERSION,
    timestamp: new Date().toISOString(),
    uptime: process.uptime()
  });
});

app.get('/health/live', (req, res) => {
  // Liveness probe - should only fail if app is completely broken
  res.status(200).json({
    status: 'alive',
    version: APP_VERSION
  });
});

app.get('/health/ready', async (req, res) => {
  // Readiness probe - should fail if app can't serve traffic
  try {
    if (!redisConnected) {
      throw new Error('Redis not connected');
    }

    // Test Redis connection
    await redisClient.ping();

    res.status(200).json({
      status: 'ready',
      version: APP_VERSION,
      dependencies: {
        redis: 'connected'
      }
    });
  } catch (error) {
    res.status(503).json({
      status: 'not ready',
      version: APP_VERSION,
      error: error.message,
      dependencies: {
        redis: 'disconnected'
      }
    });
  }
});

// Metrics endpoint
app.get('/metrics', async (req, res) => {
  try {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  } catch (error) {
    res.status(500).end(error);
  }
});

// API endpoints
app.get('/', async (req, res) => {
  try {
    let counter = 0;
    let version = APP_VERSION;
    let startupTime = 'unknown';

    if (redisConnected) {
      counter = parseInt(await redisClient.get('app:counter') || '0');
      version = await redisClient.get('app:version') || APP_VERSION;
      startupTime = await redisClient.get('app:startup_time') || 'unknown';

      // Increment counter
      await redisClient.incr('app:counter');
    }

    res.json({
      message: '🚀 Service Mesh Test Application v2 - Enhanced Edition',
      version: version,
      counter: counter + 1,
      startup_time: startupTime,
      timestamp: new Date().toISOString(),
      hostname: require('os').hostname(),
      redis_connected: redisConnected,
      features: ['Enhanced UI', 'Improved Performance', 'Canary Deployment']
    });
  } catch (error) {
    res.status(500).json({
      error: 'Internal server error',
      message: error.message,
      version: APP_VERSION
    });
  }
});

app.get('/api/data', async (req, res) => {
  try {
    if (!redisConnected) {
      return res.status(503).json({
        error: 'Service unavailable',
        message: 'Database connection not available'
      });
    }

    const data = {
      items: [
        { id: 1, name: 'Item 1', version: APP_VERSION },
        { id: 2, name: 'Item 2', version: APP_VERSION },
        { id: 3, name: 'Item 3', version: APP_VERSION }
      ],
      total_requests: parseInt(await redisClient.get('app:counter') || '0'),
      app_version: APP_VERSION,
      timestamp: new Date().toISOString()
    };

    res.json(data);
  } catch (error) {
    res.status(500).json({
      error: 'Internal server error',
      message: error.message
    });
  }
});

// Simulate load endpoint for testing
app.post('/api/load/:duration?', async (req, res) => {
  const duration = parseInt(req.params.duration) || 100;
  const start = Date.now();

  // Simulate some work
  while (Date.now() - start < duration) {
    Math.random() * Math.random();
  }

  res.json({
    message: 'Load simulation completed',
    duration_ms: duration,
    actual_duration_ms: Date.now() - start,
    version: APP_VERSION
  });
});

// Graceful shutdown endpoint (for testing)
app.post('/admin/shutdown', (req, res) => {
  res.json({ message: 'Shutting down gracefully...', version: APP_VERSION });
  setTimeout(() => {
    process.exit(0);
  }, 1000);
});

// Error handling
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({
    error: 'Something went wrong!',
    version: APP_VERSION
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    error: 'Not found',
    path: req.path,
    version: APP_VERSION
  });
});

// Graceful shutdown handling
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully');
  if (redisClient) {
    await redisClient.quit();
  }
  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('SIGINT received, shutting down gracefully');
  if (redisClient) {
    await redisClient.quit();
  }
  process.exit(0);
});

// Start server
async function startServer() {
  await connectRedis();

  app.listen(PORT, () => {
    console.log(`🚀 Mesh Test App v${APP_VERSION} listening on port ${PORT}`);
    console.log(`📊 Metrics available at http://localhost:${PORT}/metrics`);
    console.log(`🏥 Health check at http://localhost:${PORT}/health`);
    console.log(`📡 Redis connected: ${redisConnected}`);
  });
}

startServer().catch(console.error);

module.exports = app;