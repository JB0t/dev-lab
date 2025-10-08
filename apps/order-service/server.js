const express = require('express');
const { createClient } = require('redis');

const app = express();
const port = process.env.PORT || 3000;
const version = process.env.APP_VERSION || 'v1';

// In-memory counters (fallback when Redis is not available)
let orderCount = 0;
let totalOrders = 0;

// Redis configuration - only connect if explicitly configured
const redisUrl = process.env.REDIS_URL;
let redisClient = null;

// Initialize Redis client only if REDIS_URL is provided
async function initRedis() {
  if (!redisUrl) {
    console.log('No Redis URL configured - running without Redis');
    return;
  }

  try {
    redisClient = createClient({ url: redisUrl });

    redisClient.on('error', (err) => {
      console.log('Redis Client Error', err);
      // Continue without Redis
      redisClient = null;
    });

    redisClient.on('connect', () => {
      console.log('Connected to Redis');
    });

    await redisClient.connect();
  } catch (error) {
    console.error('Failed to connect to Redis:', error);
    console.log('Continuing without Redis...');
    redisClient = null;
  }
}// Middleware
app.use(express.json());

// Request logging middleware
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} - ${req.method} ${req.path} - ${req.ip}`);
  next();
});

// Health check endpoints
app.get('/health/live', (req, res) => {
  res.status(200).json({
    status: 'alive',
    service: 'order-service',
    version: version,
    timestamp: new Date().toISOString()
  });
});

app.get('/health/ready', async (req, res) => {
  try {
    // Check Redis connectivity
    if (redisClient) {
      await redisClient.ping();
    }

    res.status(200).json({
      status: 'ready',
      service: 'order-service',
      version: version,
      redis: redisClient ? 'connected' : 'disconnected',
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    res.status(503).json({
      status: 'not ready',
      service: 'order-service',
      version: version,
      error: error.message,
      timestamp: new Date().toISOString()
    });
  }
});

// Main order endpoint
app.get('/', async (req, res) => {
  try {
    let currentOrderCount = 0;

    if (redisClient) {
      // Increment order counter in Redis
      currentOrderCount = await redisClient.incr('order:count');
    } else {
      // Use in-memory counter
      orderCount++;
      currentOrderCount = orderCount;
    }

    const response = {
      service: 'order-service',
      version: version,
      message: 'Order Service is running!',
      orders_processed: currentOrderCount,
      uptime: process.uptime(),
      timestamp: new Date().toISOString(),
      node_env: process.env.NODE_ENV || 'development',
      redis_connected: !!redisClient
    };

    res.json(response);
  } catch (error) {
    console.error('Error in main endpoint:', error);
    res.status(500).json({
      service: 'order-service',
      version: version,
      error: 'Internal server error',
      timestamp: new Date().toISOString()
    });
  }
});// Order creation endpoint
app.post('/orders', async (req, res) => {
  try {
    const orderId = Math.random().toString(36).substr(2, 9);
    const order = {
      id: orderId,
      status: 'created',
      items: req.body.items || [],
      total: req.body.total || 0,
      created_at: new Date().toISOString(),
      version: version
    };

    if (redisClient) {
      // Store order in Redis
      await redisClient.setEx(`order:${orderId}`, 3600, JSON.stringify(order));
      // Increment total orders
      await redisClient.incr('order:total');
    }

    res.status(201).json(order);
  } catch (error) {
    console.error('Error creating order:', error);
    res.status(500).json({
      error: 'Failed to create order',
      timestamp: new Date().toISOString()
    });
  }
});

// Get order by ID
app.get('/orders/:id', async (req, res) => {
  try {
    const orderId = req.params.id;

    if (redisClient) {
      const orderData = await redisClient.get(`order:${orderId}`);
      if (orderData) {
        res.json(JSON.parse(orderData));
        return;
      }
    }

    res.status(404).json({
      error: 'Order not found',
      id: orderId,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('Error retrieving order:', error);
    res.status(500).json({
      error: 'Failed to retrieve order',
      timestamp: new Date().toISOString()
    });
  }
});

// Order statistics endpoint
app.get('/stats', async (req, res) => {
  try {
    let stats = {
      service: 'order-service',
      version: version,
      processed_requests: 0,
      total_orders: 0,
      uptime: process.uptime(),
      timestamp: new Date().toISOString()
    };

    if (redisClient) {
      const processedRequests = await redisClient.get('order:count');
      const totalOrders = await redisClient.get('order:total');

      stats.processed_requests = parseInt(processedRequests) || 0;
      stats.total_orders = parseInt(totalOrders) || 0;
    }

    res.json(stats);
  } catch (error) {
    console.error('Error getting stats:', error);
    res.status(500).json({
      error: 'Failed to get statistics',
      timestamp: new Date().toISOString()
    });
  }
});

// Metrics endpoint (Prometheus-style)
app.get('/metrics', async (req, res) => {
  try {
    let processedRequests = 0;
    let totalOrders = 0;

    if (redisClient) {
      processedRequests = parseInt(await redisClient.get('order:count')) || 0;
      totalOrders = parseInt(await redisClient.get('order:total')) || 0;
    }

    const metrics = `# HELP order_service_requests_total Total number of requests processed
# TYPE order_service_requests_total counter
order_service_requests_total{service="order-service",version="${version}"} ${processedRequests}

# HELP order_service_orders_total Total number of orders created
# TYPE order_service_orders_total counter
order_service_orders_total{service="order-service",version="${version}"} ${totalOrders}

# HELP order_service_uptime_seconds Service uptime in seconds
# TYPE order_service_uptime_seconds gauge
order_service_uptime_seconds{service="order-service",version="${version}"} ${process.uptime()}
`;

    res.set('Content-Type', 'text/plain');
    res.send(metrics);
  } catch (error) {
    console.error('Error generating metrics:', error);
    res.status(500).send('Error generating metrics');
  }
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully');

  if (redisClient) {
    await redisClient.disconnect();
  }

  process.exit(0);
});

// Start server
async function startServer() {
  await initRedis();

  app.listen(port, () => {
    console.log(`Order Service ${version} running on port ${port}`);
    console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
    if (redisUrl) {
      console.log(`Redis URL: ${redisUrl}`);
      console.log(`Redis Status: ${redisClient ? 'connected' : 'failed'}`);
    } else {
      console.log('Redis: disabled (no REDIS_URL configured)');
    }
  });
}

startServer().catch((error) => {
  console.error('Failed to start server:', error);
  process.exit(1);
});