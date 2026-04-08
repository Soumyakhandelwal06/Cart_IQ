/**
 * CartIQ API Gateway — Main Server
 * Orchestrates NL query parsing, scraping dispatch, and SSE streaming
 */
require('dotenv').config();
require('./db/mongoose'); // Connect to MongoDB
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');

const queryRouter = require('./routes/query');
const streamRouter = require('./routes/stream');
const authRouter = require('./routes/auth');
const platformsRouter = require('./routes/platforms');

const app = express();
const PORT = process.env.PORT || 3001;

// ── Security Middleware ────────────────────────────────────────────────────────
app.use(helmet({ crossOriginResourcePolicy: false }));
app.use(cors({ 
  origin: [
    'http://localhost:3000', 
    'http://localhost:3003'
  ],
  credentials: true
}));
app.use(morgan('dev'));
app.use(express.json({ limit: '10kb' }));

// Rate limiting — 30 requests / minute per IP
const limiter = rateLimit({
  windowMs: 60 * 1000,
  max: 30,
  message: { error: 'Too many requests. Please slow down.' }
});
app.use('/api/', limiter);

// ── Routes ────────────────────────────────────────────────────────────────────
app.use('/api/v1/auth', authRouter);
app.use('/api/v1/query', queryRouter);
app.use('/api/v1/stream', streamRouter);
app.use('/api/v1/platforms', platformsRouter);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'api-gateway', timestamp: new Date().toISOString() });
});

// 404 catch-all
app.use((req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

// Global error handler
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  console.log(`\n🚀 CartIQ API Gateway running on http://localhost:${PORT}`);
  console.log(`📡 SSE Stream endpoint: http://localhost:${PORT}/api/v1/stream/:search_id`);
});
